package pl.roseru.kalorie.core.sync

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.BootstrapProtocol
import pl.roseru.kalorie.core.ContractDecimal
import pl.roseru.kalorie.core.NutritionV1
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.time.Instant
import java.util.Locale

/** Immutable extraction. Outbox originals are evidence, never rewritten as operations. */
class LegacyImportSource(val entityType: String, val localId: String, val row: String,
    items: List<String> = emptyList(), originalOutboxes: List<String> = emptyList()) {
    val items = items.toList()
    val originalOutboxes = originalOutboxes.toList()
    override fun toString() = "LegacyImportSource(redacted)"
}
class LegacyImportIds(entities: Map<String, String>, items: Map<String, String> = emptyMap()) {
    val entities = entities.toMap()
    val items = items.toMap()
    override fun toString() = "LegacyImportIds(redacted)"
}
data class LegacyImportMetadata(val confirmed: Boolean = false, val zone: String? = null,
    val goalDecidedAt: String? = null, val goalReason: String? = null, val goalAim: String? = null,
    val goalActivity: String? = null, val timelineBaseRevision: Int? = null,
    val correctionOfLocalId: String? = null, val correctedPayload: String? = null,
    val provenCatalogProducts: Set<String> = emptySet(), val provenRationJson: String? = null) {
    override fun toString() = "LegacyImportMetadata(redacted)"
}
data class LegacyImportDependency(val entityType: String, val sourceLocalId: String, val targetWireId: String)
sealed interface LegacyImportConversion {
    data class Ready(val entityType: String, val sourceLocalId: String, val targetWireId: String,
        val payload: String?, val deleted: Boolean, val dependencies: List<LegacyImportDependency>) : LegacyImportConversion {
        override fun toString() = "LegacyImportReady(redacted)"
    }
    data class NeedsDecision(val code: String, val fieldPaths: List<String>) : LegacyImportConversion
}

/** Pure conversion only: no clock, UUID allocation, account assignment, database, ACK or recovery. */
object LegacyImportWire {
    private class Review(val code: String, val paths: List<String>) : IllegalArgumentException()
    private fun review(code: String, vararg paths: String): Nothing = throw Review(code, paths.toList())

    fun convert(source: LegacyImportSource, ids: LegacyImportIds, metadata: LegacyImportMetadata,
        schema: SyncWireSchema): LegacyImportConversion = try {
        require(source.entityType in PrivateDomainsWire.types + setOf("meal", "weight"))
        val row = legacy(source.row)
        require(text(row, "id") == source.localId)
        val target = entityId(ids, source.entityType, source.localId)
        source.originalOutboxes.forEachIndexed { index, original ->
            val outbox = legacy(original)
            if (optional(outbox, "wireFormat", "wire_format") == "sync-v1" || flag(outbox, "attempted", false))
                review("existing_wire_review", "originalOutboxes[$index]")
        }
        if (flag(row, "deleted", false)) review("tombstone_review", "row.deleted")
        val dependencies = mutableListOf<LegacyImportDependency>()
        val corrected = metadata.correctedPayload
        val value = if (corrected != null) {
            if (!metadata.confirmed) review("confirmation_required", "correctedPayload")
            StrictJson.read(corrected.toByteArray(Charsets.UTF_8))
        } else when (source.entityType) {
            "profile" -> profile(row, metadata)
            "goal" -> goal(source, row, ids, metadata, dependencies)
            "diary_day" -> day(row, metadata)
            "weight" -> weight(row, metadata)
            "product_draft" -> product(row)
            "meal" -> meal(source, row, ids, metadata, dependencies)
            else -> error("Unsupported domain")
        }
        if (corrected != null) {
            if (source.entityType == "meal") {
                val rows = value.getJSONArray("items")
                val seen = mutableSetOf<String>()
                for (index in 0 until rows.length()) {
                    val id = rows.getJSONObject(index).getString("item_id")
                    if (!BootstrapProtocol.uuid.matches(id) || ids.items.values.count { it == id } != 1 || !seen.add(id))
                        review("identity_mapping_required", "correctedPayload.items[$index].item_id")
                }
            }
            val reference = when (source.entityType) {
                "meal" -> optional(value, "goal_id")
                "goal" -> optional(value, "correction_of")
                else -> null
            }
            if (reference != null) {
                val local = ids.entities.entries.singleOrNull { it.key.startsWith("goal:") && it.value == reference }
                    ?.key?.removePrefix("goal:") ?: review("identity_mapping_required", "correctedPayload.goal_reference")
                dependency(ids, "goal", local, dependencies)
            }
        }
        val payload = StrictJson.canonical(value)
        val validated = when (source.entityType) {
            "meal" -> MealWire.read(payload, schema).canonical
            "weight" -> {
                require(BigDecimal(value.getString("weight_kg")) <= BigDecimal(1000))
                WeightWire.read(payload, schema).canonical
            }
            else -> PrivateDomainsWire.read(source.entityType, payload, schema)
        }
        LegacyImportConversion.Ready(source.entityType, source.localId, target, validated, false, dependencies.toList())
    } catch (error: Review) {
        LegacyImportConversion.NeedsDecision(error.code, error.paths)
    } catch (_: Exception) {
        LegacyImportConversion.NeedsDecision("invalid_legacy_data", listOf("row"))
    }

