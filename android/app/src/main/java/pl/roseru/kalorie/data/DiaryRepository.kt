package pl.roseru.kalorie.data

import android.content.Context
import androidx.room.withTransaction
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.MealType
import pl.roseru.kalorie.core.Nutrients
import pl.roseru.kalorie.core.normalizeSearch
import java.time.*
import java.util.UUID

class DiaryRepository(private val db: CalorieDatabase, private val context: Context) {
    val dao = db.dao()
    companion object { const val GUEST = "guest" }
    suspend fun initialize() = withContext(Dispatchers.IO) {
        val catalog = readCatalog("products-v1.json")
        val rationCatalog = readCatalog("rations-v1.json")
        val entries = readProducts(catalog) + readProducts(rationCatalog)
        val rationRows = rationCatalog.getJSONArray("rations")
        val rations = mutableListOf<RationEntity>()
        val components = mutableListOf<RationComponentEntity>()
        for (i in 0 until rationRows.length()) {
            val row = rationRows.getJSONObject(i)
            val id = row.getString("id")
            rations += RationEntity(id, row.getString("name"), row.getString("description"),
                rationCatalog.getString("source"), rationCatalog.getInt("version"))
            val parts = row.getJSONArray("components")
            for (j in 0 until parts.length()) {
                val part = parts.getJSONObject(j)
                components += RationComponentEntity(part.getString("id"), id, part.getString("productId"), part.getDouble("packageGrams"), j)
            }
        }
        db.withTransaction {
            dao.seedProducts(entries)
            dao.seedRations(rations)
            dao.seedComponents(components)
            dao.seedGoal(GoalEntity("guest-initial-goal", GUEST, "1970-01-01", 2800.0, 160.0, 90.0, 330.0))
        }
    }

    private fun readCatalog(file: String) = JSONObject(context.assets.open("catalog/$file").bufferedReader().use { it.readText() })
    private fun readProducts(catalog: JSONObject): List<ProductEntity> {
        val products = catalog.getJSONArray("products")
        return (0 until products.length()).map { i ->
            val product = products.getJSONObject(i)
            fun optional(key: String) = if (product.isNull(key)) null else product.getDouble(key)
            ProductEntity(product.getString("id"), product.getString("name"), normalizeSearch(product.getString("name")),
                product.getDouble("kcal"), optional("protein"), optional("fat"), optional("carbs"),
                product.getDouble("defaultGrams"), product.getString("category"), catalog.getString("source"), catalog.getInt("version"))
        }
    }

    suspend fun add(productId: String, grams: Double, type: MealType, date: LocalDate, id: String = UUID.randomUUID().toString()) = db.withTransaction {
        require(grams.isFinite() && grams > 0 && grams <= Nutrients.MAX_GRAMS)
        if (dao.meal(id, GUEST) != null) return@withTransaction
        val product = requireNotNull(dao.product(productId))
        val zone = ZoneId.systemDefault()
        val time = date.atTime(LocalTime.now()).atZone(zone).toInstant().toString()
        val meal = MealEntity(id, GUEST, date.toString(), time, zone.id, type.name)
        val item = MealItemEntity(UUID.randomUUID().toString(), id, product.id, product.name, grams,
            product.kcal, product.protein, product.fat, product.carbs)
        dao.insertMeal(meal)
        dao.insertItem(item)
        enqueue(meal, listOf(item), "create")
    }

    suspend fun edit(id: String, grams: Double) = db.withTransaction {
        val current = requireNotNull(dao.meal(id, GUEST))
        require(!current.meal.deleted && current.items.size == 1)
        editItem(id, current.items.single().id, grams)
    }

    suspend fun addRation(rationId: String, quantities: Map<String, Double>, type: MealType, date: LocalDate,
        id: String = UUID.randomUUID().toString()) = db.withTransaction {
        if (dao.meal(id, GUEST) != null) return@withTransaction
        val ration = requireNotNull(dao.ration(rationId))
        require(quantities.isNotEmpty() && quantities.keys.all { key -> ration.components.any { it.id == key } })
        val zone = ZoneId.systemDefault()
        val meal = MealEntity(id, GUEST, date.toString(), date.atTime(LocalTime.now()).atZone(zone).toInstant().toString(),
            zone.id, type.name, rationId = ration.ration.id, rationName = ration.ration.name)
        val items = ration.components.sortedBy { it.position }.mapNotNull { component ->
            val grams = quantities[component.id] ?: return@mapNotNull null
            require(grams.isFinite() && grams > 0 && grams <= Nutrients.MAX_GRAMS && grams <= component.packageGrams)
            val product = requireNotNull(dao.product(component.productId))
            MealItemEntity(UUID.randomUUID().toString(), id, product.id, product.name, grams,
                product.kcal, product.protein, product.fat, product.carbs, component.id)
        }
        dao.insertMeal(meal)
        items.forEach { dao.insertItem(it) }
        enqueue(meal, items, "create")
    }

