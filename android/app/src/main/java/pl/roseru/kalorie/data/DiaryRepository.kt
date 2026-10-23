package pl.roseru.kalorie.data

import android.content.Context
import androidx.room.withTransaction
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.first
import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.*
import pl.roseru.kalorie.core.sync.*
import java.math.BigDecimal
import java.time.*
import java.util.UUID

class DiaryRepository(private val db: CalorieDatabase, private val context: Context, lease: OwnerLease? = null) {
    val dao = db.dao()
    fun achievements(clock: LocalDayClock) = AchievementRepository(db, clock).observe(owner)
    companion object { const val GUEST = "guest" }
    val owner: String = lease?.storageScope ?: GUEST
    private var boundLease: OwnerLease? = lease
    private val owners = LocalOwnerStore(db)
    private suspend fun <T> ownerTransaction(action: suspend () -> T): T = db.withTransaction {
        val expected = boundLease ?: owners.currentLease().also {
            if (it.storageScope != owner) throw StaleOwnerException()
            boundLease = it
        }
        owners.requireCurrent(expected)
        action()
    }
    private suspend fun canonicalEditor():CanonicalMealEditor {
        val lease=boundLease?:owners.currentLease().also {check(it.storageScope==owner);boundLease=it}
        return CanonicalMealEditor(db,context,lease)
    }
    private suspend fun canonicalWeights():CanonicalWeightEditor {
        val lease=boundLease?:owners.currentLease().also {check(it.storageScope==owner);boundLease=it}
        return CanonicalWeightEditor(db,context,lease)
    }
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
        ownerTransaction {
            dao.seedProducts(entries)
            dao.seedRations(rations)
            dao.seedComponents(components)
            if (owner == GUEST && dao.goalById(owner, "guest-initial-goal") == null)
                dao.seedGoal(GoalEntity("guest-initial-goal", owner, "1970-01-01", 2800.0, 160.0, 90.0, 330.0))
        }
        val schema = CatalogSchema(readCatalog("e2/common.schema.json"), readCatalog("e2/catalog.schema.json"))
        val reader = CatalogPackageReader(schema, CatalogPackageReader.DEMO_ID, "demo")
        // MergeAssets auto-inflates .gz assets; .bin preserves the signed APK's original gzip bytes.
        val packageValue = reader.read(context.assets.open("catalog/e2/manifest.json"), context.assets.open("catalog/e2/base-pl.1.json.gz.bin"))
        CatalogStore(db).import(packageValue)
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

    suspend fun add(productId: String, grams: Double, type: MealType, date: LocalDate, id: String = UUID.randomUUID().toString(), amountText: String? = null) = ownerTransaction {
        require(grams.isFinite() && grams > 0 && grams <= Nutrients.MAX_GRAMS)
        if (dao.meal(id, owner) != null) return@ownerTransaction
        val product = requireNotNull(dao.product(productId, owner))
        val exactAmount = checkedAmount(grams, amountText)
        val zone = ZoneId.systemDefault()
        val time = date.atTime(LocalTime.now()).atZone(zone).toInstant().toString()
        val meal = MealEntity(id, owner, date.toString(), time, zone.id, type.name)
        val item = MealItemEntity(UUID.randomUUID().toString(), id, product.id, product.name, grams,
            product.kcal, product.protein, product.fat, product.carbs,
            snapshotJson = snapshot(product, exactAmount, product.unit))
        if (saveCanonicalManualMeal(meal, item, product, exactAmount)) return@ownerTransaction
        if (saveCanonicalCatalogMeal(meal, listOf(item))) return@ownerTransaction
        dao.insertMeal(meal)
        dao.insertItem(item)
        enqueue(meal, listOf(item), "create")
    }