    private fun entityId(ids: LegacyImportIds, type: String, local: String): String {
        val mapped = ids.entities["$type:$local"] ?: review("identity_mapping_required", "$type:$local")
        if (!BootstrapProtocol.uuid.matches(mapped)) review("identity_mapping_required", "$type:$local")
        if (ids.entities.count { (key, value) -> key.startsWith("$type:") && value == mapped } != 1)
            review("identity_collision", "$type:$local")
        return mapped
    }
    private fun itemId(ids: LegacyImportIds, local: String): String {
        val mapped = ids.items[local] ?: review("identity_mapping_required", "items:$local")
        if (!BootstrapProtocol.uuid.matches(mapped) || ids.items.values.count { it == mapped } != 1)
            review("identity_collision", "items:$local")
        return mapped
    }
    private fun dependency(ids: LegacyImportIds, type: String, local: String,
        dependencies: MutableList<LegacyImportDependency>): String = entityId(ids, type, local).also {
        dependencies += LegacyImportDependency(type, local, it)
    }
    private fun optional(row: JSONObject, vararg keys: String): String? {
        val key = keys.firstOrNull { row.has(it) } ?: return null
        if (row.isNull(key)) return null
        val value = row.get(key)
        require(value is String)
        return value
    }
    private fun text(row: JSONObject, vararg keys: String): String = optional(row, *keys)
        ?: review("missing_metadata", keys.first())
    private fun flag(row: JSONObject, key: String, fallback: Boolean? = null): Boolean {
        if (!row.has(key)) return fallback ?: review("missing_metadata", key)
        return when (val value = row.get(key)) {
            true, "1" -> true
            false, "0" -> false
            else -> { require(value is Boolean); value }
        }
    }
    private fun number(value: Any?, path: String): Any {
        if (value == null || value === JSONObject.NULL) return JSONObject.NULL
        if (value !is String) review("decimal_review", path)
        val decimal = try { BigDecimal(value) } catch (_: Exception) { review("decimal_review", path) }
        if (decimal.signum() < 0 || decimal > BigDecimal("999999.999999")) review("decimal_review", path)
        if (decimal.stripTrailingZeros().scale() > 6) review("precision_review", path)
        return ContractDecimal.canonical(decimal)
    }
    private fun decimal(row: JSONObject, path: String, vararg keys: String): Any {
        val key = keys.firstOrNull { row.has(it) } ?: review("missing_metadata", path)
        return number(row.get(key), path)
    }
    private fun zone(row: JSONObject, metadata: LegacyImportMetadata): String =
        optional(row, "zoneId", "zone_id", "time_zone") ?: confirmed(metadata, metadata.zone, "time_zone")
    private fun confirmed(metadata: LegacyImportMetadata, value: String?, path: String): String =
        value?.takeIf { metadata.confirmed } ?: review("missing_confirmed_metadata", path)
    private fun timestamp(value: String, path: String): String {
        val instant = Instant.parse(value)
        if (instant.nano % 1000 != 0) review("timestamp_precision_review", path)
        return instant.toString()
    }
    private fun activity(value: String): String = when (value) {
        "GARRISON", "STATIONARY", "stationary" -> "stationary"
        "LINE", "line" -> "line"
        "COMMANDO", "commando" -> "commando"
        else -> review("activity_review", "activity_class")
    }
    private fun aim(value: String): String = when (value) {
        "REDUCE", "reduce" -> "reduce"
        "MAINTAIN", "maintain" -> "maintain"
        "SURPLUS", "gain" -> "gain"
        else -> review("aim_review", "goal_type")
    }
    private fun profile(row: JSONObject, metadata: LegacyImportMetadata) = JSONObject()
        .put("pseudonym", text(row, "nickname", "pseudonym"))
        .put("height_cm", decimal(row, "height_cm", "heightCm", "height_cm"))
        .put("activity_class", activity(text(row, "activityClass", "activity_class")))
        .put("time_zone", zone(row, metadata))

