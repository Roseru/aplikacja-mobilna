package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.math.BigDecimal
import java.time.Instant

class MaintenanceImportTest {
    private val schema=SyncWireSchema(SyncWireSchema.FILES.associateWith {name->javaClass.getResourceAsStream("/sync/$name")!!.use {it.readBytes()}})
    private val estimate=MaintenanceEstimate.calculate(MaintenanceInput(30,BigDecimal("180"),BigDecimal("80"),EquationVariant.PLUS_5,ActivityClass.LINE),
        Instant.parse("2026-10-24T12:00:00Z"))
    private fun convert(outboxEstimate:JSONObject):LegacyImportConversion {
        val row=JSONObject().put("id","old").put("validFrom","2026-10-24").put("kcal",2500.0)
            .put("protein",JSONObject.NULL).put("fat",60.0).put("carbs",0.0).put("localSequence",1)
            .put("decidedAt","2026-10-24T12:00:00Z").put("zoneId","UTC").put("reason","user_decision")
            .put("correctionOf",JSONObject.NULL).put("estimateJson",estimate.stored())
        val payload=JSONObject().put("id","old").put("goal_type","reduce").put("activity_class","LINE").put("estimate",outboxEstimate)
        val outbox=JSONObject().put("entityType","goal").put("entityId","old").put("attempted",false)
            .put("wireFormat","legacy").put("payload",payload.toString())
        return LegacyImportWire.convert(LegacyImportSource("goal","old",row.toString(),originalOutboxes=listOf(outbox.toString())),
            LegacyImportIds(mapOf("goal:old" to "11111111-1111-4111-8111-111111111111")),
            LegacyImportMetadata(confirmed=true,timelineBaseRevision=0),schema)
    }
    @Test fun originalIntegerAgeAndCanonicalDecimalsSurviveBothImmutableEvidenceSources() {
        val value=convert(estimate.json());assertTrue(value.toString(),value is LegacyImportConversion.Ready)
        val payload=StrictJson.read(checkNotNull((value as LegacyImportConversion.Ready).payload).toByteArray())
        assertEquals(estimate.stored(),StrictJson.canonical(payload.getJSONObject("estimate")))
        assertEquals("2500",payload.getString("energy_kcal"));assertEquals("reduce",payload.getString("goal_type"))
    }
    @Test fun conflictingOrWronglyTypedAuditRequiresDecisionInsteadOfCoercionOrDiscarding() {
        val badAge=estimate.json().also {it.getJSONObject("input").put("age_years","30")}
        val numericHeight=estimate.json().also {it.getJSONObject("input").put("height_cm",180)}
        val changed=MaintenanceEstimate.calculate(estimate.input.copy(variant=EquationVariant.MINUS_161),estimate.estimatedAt).json()
        for(audit in listOf(badAge,numericHeight,changed)) {
            val value=convert(audit);assertTrue(value.toString(),value is LegacyImportConversion.NeedsDecision)
            assertEquals("estimate_review",(value as LegacyImportConversion.NeedsDecision).code)
        }
    }
}
