package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.sync.*

class LegacyImportWireTest {
    private val schema = SyncWireSchema(SyncWireSchema.FILES.associateWith { name ->
        javaClass.getResourceAsStream("/sync/$name")!!.use { it.readBytes() }
    })
    private val target = "11111111-1111-4111-8111-111111111111"
    private val item = "22222222-2222-4222-8222-222222222222"
    private val other = "33333333-3333-4333-8333-333333333333"
    private val productId = "44444444-4444-4444-8444-444444444444"
    private fun ids(type: String, local: String = "old") = LegacyImportIds(mapOf("$type:$local" to target), mapOf("old-item" to item))
    private fun convert(type: String, row: String, metadata: LegacyImportMetadata = LegacyImportMetadata(),
        items: List<String> = emptyList(), mapping: LegacyImportIds = ids(type), outbox: List<String> = emptyList()) =
        LegacyImportWire.convert(LegacyImportSource(type, "old", row, items, outbox), mapping, metadata, schema)
    private fun ready(result: LegacyImportConversion) = (result as LegacyImportConversion.Ready).also {
        assertFalse(it.deleted); assertEquals(target, it.targetWireId); assertEquals("old", it.sourceLocalId)
    }
    private fun decision(result: LegacyImportConversion, code: String) {
        assertTrue(result is LegacyImportConversion.NeedsDecision)
        assertEquals(code, (result as LegacyImportConversion.NeedsDecision).code)
        assertTrue(result.fieldPaths.isNotEmpty())
    }
    private val meal = """{"id":"old","localDate":"2020-01-02","occurredAt":"2020-01-02T10:00:00Z","zoneId":"Europe/Warsaw","mealType":"LUNCH","deleted":0,"rationId":"demo-old","rationName":"Historical ration"}"""
    private val legacyItem = """{"id":"old-item","productId":"basic-banana","productName":"Historical banana","grams":120.000000,"kcalPer100":89.0,"proteinPer100":null,"fatPer100":0.0,"carbsPer100":22.8,"rationComponentPosition":null,"snapshotJson":null}"""
    private val goal = """{"id":"old","validFrom":"1970-01-01","kcal":2500.125,"protein":null,"fat":0.0,"carbs":200.5,"localSequence":0,"decidedAt":null,"zoneId":null,"reason":"legacy","correctionOf":null}"""
    private fun audit() = LegacyImportMetadata(confirmed = true, zone = "Europe/Warsaw",
        goalDecidedAt = "1970-01-01T10:00:00Z", goalReason = "user_decision", goalAim = "MAINTAIN",
        goalActivity = "GARRISON", timelineBaseRevision = 0)

    @Test fun profileMapsActualGarrisonEnumAndPreservesNullHeightWithoutInferringAim() {
        val result = ready(convert("profile", """{"id":"old","nickname":"Guest","heightCm":null,"activityClass":"GARRISON","dietAim":"REDUCE","zoneId":"Europe/Warsaw"}"""))
        val wire = JSONObject(result.payload!!)
        assertEquals("stationary", wire.getString("activity_class")); assertTrue(wire.isNull("height_cm"))
        assertEquals("Guest", wire.getString("pseudonym")); assertFalse(wire.has("goal_type"))
    }

    @Test fun rawLegacyDecimalsAreReadWithoutDoubleAndCanonicalizedLosslessly() {
        val row = """{"id":"old","kg":80.000001000000,"occurredAt":"2020-01-02T10:00:00Z","zoneId":"Europe/Warsaw","localDate":"2020-01-02","deleted":false}"""
        assertEquals("80.000001", JSONObject(ready(convert("weight", row)).payload!!).getString("weight_kg"))
        decision(convert("weight", row.replace("80.000001000000", "80.000001000001")), "precision_review")
        decision(convert("weight", row.replace("80.000001000000", "NaN")), "invalid_legacy_data")
        decision(convert("weight", row.replace("80.000001000000", "-1")), "decimal_review")
        decision(convert("weight", row.replace("80.000001000000", "true")), "decimal_review")
        decision(convert("weight", row.replace("80.000001000000", "1e-99999999")), "precision_review")
        decision(convert("weight", row.replace("80.000001000000", "1000.000001")), "invalid_legacy_data")
    }