    private fun goal(source: LegacyImportSource, row: JSONObject, ids: LegacyImportIds, metadata: LegacyImportMetadata,
        dependencies: MutableList<LegacyImportDependency>): JSONObject {
        val base = metadata.timelineBaseRevision?.takeIf { metadata.confirmed && it >= 0 }
            ?: review("timeline_review", "timeline_base_revision")
        val decided = optional(row, "decidedAt", "decided_at")
            ?: confirmed(metadata, metadata.goalDecidedAt, "decided_at")
        val reason = optional(row, "reason")?.takeUnless { it == "legacy" }
            ?: confirmed(metadata, metadata.goalReason, "reason")
        val correction = optional(row, "correctionOf", "correction_of")
            ?: metadata.correctionOfLocalId?.takeIf { metadata.confirmed }
        val evidence = goalEvidence(source, row)
        val goalAim = goalIntent(evidence, "goal_type", metadata.goalAim, metadata, ::aim)
        val goalActivity = goalIntent(evidence, "activity_class", metadata.goalActivity, metadata, ::activity)
        return JSONObject().put("effective_from", text(row, "validFrom", "valid_from", "effective_from"))
            .put("decided_at", timestamp(decided, "decided_at")).put("time_zone", zone(row, metadata))
            .put("goal_type", goalAim)
            .put("energy_kcal", decimal(row, "energy_kcal", "kcal", "energy_kcal"))
            .put("protein_g", decimal(row, "protein_g", "protein", "protein_g"))
            .put("fat_g", decimal(row, "fat_g", "fat", "fat_g"))
            .put("carbs_g", decimal(row, "carbs_g", "carbs", "carbs_g"))
            .put("activity_class", goalActivity)
            .put("estimate", JSONObject.NULL).put("timeline_base_revision", base).put("reason", reason)
            .put("correction_of", correction?.let { dependency(ids, "goal", it, dependencies) } ?: JSONObject.NULL)
    }
    /** GoalEntity has no aim: only this goal's immutable original intent is evidence. */
    private fun goalEvidence(source: LegacyImportSource, row: JSONObject): List<JSONObject> = buildList {
        add(row)
        source.originalOutboxes.forEach { original ->
            val outbox = legacy(original)
            if (optional(outbox, "entityType", "entity_type") != "goal" ||
                optional(outbox, "entityId", "entity_id") != source.localId) return@forEach
            val payload = when (val raw = outbox.opt("payload")) {
                is String -> legacy(raw)
                is JSONObject -> raw
                else -> return@forEach
            }
            if (optional(payload, "id") == source.localId) add(payload)
        }
    }
    private fun goalIntent(evidence: List<JSONObject>, field: String, supplied: String?,
        metadata: LegacyImportMetadata, normalize: (String) -> String): String {
        // A consciously supplied value may resolve conflicting historical evidence.
        if (metadata.confirmed && supplied != null) return normalize(supplied)
        val values = evidence.mapNotNull { row ->
            if (field == "activity_class") optional(row, "activityClass", "activity_class")
            else optional(row, field)
        }.map(normalize).toSet()
        if (values.size > 1) review("goal_intent_review", "originalOutboxes.$field", "row.$field")
        return values.singleOrNull() ?: review("missing_confirmed_metadata", field)
    }
    private fun day(row: JSONObject, metadata: LegacyImportMetadata) = JSONObject()
        .put("local_date", text(row, "localDate", "local_date")).put("time_zone", zone(row, metadata))
        .put("declared_complete", flag(row, if (row.has("declaredComplete")) "declaredComplete" else "declared_complete"))
    private fun weight(row: JSONObject, metadata: LegacyImportMetadata) = JSONObject()
        .put("weight_kg", decimal(row, "weight_kg", "kg", "weight_kg"))
        .put("occurred_at", timestamp(text(row, "occurredAt", "occurred_at"), "occurred_at"))
        .put("time_zone", zone(row, metadata)).put("local_date", text(row, "localDate", "local_date"))