    suspend fun editItem(id: String, itemId: String, grams: Double) = db.withTransaction {
        require(grams.isFinite() && grams > 0 && grams <= Nutrients.MAX_GRAMS)
        val current = requireNotNull(dao.meal(id, GUEST))
        require(!current.meal.deleted)
        val meal = current.meal.copy(localRevision = current.meal.localRevision + 1)
        val item = current.items.single { it.id == itemId }.copy(grams = grams)
        dao.updateMeal(meal)
        dao.updateItem(item)
        enqueue(meal, current.items.map { if (it.id == itemId) item else it }, "update")
    }

    suspend fun removeItem(id: String, itemId: String) = db.withTransaction {
        val current = requireNotNull(dao.meal(id, GUEST))
        require(!current.meal.deleted)
        val item = current.items.single { it.id == itemId }
        if (current.items.size == 1) { delete(id); return@withTransaction }
        val meal = current.meal.copy(localRevision = current.meal.localRevision + 1)
        dao.updateMeal(meal)
        dao.removeItem(item)
        enqueue(meal, current.items.filterNot { it.id == itemId }, "update")
    }

    suspend fun delete(id: String) = db.withTransaction {
        val current = requireNotNull(dao.meal(id, GUEST))
        if (current.meal.deleted) return@withTransaction
        val meal = current.meal.copy(deleted = true, localRevision = current.meal.localRevision + 1)
        dao.updateMeal(meal)
        enqueue(meal, current.items, "delete")
    }

    suspend fun setGoal(kcal: Double, protein: Double?, fat: Double?, carbs: Double?) = db.withTransaction {
        require(kcal.isFinite() && kcal > 0 && kcal <= 20_000)
        listOfNotNull(protein, fat, carbs).forEach { require(it.isFinite() && it >= 0 && it <= 5000) }
        val today = LocalDate.now().toString()
        val existing = dao.goalOn(GUEST, today)
        val goal = GoalEntity(existing?.id ?: UUID.randomUUID().toString(), GUEST, today, kcal, protein, fat, carbs)
        dao.saveGoal(goal)
        val payload = JSONObject().put("id", goal.id).put("valid_from", today).put("kcal", kcal)
            .put("protein", protein ?: JSONObject.NULL).put("fat", fat ?: JSONObject.NULL).put("carbs", carbs ?: JSONObject.NULL)
        dao.enqueue(OutboxEntity(UUID.randomUUID().toString(), GUEST, "goal", goal.id,
            if (existing == null) "create" else "update", null, payload.toString(), Instant.now().toString()))
    }

    private suspend fun enqueue(meal: MealEntity, items: List<MealItemEntity>, action: String) {
        val payload = JSONObject().put("id", meal.id).put("local_date", meal.localDate).put("occurred_at", meal.occurredAt)
            .put("zone_id", meal.zoneId).put("meal_type", meal.mealType).put("local_revision", meal.localRevision).put("deleted", meal.deleted)
            .put("ration_id", meal.rationId ?: JSONObject.NULL).put("ration_name", meal.rationName ?: JSONObject.NULL)
        val rows = JSONArray()
        items.forEach { item ->
            rows.put(JSONObject().put("id", item.id).put("product_id", item.productId).put("product_name", item.productName)
                .put("grams", item.grams).put("kcal_per_100", item.kcalPer100)
                .put("ration_component_id", item.rationComponentId ?: JSONObject.NULL)
                .put("protein_per_100", item.proteinPer100 ?: JSONObject.NULL)
                .put("fat_per_100", item.fatPer100 ?: JSONObject.NULL).put("carbs_per_100", item.carbsPer100 ?: JSONObject.NULL))
        }
        payload.put("items", rows)
        dao.enqueue(OutboxEntity(UUID.randomUUID().toString(), meal.ownerScope, "meal", meal.id, action,
            meal.serverRevision.takeIf { it > 0 }, payload.toString(), Instant.now().toString()))
    }
}