    @Test fun actualOldGoalRequiresExplicitAuditAndKeepsHistoricalDayAndAllNutrients() {
        decision(convert("goal", goal), "timeline_review")
        decision(convert("goal", goal, audit().copy(confirmed = false)), "timeline_review")
        decision(convert("goal", goal, audit().copy(goalDecidedAt = null)), "missing_confirmed_metadata")
        decision(convert("goal", goal, audit().copy(goalAim = null)), "missing_confirmed_metadata")
        val wire = JSONObject(ready(convert("goal", goal, audit())).payload!!)
        assertEquals("1970-01-01", wire.getString("effective_from")); assertEquals(0, wire.getInt("timeline_base_revision"))
        assertEquals("2500.125", wire.getString("energy_kcal")); assertTrue(wire.isNull("protein_g"))
        assertEquals("0", wire.getString("fat_g")); assertEquals("200.5", wire.getString("carbs_g"))
        assertEquals("stationary", wire.getString("activity_class")); assertEquals("maintain", wire.getString("goal_type"))
        assertTrue(wire.isNull("estimate")); assertTrue(wire.isNull("correction_of"))
    }

    @Test fun goalCorrectionUsesExternalTargetAndRetainsDependencyRatherThanLocalSequence() {
        val mapping = LegacyImportIds(mapOf("goal:old" to target, "goal:prior" to other))
        val metadata = audit().copy(goalReason = "history_correction", correctionOfLocalId = "prior", timelineBaseRevision = 7)
        val result = ready(convert("goal", goal, metadata, mapping = mapping))
        val wire = JSONObject(result.payload!!)
        assertEquals(7, wire.getInt("timeline_base_revision")); assertEquals(other, wire.getString("correction_of"))
        assertEquals(listOf(LegacyImportDependency("goal", "prior", other)), result.dependencies)
    }

    @Test fun dayNeedsConfirmedHistoricalZoneAndDoesNotInferDeviceZone() {
        val row = """{"id":"old","localDate":"2019-01-01","declaredComplete":1,"localRevision":7}"""
        decision(convert("diary_day", row), "missing_confirmed_metadata")
        decision(convert("diary_day", row, LegacyImportMetadata(zone = "Europe/Warsaw")), "missing_confirmed_metadata")
        val wire = JSONObject(ready(convert("diary_day", row, LegacyImportMetadata(true, zone = "Europe/Warsaw"))).payload!!)
        assertTrue(wire.getBoolean("declared_complete")); assertEquals("2019-01-01", wire.getString("local_date"))
    }

    @Test fun oldProductPreservesActualSourceMissingMacrosAndPrivateIdentity() {
        val row = """{"id":"old","name":"Private soup","kcal":50.125,"protein":null,"fat":0,"carbs":12.5,"source":"Original recipe","defaultGrams":250,"catalogJson":null,"wirePayload":null}"""
        val wire = JSONObject(ready(convert("product_draft", row)).payload!!)
        assertEquals("Original recipe", wire.getString("source_description"))
        assertTrue(wire.getJSONObject("nutrition_per_100").isNull("protein_g"))
        assertEquals("0", wire.getJSONObject("nutrition_per_100").getString("fat_g"))
        assertTrue(wire.isNull("package_quantity")); assertTrue(wire.isNull("density_source")); assertFalse(wire.has("product"))
        decision(convert("product_draft", row.replace("50.125", "50.123456789")), "precision_review")
    }

    @Test fun oldMealUsesHistoricalItemValuesAndRemappedItemIdentityWithoutBasicCatalogueGuess() {
        val result = ready(convert("meal", meal, items = listOf(legacyItem)))
        val wire = JSONObject(result.payload!!); val first = wire.getJSONArray("items").getJSONObject(0)
        assertEquals(item, first.getString("item_id")); assertEquals("Historical ration", wire.getString("title"))
        assertEquals("2020-01-02", wire.getString("local_date")); assertEquals("lunch", wire.getString("meal_type"))
        assertTrue(wire.isNull("ration")); assertTrue(first.isNull("ration_component_position"))
        assertTrue(first.isNull("product")); assertEquals("manual", first.getString("nutrition_origin"))
        assertEquals("120", first.getJSONObject("quantity").getString("amount"))
        val nutrition = first.getJSONObject("nutrition_per_100")
        assertEquals("89", nutrition.getString("energy_kcal")); assertTrue(nutrition.isNull("protein_g"))
        assertEquals("0", nutrition.getString("fat_g")); assertEquals("22.8", nutrition.getString("carbs_g"))
    }

    @Test fun quantityTwelvePlacesNeverRoundsAndOriginalSourcesAndOldOutboxRemainExact() {
        val sourceText = legacyItem.replace("120.000000", "0.123456789012")
        val originals = listOf("""{"operationId":"old-operation","payload":"{}","wireFormat":"legacy","attempted":0}""")
        val source = LegacyImportSource("meal", "old", meal, listOf(sourceText), originals)
        decision(LegacyImportWire.convert(source, ids("meal"), LegacyImportMetadata(), schema), "precision_review")
        assertEquals(sourceText, source.items.single()); assertEquals(meal, source.row)
        assertEquals(originals, source.originalOutboxes)
        val changed = mutableListOf(sourceText)
        val detached = LegacyImportSource("meal", "old", meal, changed)
        changed.clear(); assertEquals(listOf(sourceText), detached.items)
    }