    private val nutritionFields = listOf("energy_kcal", "protein_g", "fat_g", "carbs_g")
    private fun nutrition(row: JSONObject, keys: List<String>, path: String) = JSONObject().also { result ->
        nutritionFields.zip(keys).forEach { (wire, local) -> result.put(wire, decimal(row, "$path.$local", local)) }
    }
    private fun product(row: JSONObject): JSONObject {
        optional(row, "wirePayload")?.let { return StrictJson.read(it.toByteArray(Charsets.UTF_8)) }
        return JSONObject().put("name", text(row, "name")).put("brand", JSONObject.NULL).put("variant", JSONObject.NULL)
            .put("basis_unit", optional(row, "basisUnit", "unit") ?: "g")
            .put("nutrition_per_100", nutrition(row, listOf("kcal", "protein", "fat", "carbs"), "row"))
            .put("package_quantity", JSONObject.NULL).put("density_g_per_ml", JSONObject.NULL)
            .put("density_source", JSONObject.NULL).put("source_description", text(row, "source"))
    }

    private fun snapshot(item: JSONObject): JSONObject? = when {
        item.has("snapshotJson") && !item.isNull("snapshotJson") -> legacy(item.getString("snapshotJson"))
        item.has("exact_snapshot") && !item.isNull("exact_snapshot") -> item.getJSONObject("exact_snapshot")
        else -> null
    }
    private fun meal(source: LegacyImportSource, row: JSONObject, ids: LegacyImportIds,
        metadata: LegacyImportMetadata, dependencies: MutableList<LegacyImportDependency>): JSONObject {
        val items = if (source.items.isNotEmpty()) source.items.map(::legacy) else {
            val array = row.optJSONArray("items") ?: review("missing_metadata", "items")
            (0 until array.length()).map { array.getJSONObject(it) }
        }
        val ration = metadata.provenRationJson?.let {
            if (!metadata.confirmed) review("confirmation_required", "provenRationJson")
            StrictJson.read(it.toByteArray(Charsets.UTF_8))
        }
        val positions = mutableSetOf<Int>()
        val wireItems = items.mapIndexed { index, item ->
            val path = "items[$index]"; val snap = snapshot(item)
            val privateProduct = snap?.optJSONObject("private_product")
            val catalog = snap?.optJSONObject("product")
            if (snap != null && snap.getString("formula_version") != NutritionV1.FORMULA)
                review("snapshot_review", "$path.snapshotJson.formula_version")
            val quantity = snap?.optJSONObject("quantity")
            val amount = if (quantity != null) decimal(quantity, "$path.quantity.amount", "amount")
                else if (item.has("quantityText") && !item.isNull("quantityText")) decimal(item, "$path.quantity.amount", "quantityText")
                else decimal(item, "$path.quantity.amount", "grams")
            val unit = quantity?.getString("unit") ?: optional(item, "quantityUnit") ?: "g"
            val product = privateProduct ?: catalog
            val nutrients = product?.getJSONObject("nutrition_per_100")?.let {
                nutrition(it, nutritionFields, "$path.nutrition_per_100")
            } ?: nutrition(item, listOf("kcalPer100", "proteinPer100", "fatPer100", "carbsPer100"), path)
            val proof = catalog?.let { "${it.getString("product_id")}:${it.getString("revision")}" }
            val proven = proof != null && metadata.confirmed && proof in metadata.provenCatalogProducts
            val density = if (catalog != null) catalog.optJSONObject("density_g_per_ml")?.let { decimal(it, "$path.density", "amount") }
                else privateProduct?.let { decimal(it, "$path.density", "density_g_per_ml") }
            val densitySource = if (catalog != null) catalog.optJSONObject("density_g_per_ml")?.getString("source_id")
                else privateProduct?.let { optional(it, "density_source") }
            if (densitySource != null && catalog != null) {
                val sources = snap!!.optJSONArray("sources") ?: review("density_source_review", "$path.sources")
                require((0 until sources.length()).any { sources.getJSONObject(it).getString("source_id") == densitySource })
            }
            val position = if (ration == null) JSONObject.NULL else {
                if (!proven) review("ration_proof_review", path)
                val raw = optional(item, "rationComponentPosition", "ration_component_position")
                    ?: review("ration_proof_review", "$path.rationComponentPosition")
                val position = raw.toInt()
                require(positions.add(position))
                val components = ration.getJSONArray("components")
                val component = (0 until components.length()).map { components.getJSONObject(it) }
                    .single { it.getInt("position") == position }
                val reference = component.getJSONObject("product")
                require(reference.getString("product_id") == catalog!!.getString("product_id") &&
                    reference.getInt("revision") == catalog.getString("revision").toInt())
                val pack = component.getJSONObject("quantity")
                require(pack.getString("unit") == unit && BigDecimal(amount.toString()) <= BigDecimal(pack.getString("amount")))
                position
            }
            JSONObject().put("item_id", itemId(ids, text(item, "id")))
                .put("name", product?.getString("name") ?: text(item, "productName", "product_name"))
                .put("product", if (proven) JSONObject().put("product_id", catalog!!.getString("product_id"))
                    .put("revision", catalog.getString("revision").toInt()) else JSONObject.NULL)
                .put("quantity", JSONObject().put("amount", amount).put("unit", unit))
                .put("basis_unit", product?.getString("basis_unit") ?: "g").put("nutrition_per_100", nutrients)
                .put("density_g_per_ml", density ?: JSONObject.NULL).put("density_source", densitySource ?: JSONObject.NULL)
                .put("nutrition_origin", if (proven) "catalog_snapshot" else "manual")
                .put("formula_version", NutritionV1.FORMULA).put("ration_component_position", position)
        }
        val goal = optional(row, "goalId", "goal_id")
        return JSONObject().put("title", optional(row, "rationName", "ration_name")
            ?: wireItems.firstOrNull()?.getString("name") ?: review("missing_metadata", "items"))
            .put("occurred_at", timestamp(text(row, "occurredAt", "occurred_at"), "occurred_at"))
            .put("time_zone", zone(row, metadata)).put("local_date", text(row, "localDate", "local_date"))
            .put("meal_type", text(row, "mealType", "meal_type").lowercase(Locale.ROOT))
            .put("goal_id", goal?.let { dependency(ids, "goal", it, dependencies) } ?: JSONObject.NULL)
            .put("ration", ration?.let { JSONObject().put("ration_id", it.getString("ration_id"))
                .put("revision", it.getInt("revision")).put("name", it.getString("name")) } ?: JSONObject.NULL)
            .put("items", JSONArray(wireItems))
    }

    /** Quote numeric lexemes before StrictJson preflight; no Double parse or duplicate-key ambiguity. */
    private fun legacy(raw: String): JSONObject {
        require(raw.toByteArray(Charsets.UTF_8).size <= 4 * 1_048_576)
        val normalized = StringBuilder(); var index = 0; var inString = false
        while (index < raw.length) {
            val char = raw[index]
            if (inString) {
                normalized.append(char); index++
                if (char == '\\') { require(index < raw.length); normalized.append(raw[index++]) }
                else if (char == '"') inString = false
            } else if (char == '"') { inString = true; normalized.append(char); index++ }
            else if (char == '-' || char in '0'..'9') {
                val match = Regex("-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][+-]?[0-9]+)?").find(raw, index)
                require(match != null && match.range.first == index)
                val end = match.range.last + 1
                require(end == raw.length || raw[end] in " \t\r\n,}]")
                normalized.append(JSONObject.quote(match.value)); index = end
            } else { normalized.append(char); index++ }
        }
        return StrictJson.read(normalized.toString().toByteArray(Charsets.UTF_8))
    }
}
