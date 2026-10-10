package pl.roseru.kalorie.data

import androidx.room.withTransaction
import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.*
import java.util.UUID

class CatalogStore(private val db: CalorieDatabase,
    private val beforeStageCommit: () -> Unit = {}, private val beforeActivateCommit: () -> Unit = {}) {
    private val catalog = db.catalogDao()
    companion object {
        fun recordId(type: String, id: String, revision: Int) = "$type/$id@$revision"
    }
    suspend fun stage(value: ValidatedCatalog): String = db.withTransaction {
        if (catalog.otherKind(value.packageId, value.kind) != null) throw CatalogError("identity_mismatch")
        val previous = catalog.generation(value.packageId, value.release)
        if (previous != null) {
            if (previous.kind != value.kind || previous.manifestJson != value.manifestJson || previous.payloadJson != value.payloadJson)
                throw CatalogError("release_conflict")
            check(previous.complete)
            return@withTransaction previous.id
        }
        val generation = CatalogGenerationEntity(UUID.randomUUID().toString(), value.packageId, value.kind,
            value.release, value.sha256, value.manifestJson, value.payloadJson, false)
        catalog.insertGeneration(generation)
        val payload = value.payload()
        suspend fun insert(type: String, id: String, revision: Int, row: JSONObject): Pair<String, Boolean> {
            val key = recordId(type, id, revision)
            val json = StrictJson.canonical(row)
            val existing = catalog.record(key)
            if (existing != null && (existing.payloadJson != json || existing.entityType != type)) throw CatalogError("version_conflict")
            if (existing == null) catalog.insertRecord(CatalogRecordEntity(key, type, json))
            catalog.insertMember(CatalogMemberEntity(generation.id, key))
            return key to (existing == null)
        }
        val sources = payload.getJSONArray("sources").objects().associateBy { it.getString("source_id") }
        sources.values.forEach { insert("source", it.getString("source_id"), 0, it) }
        payload.getJSONArray("products").objects().forEach { product ->
            val (key, new) = insert("product", product.getString("product_id"), product.getInt("revision"), product)
            if (new) {
                val nutrition = product.getJSONObject("nutrition_per_100")
                fun number(field: String): Double? = if (nutrition.isNull(field)) null else ContractDecimal.read(nutrition.getString(field)).toDouble()
                // REAL fields are legacy UI projections; catalogJson is the exact authority.
                val row = ProductEntity(key, product.getString("name"),
                    normalizeSearch(product.getString("name") + " " + product.getJSONArray("aliases").toString()),
                    number("energy_kcal") ?: 0.0, number("protein_g"), number("fat_g"), number("carbs_g"),
                    100.0, if (value.kind == "demo") "Katalog E2 · DEMO" else "Katalog oficjalny", sources.getValue(product.getString("source_id")).getString("document_id"),
                    value.release, catalogJson = StrictJson.canonical(product))
                db.dao().insertProduct(row)
            }
        }
        payload.getJSONArray("rations").objects().forEach { ration ->
            val (key, new) = insert("ration", ration.getString("ration_id"), ration.getInt("revision"), ration)
            if (new) {
                val excluded = ration.getJSONArray("excluded_items").objects()
                val description = buildString {
                    append(if (ration.getBoolean("complete")) "Kompletna racja." else "Niepełna racja — nie wszystkie pozycje mają dane.")
                    append(if (ration.getString("status") == "verified") " Źródła zweryfikowane." else " Dane niezweryfikowane — DEMO.")
                    if (excluded.isNotEmpty()) append(" Poza obliczeniami: " + excluded.joinToString(", ") { it.getString("name") } + ".")
                }
                db.dao().seedRations(listOf(RationEntity(key, ration.getString("name"), description,
                    sources.getValue(ration.getString("source_id")).getString("document_id"), value.release, StrictJson.canonical(ration))))
                db.dao().seedComponents(ration.getJSONArray("components").objects().map { part ->
                    val reference = part.getJSONObject("product"); val quantity = part.getJSONObject("quantity")
                    RationComponentEntity("$key/${part.getInt("position")}", key,
                        recordId("product", reference.getString("product_id"), reference.getInt("revision")),
                        ContractDecimal.read(quantity.getString("amount")).toDouble(), part.getInt("position"),
                        quantity.getString("amount"), quantity.getString("unit"))
                })
            }
        }
        catalog.updateGeneration(generation.copy(complete = true))
        beforeStageCommit()
        generation.id
    }
    suspend fun activate(generationId: String): Boolean = db.withTransaction {
        val candidate = catalog.generationById(generationId) ?: throw CatalogError("unknown_generation")
        if (!candidate.complete) throw CatalogError("unknown_generation")
        val current = catalog.active(candidate.packageId)
        if (current != null && current.kind != candidate.kind) throw CatalogError("identity_mismatch")
        if (current != null && current.release >= candidate.release) return@withTransaction false
        catalog.setActive(CatalogActiveEntity(candidate.packageId, candidate.kind, candidate.release, candidate.id))
        beforeActivateCommit()
        true
    }
    suspend fun import(value: ValidatedCatalog): Boolean = activate(stage(value))
}
