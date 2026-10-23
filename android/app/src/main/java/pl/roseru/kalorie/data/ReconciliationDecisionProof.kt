package pl.roseru.kalorie.data

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.ServerDiarySnapshot

class ReconciliationDecisionProofChangedException:ReconciliationProofException()

/** A decision authorizes one observed version, not an arbitrary later snapshot of this source. */
internal object ReconciliationDecisionProof {
    fun attach(choice:JSONObject,source:ImportSource,runId:String,copy:ServerDiarySnapshot):String {
        val observed=observation(source,choice,copy)
        val proof=JSONObject().put("version",1).put("run_id",runId).put("source_hash",source.sourceHash)
            .put("observation",observed).put("sha256",LegacyImportStore.digest(StrictJson.canonical(observed)))
        choice.put("decision_proof",proof)
        return StrictJson.canonical(choice)
    }
    fun matches(source:ImportSource,copy:ServerDiarySnapshot):Boolean=try {
        val choice=StrictJson.read(source.metadataJson.toByteArray())
        val proof=choice.getJSONObject("decision_proof")
        val saved=StrictJson.canonical(proof.getJSONObject("observation"))
        proof.getInt("version")==1 && proof.getString("source_hash")==source.sourceHash &&
            proof.getString("sha256")==LegacyImportStore.digest(saved) &&
            saved==StrictJson.canonical(observation(source,choice,copy))
    } catch(_:Exception){false}
    private fun observation(source:ImportSource,choice:JSONObject,copy:ServerDiarySnapshot):JSONObject {
        val original=StrictJson.read(source.sourceJson.toByteArray()).getString("wire_id")
        val mapping=copy.mappings.map {StrictJson.read(it.toByteArray())}.singleOrNull {
            it.getString("source_epoch")==source.sourceEpoch && it.getString("source_entity_id")==original}
        val target=if(choice.getString("choice")=="resolve_existing")choice.getString("target_id")
            else mapping?.getString("target_entity_id") ?: original
        val entity=copy.entities.singleOrNull {it.type==source.entityType && it.id==target}
        return JSONObject().put("entity_type",source.entityType).put("entity_id",target)
            .put("state",if(entity==null)"absent" else if(entity.deleted)"deleted" else "present")
            .put("revision",entity?.revision ?: JSONObject.NULL)
            .put("payload",entity?.payload?.let {StrictJson.read(it.toByteArray())} ?: JSONObject.NULL)
    }
}