    private fun privateSnapshot(): JSONObject = JSONObject().put("formula_version", "nutrition_v1")
        .put("quantity", JSONObject().put("amount", "125").put("unit", "g"))
        .put("private_product", JSONObject().put("name", "Historic drink").put("basis_unit", "ml")
            .put("nutrition_per_100", JSONObject().put("energy_kcal", JSONObject.NULL).put("protein_g", JSONObject.NULL)
                .put("fat_g", "0").put("carbs_g", "12.5"))
            .put("density_g_per_ml", "1.25").put("density_source", "Historic density label"))
    @Test fun privateSnapshotOverridesLossyZeroProjectionsAndRetainsDensityAndQuantityUnit() {
        val historical = JSONObject(legacyItem).put("kcalPer100", 0).put("snapshotJson", privateSnapshot().toString()).toString()
        val first = JSONObject(ready(convert("meal", meal, items = listOf(historical))).payload!!).getJSONArray("items").getJSONObject(0)
        assertTrue(first.getJSONObject("nutrition_per_100").isNull("energy_kcal"))
        assertEquals("ml", first.getString("basis_unit")); assertEquals("g", first.getJSONObject("quantity").getString("unit"))
        assertEquals("1.25", first.getString("density_g_per_ml")); assertEquals("Historic density label", first.getString("density_source"))
        assertTrue(first.isNull("product"))
    }

    private fun catalogSnapshot(): JSONObject = JSONObject().put("formula_version", "nutrition_v1")
        .put("quantity", JSONObject().put("amount", "100").put("unit", "g"))
        .put("sources", JSONArray())
        .put("product", JSONObject().put("product_id", productId).put("revision", 3).put("name", "Archived E2")
            .put("basis_unit", "g").put("density_g_per_ml", JSONObject.NULL)
            .put("nutrition_per_100", JSONObject().put("energy_kcal", "89").put("protein_g", JSONObject.NULL)
                .put("fat_g", "0").put("carbs_g", "22.8")))
    @Test fun catalogueReferenceRequiresActualExternallyConfirmedRevisionProof() {
        val sourceItem = JSONObject(legacyItem).put("snapshotJson", catalogSnapshot().toString()).toString()
        fun itemOf(metadata: LegacyImportMetadata) = JSONObject(ready(convert("meal", meal, metadata, listOf(sourceItem))).payload!!)
            .getJSONArray("items").getJSONObject(0)
        assertTrue(itemOf(LegacyImportMetadata()).isNull("product"))
        assertTrue(itemOf(LegacyImportMetadata(provenCatalogProducts = setOf("$productId:3"))).isNull("product"))
        val proven = itemOf(LegacyImportMetadata(true, provenCatalogProducts = setOf("$productId:3")))
        assertEquals("catalog_snapshot", proven.getString("nutrition_origin"))
        assertEquals(productId, proven.getJSONObject("product").getString("product_id"))
        assertEquals(3, proven.getJSONObject("product").getInt("revision"))
    }

    @Test fun mappingsCannotBeGuessedCollideOrSilentlyUseSourceNonUuid() {
        decision(convert("meal", meal, items = listOf(legacyItem), mapping = LegacyImportIds(emptyMap())), "identity_mapping_required")
        decision(convert("meal", meal, items = listOf(legacyItem), mapping = LegacyImportIds(mapOf("meal:old" to target))), "identity_mapping_required")
        decision(convert("meal", meal, items = listOf(legacyItem), mapping = LegacyImportIds(mapOf("meal:old" to target, "meal:another" to target))), "identity_collision")
        decision(convert("meal", meal, items = listOf(legacyItem), mapping = LegacyImportIds(mapOf("meal:old" to target), mapOf("old-item" to item, "another" to item))), "identity_collision")
    }