    /** Called inside ownerTransaction: diary row, exact item and operation commit together. */
    private suspend fun saveCanonicalManualMeal(meal: MealEntity, item: MealItemEntity,
        product: ProductEntity, amount: String): Boolean {
        // Private manual products have no server catalogue identity. Guest/import and catalogue
        // provenance need their own adapters; do not silently recast them as manual data.
        if (product.ownerScope != owner || product.catalogJson != null || db.ownerDao().byScope(owner)?.kind != "account") return false
        val binding = db.bootstrapDao().binding(owner) ?: return false
        if (binding.requiresRecovery) return false
        val schema = CanonicalMealRows.schema(context)
        val operationId = UUID.randomUUID().toString()
        val prepared = try {
            fun number(value: Double?) = value?.let { BigDecimal.valueOf(it) }
            val wire = ManualMealWire.create(product.name, item.id, amount, product.unit,
                ExactNutrition(number(product.kcal), number(product.protein), number(product.fat), number(product.carbs)),
                meal.occurredAt, meal.zoneId, meal.mealType.lowercase(java.util.Locale.ROOT), schema)
            if (wire.json().getString("local_date") != meal.localDate) return false
            wire to MealWire.operation(operationId, meal.id, binding.syncEpoch, null, wire.canonical, schema)
        } catch (_: SyncWireException) {
            // Local inputs can have 12 quantity decimals; wire-v1 allows six. Preserve the
            // existing local format and precision instead of rounding or losing the entry.
            return false
        }
        val (wire, operation) = prepared
        val wireContext = CanonicalMealRows.context(binding)
        val exactItem = CanonicalMealRows.items(meal.id, wire).single()
        dao.insertMeal(CanonicalMealRows.meal(meal.id, owner, wire, wireContext))
        dao.insertItem(item.copy(grams = exactItem.grams, wirePayload = exactItem.wirePayload))
        dao.enqueue(OutboxEntity(operationId, owner, "meal", meal.id, "upsert", null, wire.canonical,
            Instant.now().toString(), "pending", "sync-v1", operation, wireContext))
        return true
    }

    suspend fun edit(id:String,grams:Double) {
        val current=ownerTransaction {requireNotNull(dao.meal(id,owner))}
        require(!current.meal.deleted && current.items.size==1)
        editItem(id,current.items.single().id,grams)
    }

    suspend fun addRation(rationId: String, quantities: Map<String, Double>, type: MealType, date: LocalDate,
        id: String = UUID.randomUUID().toString(), exactQuantities: Map<String, String> = emptyMap()) = ownerTransaction {
        if (dao.meal(id, owner) != null) return@ownerTransaction
        val ration = requireNotNull(dao.ration(rationId))
        require(quantities.isNotEmpty() && quantities.keys.all { key -> ration.components.any { it.id == key } })
        require(exactQuantities.keys.all { it in quantities })
        val zone = ZoneId.systemDefault()
        val meal = MealEntity(id, owner, date.toString(), date.atTime(LocalTime.now()).atZone(zone).toInstant().toString(),
            zone.id, type.name, rationId = ration.ration.id, rationName = ration.ration.name)
        val items = ration.components.sortedBy { it.position }.mapNotNull { component ->
            val grams = quantities[component.id] ?: return@mapNotNull null
            require(grams.isFinite() && grams > 0 && grams <= Nutrients.MAX_GRAMS && grams <= component.packageGrams)
            val amountText = checkedAmount(grams, exactQuantities[component.id])
            require(BigDecimal(amountText) <= BigDecimal(component.quantityText ?: ContractDecimal.canonical(BigDecimal.valueOf(component.packageGrams))))
            val product = requireNotNull(dao.product(component.productId, owner))
            MealItemEntity(UUID.randomUUID().toString(), id, product.id, product.name, grams,
                product.kcal, product.protein, product.fat, product.carbs, component.id,
                snapshot(product, amountText, component.quantityUnit),
                // The legacy demo uses zero-based ordinals; E2 uses positive contract positions.
                rationComponentPosition = (if (ration.ration.catalogJson == null) component.position + 1 else component.position)
                    .also { require(it > 0) })
        }
        if (saveCanonicalCatalogMeal(meal, items, ration.ration)) return@ownerTransaction
        dao.insertMeal(meal)
        items.forEach { dao.insertItem(it) }
        enqueue(meal, items, "create")
    }

