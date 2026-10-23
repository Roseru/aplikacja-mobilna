package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.ContractDecimal
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*

class PrivateDomainsWireTest {
    private val schema = SyncWireSchema(SyncWireSchema.FILES.associateWith { resource(it).toByteArray() })
    private val id = "11111111-1111-4111-8111-111111111111"
    private val op = "44444444-4444-4444-8444-444444444444"
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private val fixtures = mapOf("profile" to "profile.json", "goal" to "goal.json",
        "diary_day" to "diary-day.json", "product_draft" to "product-draft.json")
    private fun resource(name: String) = javaClass.getResourceAsStream("/sync/$name")!!.use {
        String(it.readBytes(), Charsets.UTF_8)
    }
    private fun payload(type: String) = JSONObject(resource(fixtures.getValue(type)))
    private fun read(type: String, value: JSONObject) = PrivateDomainsWire.read(type, value.toString(), schema)
    private fun invalid(type: String, value: JSONObject) {
        assertThrows(SyncWireException::class.java) { read(type, value) }
    }

    @Test fun fourDomainsKeepCanonicalDetachedSnapshotsAndExplicitNulls() {
        for (type in fixtures.keys) {
            val original = payload(type)
            val canonical = read(type, original)
            assertEquals(StrictJson.canonical(original), canonical)
            assertEquals(canonical, PrivateDomainsWire.read(type, canonical, schema))
            original.put("unexpected", "changed after serialization")
            assertFalse(JSONObject(canonical).has("unexpected"))
        }
        assertTrue(JSONObject(read("profile", payload("profile").put("height_cm", JSONObject.NULL))).isNull("height_cm"))
        assertTrue(JSONObject(read("goal", payload("goal"))).isNull("protein_g"))
        assertTrue(JSONObject(read("product_draft", payload("product_draft"))).isNull("brand"))
    }

    @Test fun createsUpdatesAndDeletesRequireExactIdentityRevisionAndKnownType() {
        for (type in fixtures.keys) {
            val text = read(type, payload(type))
            val create = JSONObject(PrivateDomainsWire.operation(op, type, id, epoch, null, text, schema))
            assertEquals(op, create.getString("operation_id"))
            assertEquals(type, create.getString("entity_type"))
            assertTrue(create.isNull("base_revision"))
            assertEquals(text, StrictJson.canonical(create.getJSONObject("payload")))
            val update = JSONObject(PrivateDomainsWire.operation(op, type, id, epoch, 3, text, schema))
            assertEquals(3, update.getInt("base_revision"))
            val delete = JSONObject(PrivateDomainsWire.operation(op, type, id, epoch, 4, null, schema))
            assertEquals("delete", delete.getString("action"))
            assertTrue(delete.isNull("payload"))
            assertThrows(SyncWireException::class.java) { PrivateDomainsWire.operation(op, type, id, epoch, null, null, schema) }
            assertThrows(SyncWireException::class.java) { PrivateDomainsWire.operation(op, type, id, epoch, 0, null, schema) }
        }
        assertThrows(SyncWireException::class.java) { PrivateDomainsWire.read("meal", "{}", schema) }
        assertThrows(SyncWireException::class.java) { PrivateDomainsWire.operation(op, "unknown", id, epoch, 1, null, schema) }
        assertThrows(SyncWireException::class.java) { PrivateDomainsWire.operation("bad", "profile", id, epoch, null, read("profile", payload("profile")), schema) }
    }

    @Test fun profileRejectsSemanticRangeUnsafeTextsMissingFieldsAndInvalidZones() {
        invalid("profile", payload("profile").put("height_cm", "300.000001"))
        invalid("profile", payload("profile").put("height_cm", "0"))
        invalid("profile", payload("profile").put("pseudonym", "x\u0000y"))
        invalid("profile", payload("profile").put("time_zone", "Mars/Unknown"))
        invalid("profile", payload("profile").apply { remove("height_cm") })
        invalid("profile", payload("profile").put("height_cm", 180))
        invalid("profile", payload("profile").put("height_cm", "180.0"))
        assertThrows(SyncWireException::class.java) {
            PrivateDomainsWire.read("profile", resource("profile.json").replace("\"height_cm\":", "\"height_cm\":null,\"height_cm\":"), schema)
        }
    }

