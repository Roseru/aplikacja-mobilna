package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.energy.*
import java.math.BigDecimal
import java.time.Instant

class EnergyProtocolTest {
    private fun bytes(name:String)=javaClass.getResourceAsStream("/energy/$name")!!.use {it.readBytes()}
    private fun sample(name:String)=StrictJson.read(bytes("energy-$name.json"))
    private val protocol get()=EnergyProtocol(EnergySchema(bytes("energy.schema.json")))
    private fun encoded(value:JSONObject)=StrictJson.canonical(value).toByteArray()
    private val now=Instant.parse("2026-10-24T10:00:00Z")

    @Test fun requestedIsNotEffectiveAndEmptyHistoryKeepsItsIntegerCursor() {
        val state=protocol.state(encoded(sample("state")))
        assertTrue(state.automaticRequested);assertFalse(state.automaticEffective);assertNull(state.automaticNotice)
        assertNull(state.baselineId)
        val empty=protocol.history(encoded(JSONObject().put("items",JSONArray()).put("next_revision",3)),3)
        assertTrue(empty.items.isEmpty());assertEquals(3,empty.nextRevision)
        val page=protocol.history(encoded(JSONObject().put("items",JSONArray().put(sample("version"))).put("next_revision",3)),2)
        assertEquals(BigDecimal("3204"),page.items.single().maintenance)
        assertThrows(IllegalArgumentException::class.java){protocol.state(encoded(sample("state").put("automatic_effective",true)))}
        assertThrows(IllegalArgumentException::class.java){protocol.history(encoded(JSONObject().put("items",JSONArray()).put("next_revision",4)),3)}
        val enabled=sample("state").put("automatic_effective",true).put("baseline_id",state.currentId)
        enabled.put("automatic_notice",sample("analysis").getJSONObject("notice").put("scope","automatic_energy_adjustment").put("baseline_id",state.currentId))
        val local=EnergyLocalState(null,protocol.state(encoded(enabled)),emptyList(),emptyList(),
            pl.roseru.kalorie.core.ProfileReadProtocol.parse(encoded(sample("profile"))),null,null,emptyList(),0,null,0)
        assertTrue(EnergyViewState(local=local).automaticEffective)
        assertFalse(EnergyViewState(local=local.copy(consentUncertain=true)).automaticEffective)
        assertFalse(EnergyViewState(local=local,externalConsentUncertain=true).automaticEffective)
    }
    @Test fun readyProposalRetainsSnapshotAndNoticeAndExpiresAtTheExactDeadline() {
        val analysis=protocol.analysisResponse(encoded(sample("analysis"))) as EnergyAnalysis
        assertTrue(analysis.canAccept(now));assertFalse(analysis.canAccept(Instant.parse("2026-10-25T09:01:00Z")))
        assertEquals(3,analysis.sourceAxisRevision);assertEquals(BigDecimal("3100"),analysis.result.proposed)
        val wrong=sample("analysis");wrong.getJSONObject("notice").put("snapshot_hash","b".repeat(64))
        assertThrows(IllegalArgumentException::class.java){protocol.analysisResponse(encoded(wrong))}
        val axis=protocol.state(encoded(sample("state")))
        assertThrows(IllegalArgumentException::class.java){protocol.analysisRequest(axis,"mock",true,false)}
        assertThrows(IllegalArgumentException::class.java){protocol.affirmationRequest(axis,2,"mock",false,true)}
        val manual=StrictJson.read(protocol.analysisRequest(axis,"mock",true,true).toByteArray())
        val automatic=StrictJson.read(protocol.affirmationRequest(axis,2,"mock",true,true).toByteArray())
        assertEquals("this_energy_analysis",manual.getJSONObject("notice").getString("scope"))
        assertEquals("automatic_energy_adjustment",automatic.getJSONObject("notice").getString("scope"))
        assertEquals(2,automatic.getInt("consent_revision"))
        assertFalse(analysis.toString().contains(analysis.id));assertFalse(axis.toString().contains(axis.epoch))
    }
    @Test fun decisionsUseFrozenSourceRevisionAndReplacementNeedsAnExplicitChoice() {
        val axis=protocol.state(encoded(sample("state")));val analysis=protocol.analysisResponse(encoded(sample("analysis"))) as EnergyAnalysis
        val decision=StrictJson.read(protocol.decisionRequest(axis,analysis,true,now).toByteArray())
        assertEquals(analysis.id,decision.getString("id"));assertEquals(2,decision.getInt("revision"));assertEquals(3,decision.getInt("axis_revision"))
        assertThrows(IllegalArgumentException::class.java){protocol.decisionRequest(axis.copy(axisRevision=4),analysis,true,now)}
        val old=sample("version").put("entity_id","77777777-7777-4777-8777-777777777777").put("revision",2)
        val target=protocol.version(old)
        val replace="88888888-8888-4888-8888-888888888888"
        assertThrows(IllegalArgumentException::class.java){protocol.revertRequest(axis,target,replace,false)}
        val restored=StrictJson.read(protocol.revertRequest(axis,target,replace,true).toByteArray())
        assertEquals(target.id,restored.getString("id"));assertEquals(replace,restored.getString("replace_id"))
        assertEquals(3,restored.getInt("axis_revision"))
    }
    @Test fun pinnedSchemaRejectsNumericCoercionUnknownFieldsAndChangedConfiguration() {
        val lf=bytes("energy.schema.json").toString(Charsets.UTF_8).replace("\r\n","\n")
        for(configuration in listOf(lf,lf.replace("\n","\r\n"))) {
            val platform=EnergyProtocol(EnergySchema(configuration.toByteArray(Charsets.UTF_8)))
            assertEquals(3,platform.state(encoded(sample("state"))).axisRevision)
        }
        assertThrows(IllegalArgumentException::class.java){protocol.state(encoded(sample("state").put("account_generation","1")))}
        assertThrows(IllegalArgumentException::class.java){protocol.state(encoded(sample("state").put("extra",true)))}
        val wrong=sample("analysis");wrong.getJSONObject("result").put("proposed",3100)
        assertThrows(IllegalArgumentException::class.java){protocol.analysisResponse(encoded(wrong))}
        val schema=JSONObject(bytes("energy.schema.json").toString(Charsets.UTF_8))
        schema.getJSONObject("\$defs").getJSONObject("EnergyState").getJSONObject("properties").getJSONObject("axis_revision").put("unsupported_keyword",true)
        assertThrows(IllegalArgumentException::class.java){EnergySchema(encoded(schema))}
    }
}
