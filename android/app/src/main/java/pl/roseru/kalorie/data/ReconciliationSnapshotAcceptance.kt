package pl.roseru.kalorie.data

import androidx.room.withTransaction
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*

internal data class SnapshotAcceptanceCapture(val lease:OwnerLease,val expected:AccountBindingEntity,
    val plan:ImportPlan,val run:ServerSnapshotRun,val pull:ReconciliationPull,val pages:List<ServerSnapshotPage>,
    val access:ServerSnapshotAccess?,val sources:List<ImportSource>,val known:List<ReconciliationEvidence>,
    val previous:List<ServerDiaryRecord>)

/** Validated immutable data, not credentials. Only the owning store can construct a prepared commit. */
class PreparedReconciliationSnapshot internal constructor(internal val captured:SnapshotAcceptanceCapture,
    internal val evidence:List<ReconciliationEvidence>,internal val sourceUpdates:List<ImportSource>,
    internal val groupsComplete:Boolean,internal val alreadyAccepted:Boolean) {
    val runId:String get()=captured.run.id
    override fun toString()="PreparedReconciliationSnapshot(redacted)"
}

internal class ReconciliationSnapshotAcceptance(private val store:ReconciliationStore) {
    private val db get()=store.db
    private val dao get()=store.dao
    private fun groups(sources:List<ImportSource>):List<List<String>> {
        val ids=sources.flatMap {source->val rows=JSONArray(source.outboxesJson)
            (0 until rows.length()).map {rows.getJSONObject(it)}.filter {
                it.optString("wireFormat") in setOf("sync-v1","sync-recovery-v1") && it.optInt("attempted")==1 && !it.isNull("wireJson")
            }.map {it.getString("operationId")} }.distinct()
        return ids.chunked(100).ifEmpty {listOf(emptyList())}
    }
    private fun accepted(known:List<ReconciliationEvidence>,run:String,access:ServerSnapshotAccess?)=
        known.any {(it.kind=="snapshot_acceptance" && it.identity==run) || (it.kind=="receipt_group" && it.runId==run) || it.kind=="entity:$run"} || access?.activeRunId==run