    /** Catalogue consumption keeps the local package/source snapshot and queues only the Meal. */
    private suspend fun saveCanonicalCatalogMeal(meal: MealEntity, items: List<MealItemEntity>,
        ration: RationEntity? = null): Boolean {
        if (items.any { it.snapshotJson == null } || (ration != null && ration.catalogJson == null) ||
            db.ownerDao().byScope(owner)?.kind != "account") return false
        val binding = db.bootstrapDao().binding(owner) ?: return false
        if (binding.requiresRecovery) return false
        val schema = CanonicalMealRows.schema(context)
        val operationId = UUID.randomUUID().toString()
        val prepared = try {
            val parts = items.map { item ->
                val snapshot = StrictJson.read(checkNotNull(item.snapshotJson).toByteArray(Charsets.UTF_8))
                val product = snapshot.getJSONObject("product")
                require(item.productId == CatalogStore.recordId("product", product.getString("product_id"), product.getInt("revision")))
                CatalogMealWire.Part(item.id, checkNotNull(item.snapshotJson), item.rationComponentPosition)
            }
            val wire = CatalogMealWire.create(ration?.name ?: items.single().productName, parts, ration?.catalogJson,
                meal.occurredAt, meal.zoneId, meal.mealType.lowercase(java.util.Locale.ROOT), schema)
            if (wire.json().getString("local_date") != meal.localDate) return false
            wire to MealWire.operation(operationId, meal.id, binding.syncEpoch, null, wire.canonical, schema)
        } catch (_: SyncWireException) {
            // Preserve quantities beyond wire-v1 precision in the existing local format.
            return false
        }
        val (wire, operation) = prepared
        val wireContext = CanonicalMealRows.context(binding)
        dao.insertMeal(CanonicalMealRows.meal(meal.id, owner, wire, wireContext)
            .copy(rationId = meal.rationId, rationName = meal.rationName))
        val wireItems = CanonicalMealRows.items(meal.id, wire).associateBy { it.id }
        items.forEach { item -> dao.insertItem(item.copy(wirePayload = wireItems.getValue(item.id).wirePayload)) }
        dao.enqueue(OutboxEntity(operationId, owner, "meal", meal.id, "upsert", null, wire.canonical,
            Instant.now().toString(), "pending", "sync-v1", operation, wireContext))
        return true
    }

    suspend fun editItem(id:String,itemId:String,grams:Double,amountText:String?=null) {
        require(grams.isFinite() && grams>0 && grams<=Nutrients.MAX_GRAMS)
        val text=checkedAmount(grams,amountText)
        if(canonicalEditor().change(id,itemId,text))return
        ownerTransaction {
        require(grams.isFinite() && grams > 0 && grams <= Nutrients.MAX_GRAMS)
        val current = requireNotNull(dao.meal(id, owner))
        require(!current.meal.deleted)
        val meal = current.meal.copy(localRevision = current.meal.localRevision + 1)
        val oldItem = current.items.single { it.id == itemId }
        val item = oldItem.withAmount(checkedAmount(grams, amountText))
        dao.updateMeal(meal)
        dao.updateItem(item)
        enqueue(meal, current.items.map { if (it.id == itemId) item else it }, "update")
        }
    }

    suspend fun removeItem(id:String,itemId:String) {
        if(canonicalEditor().change(id,itemId,remove=true))return
        ownerTransaction {
        val current = requireNotNull(dao.meal(id, owner))
        require(!current.meal.deleted)
        val item = current.items.single { it.id == itemId }
        if (current.items.size == 1) { delete(id); return@ownerTransaction }
        val meal = current.meal.copy(localRevision = current.meal.localRevision + 1)
        dao.updateMeal(meal)
        dao.removeItem(item)
        enqueue(meal, current.items.filterNot { it.id == itemId }, "update")
        }
    }

    suspend fun delete(id:String) {
        if(canonicalEditor().change(id))return
        ownerTransaction {
        val current = requireNotNull(dao.meal(id, owner))
        if (current.meal.deleted) return@ownerTransaction
        val meal = current.meal.copy(deleted = true, localRevision = current.meal.localRevision + 1)
        dao.updateMeal(meal)
        enqueue(meal, current.items, "delete")
        }
    }

