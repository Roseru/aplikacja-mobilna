package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.data.ImportSource
import pl.roseru.kalorie.importing.LegacyImportForm

class LegacyImportFormTest {
    private fun source(type: String, row: JSONObject, items: JSONArray = JSONArray(), outboxes: JSONArray = JSONArray(),
        previous: String = "{}"): ImportSource {
        val json = StrictJson.canonical(JSONObject().put("row", row).put("items", items).put("outboxes", outboxes))
        return ImportSource("fixture-plan", type, row.getString("id"), 0, json, "source-digest", outboxes.toString(),
            "local-alias", "11111111-1111-4111-8111-111111111111", metadataJson = previous)
    }
    private fun LegacyImportForm.key(suffix: String) = fields.single { it.key.endsWith(":$suffix") }.key
    private fun mealRow() = JSONObject().put("id", "legacy-meal").put("localDate", "2020-01-02")
        .put("occurredAt", "2020-01-02T10:00:00Z").put("zoneId", "Europe/Warsaw").put("mealType", "LUNCH")
        .put("rationName", JSONObject.NULL)
    private fun item(amount: String = "125.123456789012") = JSONObject().put("id", "legacy:item/id")
        .put("productName", "Historical drink").put("grams", amount).put("kcalPer100", JSONObject.NULL)
        .put("proteinPer100", JSONObject.NULL).put("fatPer100", "0").put("carbsPer100", "12.5")
        .put("snapshotJson", JSONObject.NULL)
    private fun snapshot() = JSONObject().put("formula_version", "nutrition_v1")
        .put("quantity", JSONObject().put("amount", "125.123456789012").put("unit", "g"))
        .put("private_product", JSONObject().put("name", "Historical drink").put("basis_unit", "ml")
            .put("nutrition_per_100", JSONObject().put("energy_kcal", JSONObject.NULL).put("protein_g", JSONObject.NULL)
                .put("fat_g", "0").put("carbs_g", "12.5"))
            .put("density_g_per_ml", "1.25").put("density_source", "Original measured label"))

    @Test fun twelvePlaceAmountAndNullRemainVisibleUntilExplicitLosslessCorrection() {
        val original = source("meal", mealRow(), JSONArray().put(item()))
        val bytes = original.sourceJson
        val form = LegacyImportForm.from(original)
        val quantity = form.fields.single { it.key.endsWith(":amount") }
        assertEquals("125.123456789012", quantity.original); assertEquals(quantity.original, quantity.value)
        assertThrows(IllegalArgumentException::class.java) { form.choice(emptyMap()) }
        val choice = JSONObject(form.choice(mapOf(quantity.key to "125,123456")))
        val changed = choice.getJSONArray("item_overrides").getJSONObject(0)
        assertEquals("legacy:item/id", changed.getString("id")); assertEquals("125.123456", changed.getString("amount"))
        assertFalse(changed.has("energy_kcal")); assertFalse(choice.has("row_overrides"))
        assertEquals(bytes, original.sourceJson)
        assertEquals("", form.fields.single { it.key.endsWith(":energy_kcal") }.value)
        assertEquals("0", form.fields.single { it.key.endsWith(":fat_g") }.value)
    }

    @Test fun privateHistoricalSnapshotOwnsUnknownEnergyAndUnitsInsteadOfMutableRealProjection() {
        val historical = item().put("kcalPer100", "999").put("grams", "5").put("snapshotJson", snapshot().toString())
        val original = source("meal", mealRow(), JSONArray().put(historical))
        val form = LegacyImportForm.from(original)
        assertEquals("", form.fields.single { it.key.endsWith(":energy_kcal") }.original)
        assertEquals("125.123456789012", form.fields.single { it.key.endsWith(":amount") }.original)
        assertEquals("ml", form.fields.single { it.key.endsWith(":basis_unit") }.value)
        assertEquals("g", form.fields.single { it.key.endsWith(":unit") }.value)
        assertEquals("1.25", form.fields.single { it.key.endsWith(":density") }.original)
        assertEquals("Original measured label", form.fields.single { it.key.endsWith(":density_source") }.original)
        val changed = JSONObject(form.choice(mapOf(form.key("amount") to "125.123456", form.key("energy_kcal") to "50")))
            .getJSONArray("item_overrides").getJSONObject(0)
        assertEquals("50", changed.getString("energy_kcal")); assertFalse(changed.has("product"))
    }

