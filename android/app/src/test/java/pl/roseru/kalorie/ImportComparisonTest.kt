package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.data.ImportSource
import pl.roseru.kalorie.importing.*

class ImportComparisonTest {
    private fun source(type: String, row: JSONObject, items: JSONArray = JSONArray(), canonical: String? = null,
        outboxes: JSONArray = JSONArray()): ImportSource {
        val archive = JSONObject().put("row", row).put("items", items).put("outboxes", outboxes)
            .put("canonical_payload", canonical ?: JSONObject.NULL).toString()
        return ImportSource("plan", type, "source", 0, archive, "immutable-digest", outboxes.toString(), "local", "wire")
    }
    private fun ImportComparisonSide.value(label: String) = values.single { it.label == label }.value
    @Test fun independentLocal82AndServer80AreDistinctAndOriginalBytesStayUntouched() {
        val original = source("weight", JSONObject().put("id", "source").put("kg", "82")
            .put("localDate", "2020-01-02").put("occurredAt", "2020-01-02T10:00:00Z").put("zoneId", "Europe/Warsaw"))
        val bytes = original.sourceJson
        val local = ImportComparison.local(original)
        val server = ImportComparison.server("weight", """{"weight_kg":"80","local_date":"2020-01-02","occurred_at":"2020-01-02T10:00:00Z","time_zone":"Europe/Warsaw"}""")
        assertEquals(ImportSideState.PRESENT, local.state); assertEquals("82 kg", local.value("Masa ciała"))
        assertEquals("80 kg", server.value("Masa ciała")); assertNotEquals(local, server)
        assertEquals(bytes, original.sourceJson); assertEquals("immutable-digest", original.sourceHash)
    }
    @Test fun nullDoesNotBecomeZeroAndFullExactQuantityIsNotRounded() {
        val meal = """{"title":"Soup","items":[{"name":"Historic soup","quantity":{"amount":"0.123456789012","unit":"ml"},"basis_unit":"ml","nutrition_per_100":{"energy_kcal":null,"protein_g":"0","fat_g":"1.234567","carbs_g":null},"density_g_per_ml":null,"density_source":null}]}"""
        val side = ImportComparison.server("meal", meal)
        assertEquals("0.123456789012 ml", side.value("Składnik 1: ilość"))
        assertEquals("Brak danych", side.value("Składnik 1: Energia na 100 ml"))
        assertEquals("0 g", side.value("Składnik 1: Białko na 100 ml"))
        assertEquals("1.234567 g", side.value("Składnik 1: Tłuszcz na 100 ml"))
    }
    @Test fun unreadableSnapshotIsPerItemAndCannotEraseOtherItemsOrInventSnapshotValues() {
        val row = JSONObject().put("localDate", "2019-02-03").put("mealType", "LUNCH")
        val corrupt = JSONObject().put("productName", "Known historical name").put("snapshotJson", "{").put("grams", "999").put("kcalPer100", "999")
        val intact = JSONObject().put("productName", "Other intact item").put("grams", "75.125")
            .put("kcalPer100", "89").put("proteinPer100", JSONObject.NULL).put("fatPer100", "0").put("carbsPer100", "22.8")
        val original = source("meal", row, JSONArray().put(corrupt).put(intact))
        val bytes = original.sourceJson; val side = ImportComparison.local(original)
        assertEquals(ImportSideState.PRESENT, side.state)
        assertEquals("2019-02-03", side.value("Data posiłku"))
        assertEquals("Known historical name", side.value("Składnik 1: nazwa"))
        assertEquals("Nie można odczytać danych składnika", side.value("Składnik 1: zapis historyczny"))
        assertTrue(side.values.none { it.label == "Składnik 1: ilość" || it.value == "999 kcal" })
        assertEquals("75.125 g", side.value("Składnik 2: ilość")); assertEquals("89 kcal", side.value("Składnik 2: Energia na 100 g"))
        assertEquals(bytes, original.sourceJson)
    }
    @Test fun canonicalLocalPayloadWinsOverLossyProjectionAndOtherDomainCorruptionIsNotRead() {
        val canonical = """{"weight_kg":"82.123456","local_date":"2020-01-02"}"""
        val original = source("weight", JSONObject().put("kg", "0").put("wirePayload", "{"), canonical = canonical)
        assertEquals("82.123456 kg", ImportComparison.local(original).value("Masa ciała"))
        val rowOnly = source("weight", JSONObject().put("kg", "82").put("wirePayload", "{"))
        assertEquals("82 kg", ImportComparison.local(rowOnly).value("Masa ciała"))
        assertEquals(ImportSideState.UNREADABLE, ImportComparison.local(original.copy(sourceJson = "{" )).state)
    }
    @Test fun deletedAbsentUnverifiedAndUnreadableRemainDifferentStates() {
        assertEquals(ImportSideState.ABSENT, ImportComparison.server("weight", null).state)
        assertEquals(ImportSideState.DELETED, ImportComparison.server("weight", "{", true).state)
        assertEquals(ImportSideState.UNREADABLE, ImportComparison.server("weight", "{").state)
        assertNotEquals(ImportSideState.UNVERIFIED, ImportComparison.server("weight", null).state)
        assertEquals(ImportSideState.DELETED, ImportComparison.local(source("profile", JSONObject().put("deleted", 1))).state)
    }
    @Test fun goalAndProfileUseReadableIntentWithExactMacrosAndNoTechnicalIdentity() {
        val id = "44444444-4444-4444-8444-444444444444"
        val payload = """{"energy_kcal":"2500.125","protein_g":null,"fat_g":"0","carbs_g":"200.5","goal_type":"reduce","activity_class":"line","effective_from":"1970-01-01","decided_at":"1970-01-01T10:00:00Z","reason":"history_correction","correction_of":"$id"}"""
        val goal = ImportComparison.server("goal", payload)
        assertEquals("2500.125 kcal", goal.value("Cel energii")); assertEquals("Brak danych", goal.value("Cel białka"))
        assertEquals("0 g", goal.value("Cel tłuszczu")); assertEquals("200.5 g", goal.value("Cel węglowodanów"))
        assertEquals("Redukcja", goal.value("Rodzaj celu")); assertEquals("Linia", goal.value("Klasa aktywności"))
        assertEquals("1970-01-01", goal.value("Obowiązuje od")); assertTrue(goal.values.none { it.value.contains(id) || it.value.startsWith('{') })
        val profile = ImportComparison.server("profile", """{"pseudonym":"Local name","height_cm":null,"activity_class":"commando","time_zone":"Europe/Warsaw"}""")
        assertEquals("Local name", profile.value("Pseudonim")); assertEquals("Brak danych", profile.value("Wzrost")); assertEquals("Komandos", profile.value("Klasa aktywności"))
    }
    @Test fun privateSnapshotUsesHistoricalUnitsDensityAndUnknownEnergyAndDayBooleanIsReadable() {
        val product = JSONObject().put("name", "Historic drink").put("basis_unit", "ml")
            .put("nutrition_per_100", JSONObject().put("energy_kcal", JSONObject.NULL).put("protein_g", "0").put("fat_g", "0").put("carbs_g", "12.5"))
            .put("density_g_per_ml", "1.25").put("density_source", "Original density label").put("source_description", "Historical recipe")
        val snapshot = JSONObject().put("private_product", product).put("quantity", JSONObject().put("amount", "125.000000000001").put("unit", "g"))
        val item = JSONObject().put("snapshotJson", snapshot.toString()).put("grams", "5").put("kcalPer100", "0")
        val meal = ImportComparison.local(source("meal", JSONObject(), JSONArray().put(item)))
        assertEquals("125.000000000001 g", meal.value("Składnik 1: ilość")); assertEquals("Brak danych", meal.value("Składnik 1: Energia na 100 ml"))
        assertEquals("1.25 g/ml", meal.value("Składnik 1: gęstość")); assertEquals("Original density label", meal.value("Składnik 1: źródło gęstości"))
        val privateProduct = ImportComparison.local(source("product_draft", JSONObject().put("wirePayload", product.toString()).put("kcal", "0")))
        assertEquals("Brak danych", privateProduct.value("Energia na 100 ml")); assertEquals("Historical recipe", privateProduct.value("Źródło wartości"))
        val day = ImportComparison.server("diary_day", """{"local_date":"2020-01-02","declared_complete":false,"time_zone":"Europe/Warsaw"}""")
        assertEquals("Nie", day.value("Deklarowana kompletność"))
    }
    @Test fun historicalGoalIntentIsOnlyFromItsOwnMatchingOutbox() {
        val row = JSONObject().put("id", "source").put("kcal", "2500")
        fun outbox(id: String, aim: String) = JSONObject().put("entityType", "goal").put("entityId", id)
            .put("payload", JSONObject().put("id", id).put("goal_type", aim).put("activity_class", "LINE").toString())
        val original = source("goal", row, outboxes = JSONArray().put(outbox("source", "maintain")).put(outbox("another", "reduce")))
        val side = ImportComparison.local(original)
        assertEquals("Utrzymanie", side.value("Rodzaj celu")); assertEquals("Linia", side.value("Klasa aktywności"))
        assertEquals("Brak danych", side.value("Czas decyzji (UTC)"))
    }
}