    suspend fun setGoal(kcal: Double, protein: Double?, fat: Double?, carbs: Double?, id: String = UUID.randomUUID().toString()) = ownerTransaction {
        require(kcal.isFinite() && kcal > 0 && kcal <= 20_000)
        listOfNotNull(protein, fat, carbs).forEach { require(it.isFinite() && it >= 0 && it <= 5000) }
        val today = LocalDate.now().toString()
        dao.goalById(owner, id)?.let { saved ->
            require(saved.validFrom == today && saved.kcal == kcal && saved.protein == protein && saved.fat == fat && saved.carbs == carbs)
            return@ownerTransaction
        }
        val existing = dao.goalOn(owner, today)
        val sequence = Math.addExact(dao.goalSequence(owner), 1)
        val goal = GoalEntity(id, owner, today, kcal, protein, fat, carbs, sequence, Instant.now().toString(), ZoneId.systemDefault().id,
            if (existing == null) "user_decision" else "history_correction", existing?.id)
        dao.saveGoal(goal)
        val payload = JSONObject().put("id", goal.id).put("valid_from", today).put("kcal", kcal)
            .put("protein", protein ?: JSONObject.NULL).put("fat", fat ?: JSONObject.NULL).put("carbs", carbs ?: JSONObject.NULL)
            .put("decided_at", goal.decidedAt).put("zone_id", goal.zoneId).put("reason", goal.reason)
            .put("correction_of", goal.correctionOf ?: JSONObject.NULL).put("local_timeline_base", sequence - 1)
        dao.enqueue(OutboxEntity(UUID.randomUUID().toString(), owner, "goal", goal.id,
            "create", null, payload.toString(), Instant.now().toString()))
    }

    suspend fun addCustomProduct(draft: CustomProductDraft, grams: Double, type: MealType, date: LocalDate,
        mealId: String = UUID.randomUUID().toString(), productId: String = UUID.randomUUID().toString()) = ownerTransaction {
        if (dao.meal(mealId, owner) != null) return@ownerTransaction
        draft.validate()
        require(grams.isFinite() && grams > 0 && grams <= Nutrients.MAX_GRAMS)
        val product = ProductEntity(productId, draft.name.trim(), normalizeSearch(draft.name), draft.kcal, draft.protein,
            draft.fat, draft.carbs, grams, "Własny produkt", draft.source.trim(), 0, owner)
        dao.insertProduct(product)
        enqueueLocal("product_draft", productId, "create", JSONObject().put("id", productId).put("name", product.name)
            .put("basis", "100 g").put("kcal", product.kcal).put("protein", product.protein ?: JSONObject.NULL)
            .put("fat", product.fat ?: JSONObject.NULL).put("carbs", product.carbs ?: JSONObject.NULL).put("source", product.source))
        add(productId, grams, type, date, mealId)
    }

    suspend fun setProfile(nickname: String, heightCm: Double, activity: ActivityClass, aim: DietAim) = ownerTransaction {
        require(nickname.trim().length in 2..40 && heightCm.isFinite() && heightCm in 80.0..250.0)
        val old = dao.currentProfile(owner)
        val profile = ProfileEntity(old?.id ?: UUID.randomUUID().toString(), owner, nickname.trim(), heightCm,
            activity.name, aim.name, old?.zoneId ?: ZoneId.systemDefault().id, (old?.localRevision ?: 0) + 1)
        dao.saveProfile(profile)
        enqueueLocal("profile", profile.id, if (old == null) "create" else "update", JSONObject().put("id", profile.id)
            .put("nickname", profile.nickname).put("height_cm", heightCm).put("activity_class", activity.name)
            .put("diet_aim", aim.name).put("zone_id", profile.zoneId).put("local_revision", profile.localRevision))
    }

    suspend fun setProfileAndActivityGoal(nickname: String, heightCm: Double, activity: ActivityClass, aim: DietAim) = ownerTransaction {
        val previous = dao.currentProfile(owner)?.activityClass?.let(ActivityClass::valueOf) ?: ActivityClass.GARRISON
        val goal = dao.goal(owner, LocalDate.now().toString()).first()
        val kcal = activityCalorieGoal(goal?.kcal ?: 2800.0, previous, activity)
        setProfile(nickname, heightCm, activity, aim)
        if (previous != activity || goal == null) setGoal(kcal, goal?.protein, goal?.fat, goal?.carbs)
    }

    suspend fun addWeight(kg: Double, date: LocalDate, id: String = UUID.randomUUID().toString()) = ownerTransaction {
        require(kg.isFinite() && kg in 20.0..400.0 && date <= LocalDate.now())
        require(dao.weightOwner(id).let { it == null || it == owner }) { "Weight ID collision" }
        if (dao.weight(id, owner) != null) return@ownerTransaction
        val zone = ZoneId.systemDefault()
        val point = WeightEntity(id, owner, date.toString(), date.atTime(LocalTime.now()).atZone(zone).toInstant().toString(), zone.id, kg)
        if(canonicalWeights().create(point)) return@ownerTransaction
        dao.saveWeight(point)
        enqueueWeight(point, "create")
    }