    @Test fun goalsCheckLocalDecisionDayBoundsAndCorrectionAudit() {
        invalid("goal", payload("goal").put("energy_kcal", "20000.000001"))
        invalid("goal", payload("goal").put("protein_g", "5000.000001"))
        invalid("goal", payload("goal").put("effective_from", "2026-10-08"))
        invalid("goal", payload("goal").put("decided_at", "2026-10-09T23:30:00Z"))
        invalid("goal", payload("goal").put("reason", "history_correction"))
        invalid("goal", payload("goal").put("correction_of", id))
        read("goal", payload("goal").put("reason", "history_correction")
            .put("correction_of", id).put("effective_from", "2020-01-01"))
    }

    @Test fun timelineAssertionCannotMutatePayloadOrEnterOtherDomainsOrDelete() {
        val text = read("goal", payload("goal").put("timeline_base_revision", 7))
        val operation = JSONObject(PrivateDomainsWire.operation(op, "goal", id, epoch, null, text, schema, 7))
        assertEquals(text, StrictJson.canonical(operation.getJSONObject("payload")))
        assertFalse(operation.has("timeline_base_revision"))
        assertThrows(SyncWireException::class.java) { PrivateDomainsWire.operation(op, "goal", id, epoch, null, text, schema, 8) }
        assertThrows(SyncWireException::class.java) { PrivateDomainsWire.operation(op, "goal", id, epoch, 1, null, schema, 7) }
        assertThrows(SyncWireException::class.java) { PrivateDomainsWire.operation(op, "profile", id, epoch, null, read("profile", payload("profile")), schema, 0) }
        invalid("goal", payload("goal").put("timeline_base_revision", -1))
        invalid("goal", payload("goal").put("timeline_base_revision", 2147483648L))
    }

    @Test fun exactEstimateKeepsComputedPrecisionAndRejectsInconsistentArithmetic() {
        val estimate = JSONObject("""{"method":"mifflin_pal_v1","input":{"age_years":30,"height_cm":"180.000001","weight_kg":"80","equation_variant":"plus_5","activity_class":"line"},"resting_kcal":"1780.00000625","pal":"1.8","maintenance_kcal":"3204.00001125","estimated_at":"2026-10-09T10:00:00Z"}""")
        val value = payload("goal").put("estimate", estimate)
        assertEquals("3204.00001125", JSONObject(read("goal", value)).getJSONObject("estimate").getString("maintenance_kcal"))
        invalid("goal", value.apply { estimate.put("maintenance_kcal", "3204.000011") })
        estimate.put("maintenance_kcal", "3204.00001125").put("pal", "2.2")
        invalid("goal", value)
        estimate.put("pal", "1.8").getJSONObject("input").put("weight_kg", "1000.000001")
        invalid("goal", value)
    }

    @Test fun privateDraftRequiresDensityEvidenceAndNeverInventsCatalogueReferences() {
        val value = payload("product_draft")
        invalid("product_draft", JSONObject(value.toString()).put("density_g_per_ml", "1"))
        invalid("product_draft", JSONObject(value.toString()).put("density_source", "label"))
        value.put("package_quantity", JSONObject().put("amount", "250").put("unit", "ml"))
        invalid("product_draft", value)
        value.put("density_g_per_ml", "1.03").put("density_source", "Measured sample")
        val wire = JSONObject(read("product_draft", value))
        assertFalse(wire.has("product"))
        assertTrue(wire.getJSONObject("nutrition_per_100").isNull("protein_g"))
        invalid("product_draft", JSONObject(value.toString()).put("product", JSONObject().put("product_id", id)))
        invalid("product_draft", JSONObject(value.toString()).put("source_description", JSONObject.NULL))
        value.getJSONObject("package_quantity").put("amount", "999999.999999")
        read("product_draft", value) // Draft package size has no Meal's 10000-unit cap.
    }

    @Test fun twelvePlaceLocalQuantityIsNotSilentlyRoundedForWire() {
        assertNotNull(ContractDecimal.userQuantity("0.123456789012", 12))
        val value = payload("product_draft").put("package_quantity",
            JSONObject().put("amount", "0.123456789012").put("unit", "g"))
        invalid("product_draft", value)
        assertEquals("0.123456789012", value.getJSONObject("package_quantity").getString("amount"))
        value.getJSONObject("package_quantity").put("amount", "0.123456")
        read("product_draft", value)
    }

    @Test fun dayDeclarationRequiresStrictBooleanAndRealCalendarDate() {
        invalid("diary_day", payload("diary_day").put("local_date", "2026-02-30"))
        invalid("diary_day", payload("diary_day").put("declared_complete", "true"))
        invalid("diary_day", payload("diary_day").put("effective_complete", true))
        assertFalse(JSONObject(read("diary_day", payload("diary_day").put("declared_complete", false))).getBoolean("declared_complete"))
    }
}