    @Test fun existingWireAttemptedOperationsTombstonesAndTimestampLossRequireExplicitDecision() {
        val wire = """{"wireFormat":"sync-v1","attempted":0}"""
        decision(convert("meal", meal, items = listOf(legacyItem), outbox = listOf(wire)), "existing_wire_review")
        decision(convert("meal", meal, items = listOf(legacyItem), outbox = listOf("""{"attempted":1}""")), "existing_wire_review")
        decision(convert("meal", meal.replace("\"deleted\":0", "\"deleted\":1"), items = listOf(legacyItem)), "tombstone_review")
        decision(convert("meal", meal.replace("10:00:00Z", "10:00:00.123456789Z"), items = listOf(legacyItem)), "timestamp_precision_review")
        decision(convert("meal", meal.replace("2020-01-02T10:00:00Z", "2020-01-03T10:00:00Z"), items = listOf(legacyItem)), "invalid_legacy_data")
    }

    @Test fun explicitlyCorrectedPayloadRequiresConfirmationAndStillPassesRealWireValidation() {
        val canonical = javaClass.getResourceAsStream("/sync/profile.json")!!.use { String(it.readBytes()) }
        val source = """{"id":"old","heightCm":999999999}"""
        decision(convert("profile", source, LegacyImportMetadata(correctedPayload = canonical)), "confirmation_required")
        val result = ready(convert("profile", source, LegacyImportMetadata(true, correctedPayload = canonical)))
        assertEquals(JSONObject(canonical).getString("pseudonym"), JSONObject(result.payload!!).getString("pseudonym"))
        decision(convert("profile", source, LegacyImportMetadata(true, correctedPayload = "{}")), "invalid_legacy_data")
    }

    @Test fun provenRationChecksExactComponentRevisionPositionAndPackageLimit() {
        val ration = JSONObject().put("ration_id", other).put("revision", 2).put("name", "Proven archived ration")
            .put("components", JSONArray().put(JSONObject().put("position", 1)
                .put("product", JSONObject().put("product_id", productId).put("revision", 3))
                .put("quantity", JSONObject().put("amount", "100").put("unit", "g"))))
        val original = JSONObject(legacyItem).put("rationComponentPosition", 1)
            .put("snapshotJson", catalogSnapshot().toString()).toString()
        val metadata = LegacyImportMetadata(true, provenCatalogProducts = setOf("$productId:3"), provenRationJson = ration.toString())
        val wire = JSONObject(ready(convert("meal", meal, metadata, listOf(original))).payload!!)
        assertEquals(other, wire.getJSONObject("ration").getString("ration_id"))
        assertEquals(1, wire.getJSONArray("items").getJSONObject(0).getInt("ration_component_position"))
        val mismatch = JSONObject(ration.toString())
        mismatch.getJSONArray("components").getJSONObject(0).getJSONObject("product").put("revision", 4)
        decision(convert("meal", meal, metadata.copy(provenRationJson = mismatch.toString()), listOf(original)), "invalid_legacy_data")
        val oversized = catalogSnapshot().apply { getJSONObject("quantity").put("amount", "100.000001") }
        val tooMuch = JSONObject(legacyItem).put("rationComponentPosition", 1).put("snapshotJson", oversized.toString()).toString()
        decision(convert("meal", meal, metadata, listOf(tooMuch)), "invalid_legacy_data")
    }

    @Test fun orderedItemsUseExternalWireAliasesAndNullableQuantityTextFallsBackToHistoricalGrams() {
        val second = JSONObject(legacyItem).put("id", "second-item").put("productName", "Second historical item")
            .put("quantityText", JSONObject.NULL).put("grams", 75.125).toString()
        val mapping = LegacyImportIds(mapOf("meal:old" to target), mapOf("old-item" to item, "second-item" to other))
        val wire = JSONObject(ready(convert("meal", meal, items = listOf(second, legacyItem), mapping = mapping)).payload!!)
        val items = wire.getJSONArray("items")
        assertEquals(other, items.getJSONObject(0).getString("item_id"))
        assertEquals(item, items.getJSONObject(1).getString("item_id"))
        assertEquals("75.125", items.getJSONObject(0).getJSONObject("quantity").getString("amount"))
    }

    @Test fun confirmedCorrectedMealStillDeclaresItsMappedGoalDependency() {
        val payload = javaClass.getResourceAsStream("/sync/meal.json")!!.use { JSONObject(String(it.readBytes())) }
        payload.put("goal_id", other)
        payload.getJSONArray("items").getJSONObject(0).put("item_id", item)
        val metadata = LegacyImportMetadata(true, correctedPayload = payload.toString())
        decision(convert("meal", meal, metadata, listOf(legacyItem)), "identity_mapping_required")
        val mapping = LegacyImportIds(mapOf("meal:old" to target, "goal:historical-goal" to other), mapOf("old-item" to item))
        val result = ready(convert("meal", meal, metadata, listOf(legacyItem), mapping))
        assertEquals(listOf(LegacyImportDependency("goal", "historical-goal", other)), result.dependencies)
    }
    private fun intentOutbox(localId: String, goalType: String?, activity: String? = "LINE",
        payloadId: String = localId, outerType: String = "goal"): String {
        val payload = JSONObject().put("id", payloadId).put("goal_type", goalType ?: JSONObject.NULL)
            .put("activity_class", activity ?: JSONObject.NULL)
        return JSONObject().put("entityType", outerType).put("entityId", localId).put("wireFormat", "legacy")
            .put("attempted", 0).put("payload", payload.toString()).toString()
    }