    @Test fun unchangedCatalogueSnapshotIsNotRecastAsManualAndUuidIsNotAVisibleValue() {
        val id = "44444444-4444-4444-8444-444444444444"
        val catalog = snapshot(); val product = catalog.getJSONObject("private_product")
        product.put("density_g_per_ml", JSONObject().put("amount", "1.25").put("source_id", id))
        product.remove("density_source"); catalog.remove("private_product"); catalog.put("product", product)
        catalog.getJSONObject("quantity").put("amount", "125")
        catalog.put("sources", JSONArray().put(JSONObject().put("source_id", id).put("notes", JSONArray().put("Historical manufacturer density label"))))
        val original = source("meal", mealRow(), JSONArray().put(item().put("snapshotJson", catalog.toString())))
        val form = LegacyImportForm.from(original)
        assertTrue(form.fields.none { it.label.contains(id) || it.original == id || it.value == id })
        assertEquals("Historical manufacturer density label", form.fields.single { it.key.endsWith(":density_source") }.value)
        val choice = JSONObject(form.choice(emptyMap()))
        assertFalse(choice.has("item_overrides")); assertFalse(choice.has("row_overrides"))
    }

    private fun oldGoal() = JSONObject().put("id", "old-goal").put("kcal", "2500.125").put("protein", JSONObject.NULL)
        .put("fat", "0").put("carbs", "200.5").put("validFrom", "1970-01-01")
        .put("decidedAt", JSONObject.NULL).put("zoneId", JSONObject.NULL).put("reason", "legacy")
    @Test fun unknownGoalHasBlankRequiredAuditAndNoCurrentProfileOrClockDefaults() {
        val form = LegacyImportForm.from(source("goal", oldGoal()))
        for (suffix in listOf("goal_decided_at", "zoneId", "goal_reason", "goal_aim", "goal_activity")) {
            val field = form.fields.single { it.key.endsWith(":$suffix") }
            assertEquals("", field.value); assertTrue(field.required)
        }
        assertEquals("1970-01-01", form.fields.single { it.key.endsWith(":validFrom") }.original)
        assertThrows(IllegalArgumentException::class.java) { form.choice(emptyMap()) }
        val choice = JSONObject(form.choice(mapOf(form.key("goal_decided_at") to "1970-01-01T10:00:00Z",
            form.key("zoneId") to "Europe/Warsaw", form.key("goal_reason") to "user_decision",
            form.key("goal_aim") to "reduce", form.key("goal_activity") to "line")))
        assertEquals("reduce", choice.getString("goal_aim")); assertEquals("line", choice.getString("goal_activity"))
        assertEquals("1970-01-01T10:00:00Z", choice.getString("goal_decided_at"))
        assertEquals("Europe/Warsaw", choice.getJSONObject("row_overrides").getString("zoneId"))
        assertTrue(form.fields.single { it.key.endsWith(":goal_reason") }.options.contains("Korekta historii" to "history_correction"))
    }

    @Test fun ownGoalOutboxIntentIsPreservedAndUnrelatedOrConflictingProofDoesNotPrefill() {
        fun original(id: String, aim: String) = JSONObject().put("entityType", "goal").put("entityId", id)
            .put("payload", JSONObject().put("id", id).put("goal_type", aim).put("activity_class", "LINE").toString())
        val outboxes = JSONArray().put(original("old-goal", "reduce")).put(original("other", "gain"))
        val form = LegacyImportForm.from(source("goal", oldGoal(), outboxes = outboxes))
        assertEquals("reduce", form.fields.single { it.key.endsWith(":goal_aim") }.value)
        assertEquals("line", form.fields.single { it.key.endsWith(":goal_activity") }.value)
        outboxes.put(original("old-goal", "maintain"))
        val conflict = LegacyImportForm.from(source("goal", oldGoal(), outboxes = outboxes))
        assertEquals("", conflict.fields.single { it.key.endsWith(":goal_aim") }.value)
    }