    suspend fun pending(lease:OwnerLease,expected:AccountBindingEntity,id:String):String?=db.withTransaction {
        val plan=store.plan(lease,expected,id);check(plan.approvedAt!=null)
        if(plan.state=="complete")return@withTransaction null
        val known=dao.evidence(id);val groups=groups(dao.sources(id))
        val done=known.filter {it.kind=="receipt_group"}.map {it.identity}.toSet()
        val index=groups.indices.firstOrNull {it.toString() !in done}?:groups.size
        val requested=if(index<groups.size)groups[index] else emptyList()
        val runs=db.snapshotDao().runs(lease.storageScope);val access=db.snapshotDao().access(lease.storageScope)
        val batches=dao.batches(id)
        for(pull in dao.pulls(id).asReversed().filter {it.groupIndex==index}) {
            if(pull.operationIdsJson!=StrictJson.canonical(JSONArray(requested)))continue
            val run=runs.firstOrNull {it.id==pull.runId}?:continue
            if(run.state!="complete" || run.accountId!=expected.accountId || run.accountGeneration!=expected.accountGeneration ||
                run.syncEpoch!=expected.syncEpoch || run.contextRevision!=expected.contextRevision || accepted(known,run.id,access))continue
            // Post-ACK read must be newer than every batch's captured pre-ACK snapshot.
            if(index==groups.size && batches.any {batch->runs.indexOfFirst {it.id==batch.snapshotRunId}.let {it<0 || runs.indexOf(run)>=it}})continue
            if(db.snapshotDao().pageCount(run.id)==run.pageCount)return@withTransaction run.id
        }
        null
    }
    suspend fun prepare(lease:OwnerLease,expected:AccountBindingEntity,id:String,runId:String):PreparedReconciliationSnapshot=withContext(Dispatchers.IO) {
        val captured=db.withTransaction {
            val plan=store.plan(lease,expected,id);check(plan.approvedAt!=null)
            val pull=checkNotNull(dao.pull(runId));check(pull.planId==id)
            val run=checkNotNull(db.snapshotDao().run(runId));check(run.state=="complete" && run.ownerScope==lease.storageScope &&
                run.accountId==expected.accountId && run.accountGeneration==expected.accountGeneration &&
                run.syncEpoch==expected.syncEpoch && run.contextRevision==expected.contextRevision)
            SnapshotAcceptanceCapture(lease,expected,plan,run,pull,db.snapshotDao().pages(runId),db.snapshotDao().access(lease.storageScope),
                dao.sources(id),dao.evidence(id),db.serverDiaryDao().records(lease.storageScope))
        }
        if(accepted(captured.known,runId,captured.access))return@withContext PreparedReconciliationSnapshot(captured,emptyList(),emptyList(),false,true)
        val copy=ServerDiaryProtocol(store.schema).read(expected.syncEpoch,captured.pages.map {ArchivedDiaryPage(it.queryJson,it.responseJson)})
        check(copy.checkpoint==captured.run.checkpoint && copy.timelineRevision.toLong()==captured.run.timelineRevision)
        val groups=groups(captured.sources);val pull=captured.pull
        val requested=JSONArray(pull.operationIdsJson).let {rows->(0 until rows.length()).map {rows.getString(it)}}
        require(pull.groupIndex<=groups.size && if(pull.groupIndex<groups.size)requested==groups[pull.groupIndex] else requested.isEmpty())
        val evidence=mutableListOf<ReconciliationEvidence>();val known=captured.known
        val originals=captured.sources.flatMap {source->JSONArray(source.outboxesJson).let {rows->
            (0 until rows.length()).map {rows.getJSONObject(it)} }}.associateBy {it.getString("operationId")}
        for(text in copy.receipts) {
            val receipt=StrictJson.read(text.toByteArray());val opId=receipt.getString("operation_id");check(opId in requested)
            val original=checkNotNull(originals[opId]);check(original.getString("ownerScope")==lease.storageScope)
            val wire=StrictJson.read(original.getString("wireJson").toByteArray())
            check(wire.getString("operation_id")==opId && wire.getString("entity_id")==receipt.getString("entity_id") &&
                wire.getString("sync_epoch")==receipt.getString("source_epoch"))
            known.firstOrNull {it.kind=="receipt" && it.identity==opId}?.let {check(it.json==text)}
            evidence+=ReconciliationEvidence(id,"receipt",opId,text,LegacyImportStore.digest(text),runId)
        }
        for(text in copy.mappings) {
            val mapping=StrictJson.read(text.toByteArray());val key=mapping.getString("source_epoch")+":"+mapping.getString("source_entity_id")
            known.firstOrNull {it.kind=="mapping" && it.identity==key}?.let {
                check(StrictJson.read(it.json.toByteArray()).getString("target_entity_id")==mapping.getString("target_entity_id"))}
            evidence+=ReconciliationEvidence(id,"mapping",key,text,LegacyImportStore.digest(text),runId)
        }
        for(entity in copy.entities) {
            val text=StrictJson.canonical(JSONObject().put("entity_id",entity.id).put("entity_type",entity.type).put("revision",entity.revision)
                .put("deleted",entity.deleted).put("payload",entity.payload?.let {StrictJson.read(it.toByteArray())}?:JSONObject.NULL))
            evidence+=ReconciliationEvidence(id,"entity:$runId",entity.id,text,LegacyImportStore.digest(text),runId)
        }
        evidence+=ReconciliationEvidence(id,"receipt_group",pull.groupIndex.toString(),pull.operationIdsJson,LegacyImportStore.digest(pull.operationIdsJson),runId)
        val marker=StrictJson.canonical(JSONObject().put("run_id",runId).put("checkpoint",copy.checkpoint)
            .put("pages",JSONArray(captured.pages.map {LegacyImportStore.digest(it.queryJson+"\n"+it.responseJson)})))
        evidence+=ReconciliationEvidence(id,"snapshot_acceptance",runId,marker,LegacyImportStore.digest(marker),runId)
        val done=(known+evidence).filter {it.kind=="receipt_group"}.map {it.identity}.toSet()
        val complete=groups.indices.all {it.toString() in done}
        val entities=copy.entities.associateBy {it.type to it.id}
        val updates=if(!complete)emptyList() else captured.sources.filter {it.operationId==null && it.metadataJson=="{}"}.map {row->
            val root=StrictJson.read(row.sourceJson.toByteArray());val sourceId=root.getString("wire_id")
            val target=entities[row.entityType to sourceId]
            val knownBefore=captured.previous.any {it.entityType==row.entityType && it.entityId==sourceId} || root.getInt("server_revision")>0
            val code=when {
                row.sourceEpoch==null->"legacy_import_after_reconciliation"
                row.sourceEpoch==expected.syncEpoch && knownBefore && (target==null || target.deleted)->"absent_same_epoch"
                row.sourceEpoch==expected.syncEpoch->"same_epoch_review"
                else->"epoch_recovery_review"
            }
            row.copy(state="decision",decisionCode=code)
        }
        PreparedReconciliationSnapshot(captured,evidence.toList(),updates,complete,false)
    }
    suspend fun apply(prepared:PreparedReconciliationSnapshot)=db.withTransaction {
        val c=prepared.captured;val plan=store.plan(c.lease,c.expected,c.plan.id)
        val run=db.snapshotDao().run(c.run.id);val pull=dao.pull(c.run.id);val known=dao.evidence(c.plan.id)
        check(run==c.run && pull==c.pull)
        // Idempotent saved result never republishes a historical active pointer.
        if(accepted(known,c.run.id,db.snapshotDao().access(c.lease.storageScope)))return@withTransaction
        check(!prepared.alreadyAccepted && plan==c.plan && db.snapshotDao().pages(c.run.id)==c.pages &&
            db.snapshotDao().access(c.lease.storageScope)==c.access && dao.sources(c.plan.id)==c.sources && known==c.known &&
            db.serverDiaryDao().records(c.lease.storageScope)==c.previous)
        for(row in prepared.evidence)dao.insert(row)
        for(row in prepared.sourceUpdates)dao.update(row)
        if(prepared.groupsComplete)dao.update(plan.copy(state="decisions"))
        db.snapshotDao().save(ServerSnapshotAccess(c.lease.storageScope,c.run.id,false))
    }
}