    @Test fun eachGuestGoalKeepsItsCreationIntentFromOwnOutboxDespiteLaterProfileAim() {
        val noIntentOverride = audit().copy(goalAim = null, goalActivity = null)
        val maintain = intentOutbox("old", "maintain", "LINE")
        val reduce = intentOutbox("second", "reduce", "COMMANDO")
        // A newer profile's gain intent must never become evidence for either old goal.
        val profile = intentOutbox("old", "gain", "GARRISON", outerType = "profile")
        val rows = listOf(maintain, reduce, profile)
        val first = ready(convert("goal", goal, noIntentOverride, outbox = rows))
        assertEquals("maintain", JSONObject(first.payload!!).getString("goal_type"))
        assertEquals("line", JSONObject(first.payload!!).getString("activity_class"))
        val secondSource = LegacyImportSource("goal", "second", goal.replace("\"id\":\"old\"", "\"id\":\"second\""), originalOutboxes = rows)
        val second = LegacyImportWire.convert(secondSource, LegacyImportIds(mapOf("goal:second" to other)), noIntentOverride, schema)
            as LegacyImportConversion.Ready
        assertEquals("reduce", JSONObject(second.payload!!).getString("goal_type"))
        assertEquals("commando", JSONObject(second.payload!!).getString("activity_class"))
        assertEquals(rows, secondSource.originalOutboxes)
    }

    @Test fun olderGoalWithoutIntentAndOtherGoalOrMismatchedPayloadCannotSupplyProof() {
        val metadata = audit().copy(goalAim = null, goalActivity = null)
        val old = intentOutbox("old", null, null)
        decision(convert("goal", goal, metadata, outbox = listOf(old)), "missing_confirmed_metadata")
        decision(convert("goal", goal, metadata, outbox = listOf(intentOutbox("other-goal", "reduce"))), "missing_confirmed_metadata")
        decision(convert("goal", goal, metadata, outbox = listOf(intentOutbox("old", "reduce", payloadId = "another-id"))), "missing_confirmed_metadata")
        decision(convert("goal", goal, metadata, outbox = listOf(intentOutbox("old", "reduce", outerType = "profile"))), "missing_confirmed_metadata")
    }

    @Test fun contradictoryGoalIntentRequiresDecisionAndOnlyConfirmedMetadataCanResolveIt() {
        val evidence = listOf(intentOutbox("old", "maintain"), intentOutbox("old", "reduce"))
        val metadata = audit().copy(goalAim = null, goalActivity = null)
        decision(convert("goal", goal, metadata, outbox = evidence), "goal_intent_review")
        val resolved = ready(convert("goal", goal, metadata.copy(goalAim = "SURPLUS"), outbox = evidence))
        assertEquals("gain", JSONObject(resolved.payload!!).getString("goal_type"))
        assertEquals("line", JSONObject(resolved.payload!!).getString("activity_class"))
        val contradictoryRow = JSONObject(goal).put("goal_type", "gain").toString()
        decision(convert("goal", contradictoryRow, metadata, outbox = listOf(intentOutbox("old", "reduce"))), "goal_intent_review")
        val activityConflict = listOf(intentOutbox("old", "maintain", "LINE"), intentOutbox("old", "maintain", "COMMANDO"))
        decision(convert("goal", goal, metadata, outbox = activityConflict), "goal_intent_review")
        val chosen = ready(convert("goal", goal, metadata.copy(goalActivity = "GARRISON"), outbox = activityConflict))
        assertEquals("stationary", JSONObject(chosen.payload!!).getString("activity_class"))
    }
    @Test fun duplicateKeysInvalidNumbersAndUnsafeInputDoNotEscapeAsExceptionsOrLeakValues() {
        val duplicate = """{"id":"old","id":"private secret"}"""
        decision(convert("profile", duplicate), "invalid_legacy_data")
        decision(convert("profile", "not json"), "invalid_legacy_data")
        assertEquals("LegacyImportSource(redacted)", LegacyImportSource("profile", "old", duplicate).toString())
        assertEquals("LegacyImportMetadata(redacted)", audit().toString())
    }
}