    @Test fun profileAndDayUseNormalPolishOptionsAndSerializeBooleanRatherThanText() {
        val row = JSONObject().put("id", "profile").put("nickname", "Local name").put("heightCm", JSONObject.NULL)
            .put("zoneId", "Europe/Warsaw").put("activityClass", "GARRISON").put("dietAim", "MAINTAIN")
        val profile = LegacyImportForm.from(source("profile", row))
        assertEquals("", profile.fields.single { it.key.endsWith(":heightCm") }.value)
        assertTrue(profile.fields.none { it.key.endsWith(":dietAim") })
        val choice = JSONObject(profile.choice(mapOf(profile.key("activityClass") to "COMMANDO")))
        assertEquals("COMMANDO", choice.getJSONObject("row_overrides").getString("activityClass"))
        assertFalse(choice.getJSONObject("row_overrides").has("dietAim"))
        val day = LegacyImportForm.from(source("diary_day", JSONObject().put("id", "day").put("localDate", "2020-01-02")
            .put("declaredComplete", 1).put("zoneId", "Europe/Warsaw")))
        assertFalse(JSONObject(day.choice(mapOf(day.key("declaredComplete") to "false"))).getJSONObject("row_overrides").getBoolean("declaredComplete"))
    }

    @Test fun productUsesExactPrivateWireValuesAndRestoresPriorChoiceWithoutChangingOriginal() {
        val product = snapshot().getJSONObject("private_product").put("source_description", "Historical source")
        val row = JSONObject().put("id", "product").put("wirePayload", product.toString()).put("name", "Changed projection")
            .put("kcal", "0").put("protein", "99").put("fat", "0").put("carbs", "0").put("source", "Current source")
        val previous = """{"choice":"metadata","row_overrides":{"kcal":"50.125","protein":null}}"""
        val original = source("product_draft", row, previous = previous)
        val form = LegacyImportForm.from(original)
        assertEquals("Historical drink", form.fields.single { it.key.endsWith(":name") }.original)
        assertEquals("", form.fields.single { it.key.endsWith(":kcal") }.original)
        assertEquals("50.125", form.fields.single { it.key.endsWith(":kcal") }.value)
        assertEquals("Historical source", form.fields.single { it.key.endsWith(":source") }.value)
        assertEquals("50.125", JSONObject(form.choice(emptyMap())).getJSONObject("row_overrides").getString("kcal"))
        assertEquals(previous, original.metadataJson)
    }

    @Test fun changingKnownGoalReasonAndTimeWritesRowOverridesAndStandaloneClearsCorrectionSemantics() {
        val row = oldGoal().put("decidedAt", "1970-01-01T10:00:00Z").put("zoneId", "Europe/Warsaw")
            .put("reason", "history_correction").put("goal_type", "maintain").put("activity_class", "line")
        val form = LegacyImportForm.from(source("goal", row))
        val choice = JSONObject(form.choice(mapOf(form.key("goal_decided_at") to "1970-01-01T11:00:00Z"), standaloneGoal = true))
        assertEquals("user_decision", choice.getString("goal_reason"))
        assertEquals("user_decision", choice.getJSONObject("row_overrides").getString("reason"))
        assertEquals("1970-01-01T11:00:00Z", choice.getJSONObject("row_overrides").getString("decidedAt"))
        assertTrue(choice.getBoolean("standalone_goal"))
    }

    @Test fun invalidDecimalsDatesOptionsAndUnknownKeysNeverProduceAChoice() {
        val row = JSONObject().put("id", "weight").put("kg", "80").put("localDate", "2020-01-02")
            .put("occurredAt", "2020-01-02T10:00:00Z").put("zoneId", "Europe/Warsaw")
        val form = LegacyImportForm.from(source("weight", row))
        for (value in listOf("NaN", "Infinity", "-1", "80.1234567", "1e-99999999"))
            assertThrows(IllegalArgumentException::class.java) { form.choice(mapOf(form.key("kg") to value)) }
        assertThrows(IllegalArgumentException::class.java) { form.choice(mapOf(form.key("localDate") to "2020-02-30")) }
        assertThrows(IllegalArgumentException::class.java) { form.choice(mapOf(form.key("zoneId") to "Mars/Unknown")) }
        assertThrows(IllegalArgumentException::class.java) { form.choice(mapOf("row:id" to "invented")) }
    }
}