    suspend fun editWeight(id: String, kg: Double) {
        require(kg.isFinite() && kg in 20.0..400.0)
        if(canonicalWeights().change(id, kg)) return
        ownerTransaction {
            val old = requireNotNull(dao.weight(id, owner))
            require(!old.deleted)
            val point = old.copy(kg = kg, localRevision = old.localRevision + 1)
            dao.saveWeight(point)
            enqueueWeight(point, "update")
        }
    }

    suspend fun deleteWeight(id: String) {
        if(canonicalWeights().change(id)) return
        ownerTransaction {
            val old = requireNotNull(dao.weight(id, owner))
            if (old.deleted) return@ownerTransaction
            val point = old.copy(deleted = true, localRevision = old.localRevision + 1)
            dao.saveWeight(point)
            enqueueWeight(point, "delete")
        }
    }

    private suspend fun enqueueWeight(point: WeightEntity, action: String) = enqueueLocal("weight", point.id, action,
        JSONObject().put("id", point.id).put("kg", point.kg).put("local_date", point.localDate).put("occurred_at", point.occurredAt)
            .put("zone_id", point.zoneId).put("deleted", point.deleted).put("local_revision", point.localRevision))

    suspend fun setDayComplete(date: LocalDate, declared: Boolean) = ownerTransaction {
        require(date <= LocalDate.now())
        if (declared) {
            val meals = dao.day(owner, date.toString()).first()
            val items = meals.flatMap { it.items }
            require(completeDiary(true, items.size, items.map { it.consumed() }.total()))
        }
        val old = dao.currentDiaryDay(owner, date.toString())
        if (old?.declaredComplete == declared || (old == null && !declared)) return@ownerTransaction
        val status = DiaryDayEntity(old?.id ?: UUID.randomUUID().toString(), owner, date.toString(), declared, (old?.localRevision ?: 0) + 1)
        dao.saveDiaryDay(status)
        enqueueLocal("diary_day", status.id, if (old == null) "create" else "update", JSONObject().put("id", status.id)
            .put("local_date", status.localDate).put("declared_complete", declared).put("local_revision", status.localRevision))
    }

    private suspend fun enqueueLocal(type: String, id: String, action: String, payload: JSONObject) {
        dao.enqueue(OutboxEntity(UUID.randomUUID().toString(), owner, type, id, action, null, payload.toString(), Instant.now().toString()))
    }

    private fun checkedAmount(projection: Double, text: String?): String {
        val amount = ContractDecimal.userQuantity(text ?: ContractDecimal.canonical(BigDecimal.valueOf(projection)), 12)
            ?: throw NutritionError("quantity_range")
        require(amount.toDouble() == projection) { "Quantity projection mismatch" }
        return ContractDecimal.canonical(amount)
    }

    private suspend fun snapshot(product: ProductEntity, amountText: String, unit: String): String? {
        val json = product.catalogJson ?: return null
        val amount = ContractDecimal.userQuantity(amountText, 12) ?: throw NutritionError("quantity_range")
        product.portion(ContractDecimal.canonical(amount), unit)
        val original = JSONObject(json)
        val sources = JSONArray()
        val sourceIds = mutableSetOf(original.getString("source_id"))
        original.optJSONObject("density_g_per_ml")?.let { sourceIds += it.getString("source_id") }
        sourceIds.sorted().forEach { id ->
            val source = requireNotNull(db.catalogDao().record(CatalogStore.recordId("source", id, 0)))
            sources.put(JSONObject(source.payloadJson))
        }
        return StrictJson.canonical(JSONObject().put("formula_version", NutritionV1.FORMULA).put("product", original)
            .put("quantity", JSONObject().put("amount", ContractDecimal.canonical(amount)).put("unit", unit)).put("sources", sources))
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
                .put("ration_component_position", item.rationComponentPosition ?: JSONObject.NULL)
                .put("exact_snapshot", item.snapshotJson?.let(::JSONObject) ?: JSONObject.NULL)
                .put("protein_per_100", item.proteinPer100 ?: JSONObject.NULL)
                .put("fat_per_100", item.fatPer100 ?: JSONObject.NULL).put("carbs_per_100", item.carbsPer100 ?: JSONObject.NULL))
        }
        payload.put("items", rows)
        dao.enqueue(OutboxEntity(UUID.randomUUID().toString(), meal.ownerScope, "meal", meal.id, action,
            meal.serverRevision.takeIf { it > 0 }, payload.toString(), Instant.now().toString()))
    }
}
