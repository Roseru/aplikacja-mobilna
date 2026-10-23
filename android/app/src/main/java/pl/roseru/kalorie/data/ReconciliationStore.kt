package pl.roseru.kalorie.data

import androidx.room.withTransaction
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.time.Instant
import java.util.UUID

class ReconciliationProofException:IllegalStateException("Uzgodnienie wymaga aktualnej pełnej kopii i rozstrzygnięcia źródeł")

/** Full snapshots, receipts and user choices have a durable ledger independent of ordinary push. */
class ReconciliationStore(internal val db:CalorieDatabase,internal val schema:SyncWireSchema) {
    internal val dao get()=db.importDao()
    private val snapshots get()=ServerSnapshotStore(db,SnapshotProtocol(schema))
    internal suspend fun context(lease:OwnerLease,expected:AccountBindingEntity):AccountBindingEntity {
        LocalOwnerStore(db).requireCurrent(lease)
        val actual=checkNotNull(db.bootstrapDao().binding(lease.storageScope))
        if(actual!=expected || actual.ownerScope!=lease.storageScope)throw ImportContextChangedException()
        check(db.ownerDao().byScope(lease.storageScope)?.kind=="account")
        return actual
    }
    internal suspend fun plan(lease:OwnerLease,expected:AccountBindingEntity,id:String):ImportPlan {
        context(lease,expected);val plan=checkNotNull(dao.plan(id))
        check(plan.kind in setOf("reconcile_same_epoch","reconcile_epoch") && plan.targetScope==lease.storageScope &&
            plan.targetAccountId==expected.accountId && plan.wireContext==CanonicalMealRows.context(expected))
        return plan
    }
    suspend fun begin(lease:OwnerLease,expected:AccountBindingEntity):ImportProgress=withContext(Dispatchers.IO) {
        db.withTransaction {
            val binding=context(lease,expected);check(binding.requiresRecovery)
            val owner=checkNotNull(db.ownerDao().byScope(lease.storageScope))
            val captured=LegacyImportStore(db,schema).capture(lease.storageScope,true)
            val fingerprint=LegacyImportStore.digest(captured.joinToString("\n"){it.first+":"+it.second})
            val wireContext=CanonicalMealRows.context(binding)
            dao.plans(lease.storageScope).firstOrNull {it.kind.startsWith("reconcile_") && it.fingerprint==fingerprint && it.wireContext==wireContext}
                ?.let {return@withTransaction progress(it)}
            val changedEpoch=captured.any {entry->StrictJson.read(entry.second.toByteArray()).let {root->
                !root.isNull("wire_context") && StrictJson.read(root.getString("wire_context").toByteArray()).getString("sync_epoch")!=binding.syncEpoch}}
            val plan=ImportPlan(UUID.randomUUID().toString(),lease.storageScope,lease.storageScope,binding.accountId,
                checkNotNull(owner.issuer),checkNotNull(owner.subject),if(changedEpoch)"reconcile_epoch" else "reconcile_same_epoch",
                fingerprint,wireContext,Instant.now().toString())
            dao.insert(plan)
            val operationProofs=db.provedOperationResults(schema,lease.storageScope)
            captured.forEachIndexed {index,(type,json)->
                val root=StrictJson.read(json.toByteArray());val row=root.getJSONObject("row");val id=row.getString("id")
                val epoch=if(root.isNull("wire_context"))null else StrictJson.read(root.getString("wire_context").toByteArray()).getString("sync_epoch")
                val outboxes=root.getJSONArray("outboxes")
                val sourceOps=(0 until outboxes.length()).map {outboxes.getJSONObject(it)}.filter {
                    it.optString("wireFormat") in setOf("sync-v1","sync-recovery-v1") && !it.isNull("wireJson") && it.optInt("attempted")==1 }
                val operation=sourceOps.lastOrNull {op->StrictJson.read(op.getString("wireJson").toByteArray()).let {
                    it.getString("sync_epoch")==epoch && it.getString("entity_id")==root.getString("wire_id")}}
                val proved=operation?.getString("operationId")?.let {operationProofs[it]}
                val sourceRevision=if(operation==null)root.getInt("server_revision").takeIf {it>0}
                    else proved?.takeIf {it.status=="accepted"}?.revision
                dao.insert(ImportSource(plan.id,type,id,index,json,LegacyImportStore.digest(json),StrictJson.canonical(outboxes),id,root.getString("wire_id"),
                    epoch,sourceRevision,operation?.getString("operationId"),
                    state="decision",decisionCode=if(epoch==null)"legacy_import_after_reconciliation" else "full_snapshot_required"))
            }
            progress(plan)
        }
    }
    suspend fun approve(lease:OwnerLease,expected:AccountBindingEntity,id:String,accountId:String,issuer:String,subject:String):ImportProgress=db.withTransaction {
        val plan=plan(lease,expected,id);require(plan.targetAccountId==accountId && plan.issuer==issuer && plan.subject==subject)
        if(plan.approvedAt!=null)return@withTransaction progress(plan)
        val approved=plan.copy(approvedAt=Instant.now().toString(),state="snapshots")
        dao.update(approved);progress(approved)
    }
    internal suspend fun groups(plan:ImportPlan):List<List<String>> {
        val ids=dao.sources(plan.id).flatMap {source->val rows=JSONArray(source.outboxesJson)
            (0 until rows.length()).map {rows.getJSONObject(it)}.filter {
                it.optString("wireFormat") in setOf("sync-v1","sync-recovery-v1") && it.optInt("attempted")==1 && !it.isNull("wireJson")
            }.map {it.getString("operationId")} }.distinct()
        return ids.chunked(100).ifEmpty {listOf(emptyList())}
    }
    internal suspend fun groupsComplete(plan:ImportPlan):Boolean {
        val evidence=dao.evidence(plan.id).filter {it.kind=="receipt_group"}.associateBy {it.identity}
        return groups(plan).indices.all {it.toString() in evidence}
    }
    /** One persisted group at a time; completing group zero does not complete a larger plan. */
    suspend fun nextSnapshot(lease:OwnerLease,expected:AccountBindingEntity,id:String):SnapshotRequest?=db.withTransaction {
        val plan=plan(lease,expected,id);check(plan.approvedAt!=null)
        val groups=groups(plan);val done=dao.evidence(id).filter {it.kind=="receipt_group"}.map {it.identity}.toSet()
        val index=groups.indices.firstOrNull {it.toString() !in done}
        if(index!=null)return@withTransaction snapshots.begin(lease,groups[index],id,index)
        // A different-device ACK target must be proven by a newer typed snapshot before local ACK.
        val batches=dao.batches(id)
        val active=snapshots.active(lease)
        if(batches.any {it.state=="awaiting_snapshot"} ||
            (batches.any {it.state=="complete"} && active?.id in batches.map {it.snapshotRunId}))
            return@withTransaction snapshots.begin(lease,emptyList(),id,groups.size)
        null
    }
    /** Parse and semantically validate every archived page before publishing typed evidence. */
    suspend fun acceptCompletedSnapshot(lease:OwnerLease,expected:AccountBindingEntity,id:String,runId:String)=withContext(Dispatchers.IO) {
        val source=db.withTransaction {
            val plan=plan(lease,expected,id);check(plan.approvedAt!=null)
            val pull=checkNotNull(dao.pull(runId));check(pull.planId==id)
            val run=checkNotNull(db.snapshotDao().run(runId));check(run.state=="complete" && run.ownerScope==lease.storageScope &&
                run.accountId==expected.accountId && run.accountGeneration==expected.accountGeneration &&
                run.syncEpoch==expected.syncEpoch && run.contextRevision==expected.contextRevision)
            if(dao.evidence(id).any {it.kind=="receipt_group" && it.runId==runId})return@withTransaction null
            Triple(plan,run,db.snapshotDao().pages(runId)) to db.snapshotDao().access(lease.storageScope)
        } ?: return@withContext
        val (captured,access)=source
        val copy=ServerDiaryProtocol(schema).read(expected.syncEpoch,captured.third.map {ArchivedDiaryPage(it.queryJson,it.responseJson)})
        check(copy.checkpoint==captured.second.checkpoint && copy.timelineRevision.toLong()==captured.second.timelineRevision)
        db.withTransaction {
            check(plan(lease,expected,id)==captured.first && db.snapshotDao().run(runId)==captured.second &&
                db.snapshotDao().access(lease.storageScope)==access && db.snapshotDao().pages(runId)==captured.third)
            val pull=checkNotNull(dao.pull(runId));val groups=groups(captured.first)
            val requested=JSONArray(pull.operationIdsJson).let {rows->(0 until rows.length()).map {rows.getString(it)}}
            require(if(pull.groupIndex<groups.size)requested==groups[pull.groupIndex] else requested.isEmpty())
            val known=dao.evidence(id)
            val sources=dao.sources(id)
            val originals=sources.flatMap {source->JSONArray(source.outboxesJson).let {rows->
                (0 until rows.length()).map {rows.getJSONObject(it)} }}.associateBy {it.getString("operationId")}
            for(text in copy.receipts) {
                val receipt=StrictJson.read(text.toByteArray());val opId=receipt.getString("operation_id")
                check(opId in requested)
                val original=checkNotNull(originals[opId]);check(original.getString("ownerScope")==lease.storageScope)
                val wire=StrictJson.read(original.getString("wireJson").toByteArray())
                check(wire.getString("operation_id")==opId && wire.getString("entity_id")==receipt.getString("entity_id") &&
                    wire.getString("sync_epoch")==receipt.getString("source_epoch"))
                val old=known.firstOrNull {it.kind=="receipt" && it.identity==opId}
                if(old!=null)check(old.json==text)
                dao.insert(ReconciliationEvidence(id,"receipt",opId,text,LegacyImportStore.digest(text),runId))
            }
            for(text in copy.mappings) {
                val mapping=StrictJson.read(text.toByteArray());val key=mapping.getString("source_epoch")+":"+mapping.getString("source_entity_id")
                val old=known.firstOrNull {it.kind=="mapping" && it.identity==key}
                if(old!=null)check(StrictJson.read(old.json.toByteArray()).getString("target_entity_id")==mapping.getString("target_entity_id"))
                // Historical mappings reserve an identity even after target deletion/retention.
                // Archive them here. A selected operation must separately prove a live typed target;
                // an unrelated historical reservation must not prevent completing a full read.
                // A later observation is separately archived rather than overwriting old evidence.
                dao.insert(ReconciliationEvidence(id,"mapping",key,text,LegacyImportStore.digest(text),runId))
            }
            for(entity in copy.entities) {
                val text=StrictJson.canonical(JSONObject().put("entity_id",entity.id).put("entity_type",entity.type).put("revision",entity.revision)
                    .put("deleted",entity.deleted).put("payload",entity.payload?.let {StrictJson.read(it.toByteArray())} ?: JSONObject.NULL))
                dao.insert(ReconciliationEvidence(id,"entity:$runId",entity.id,text,LegacyImportStore.digest(text),runId))
            }
            dao.insert(ReconciliationEvidence(id,"receipt_group",pull.groupIndex.toString(),pull.operationIdsJson,
                LegacyImportStore.digest(pull.operationIdsJson),runId))
            val plan=captured.first
            if(groupsComplete(plan)) {
                val entities=copy.entities.associateBy {it.type to it.id}
                val previous=db.serverDiaryDao().records(lease.storageScope)
                for(row in sources.filter {it.operationId==null}) {
                    val root=StrictJson.read(row.sourceJson.toByteArray());val sourceId=root.getString("wire_id")
                    val target=entities[row.entityType to sourceId]
                    val knownBefore=previous.any {it.entityType==row.entityType && it.entityId==sourceId} || root.getInt("server_revision")>0
                    val code=when {
                        row.sourceEpoch==null->"legacy_import_after_reconciliation"
                        row.sourceEpoch==expected.syncEpoch && knownBefore && (target==null || target.deleted)->"absent_same_epoch"
                        row.sourceEpoch==expected.syncEpoch->"same_epoch_review"
                        else->"epoch_recovery_review"
                    }
                    if(row.metadataJson=="{}")dao.update(row.copy(state="decision",decisionCode=code))
                }
                dao.update(plan.copy(state="decisions"))
            }
            db.snapshotDao().save(ServerSnapshotAccess(lease.storageScope,runId,false))
        }
    }
    suspend fun decide(lease:OwnerLease,expected:AccountBindingEntity,id:String,type:String,sourceId:String,sourceHash:String,choiceJson:String)=withContext(Dispatchers.IO) {
        val choice=StrictJson.read(choiceJson.toByteArray());val canonical=StrictJson.canonical(choice)
        require(choice.getString("choice") in setOf("preserve_local","accept_server","recreate_missing","resolve_existing","new_goal_decision","replay_original"))
        db.withTransaction {
            val plan=plan(lease,expected,id);check(plan.approvedAt!=null && groupsComplete(plan))
            val row=checkNotNull(dao.source(id,type,sourceId));check(row.sourceHash==sourceHash)
            if(row.operationId!=null) {
                check(db.dao().operation(row.operationId)?.status in setOf("acked","conflict","rejected"))
                require(choice.getString("choice") in setOf("preserve_local","accept_server"))
            }
            if(row.decisionCode=="absent_same_epoch")require(choice.getString("choice") in setOf("preserve_local","accept_server"))
            if(row.sourceEpoch==expected.syncEpoch)require(choice.getString("choice") in setOf("preserve_local","accept_server","replay_original"))
            else require(choice.getString("choice")!="replay_original")
            if(row.sourceEpoch==null)require(choice.getString("choice")=="preserve_local")
            dao.insert(ImportDecision(UUID.randomUUID().toString(),id,type,sourceId,sourceHash,canonical,Instant.now().toString()))
            val local=choice.getString("choice")=="preserve_local"
            val accept=choice.getString("choice")=="accept_server"
            val target=if(choice.getString("choice") in setOf("recreate_missing","new_goal_decision")) UUID.randomUUID().toString()
                else if(choice.getString("choice")=="resolve_existing")choice.getString("target_id") else row.wireId
            dao.update(row.copy(wireId=target,metadataJson=canonical,state=if(local)"retained" else if(accept)"accept_server" else "approved_source",decisionCode=null))
            progress(plan)
        }
    }
    suspend fun status(lease:OwnerLease,expected:AccountBindingEntity,id:String):ImportProgress=db.withTransaction {progress(plan(lease,expected,id))}
    internal suspend fun progress(plan:ImportPlan):ImportProgress {
        val rows=dao.sources(plan.id)
        return ImportProgress(plan.id,plan.targetAccountId,plan.issuer,plan.subject,plan.state,rows.size,rows.count {it.state=="queued"},
            rows.count {it.state=="acked"},rows.count {it.state=="retained"},rows.filter {it.state=="decision"}.map {
                ImportIssue(it.entityType,it.sourceId,it.decisionCode ?: "decision_required")},
            pending=rows.count {it.state=="approved_source"},waiting=rows.count {it.state=="awaiting_snapshot"})
    }
    suspend fun finish(lease:OwnerLease,expected:AccountBindingEntity,id:String):ServerDiaryApplication = ReconciliationFinishStore(this).finish(lease,expected,id)
    suspend fun preparePush(lease:OwnerLease,expected:AccountBindingEntity,id:String):ReconciliationPushRequest? = ReconciliationPushStore(this).prepare(lease,expected,id)
    suspend fun requireCurrent(request:ReconciliationPushRequest)=ReconciliationPushStore(this).requireCurrent(request)
    suspend fun markAttempted(request:ReconciliationPushRequest,nowMillis:Long=System.currentTimeMillis())=ReconciliationPushStore(this).markAttempted(request,nowMillis)
    suspend fun defer(request:ReconciliationPushRequest,retryAtMillis:Long)=ReconciliationPushStore(this).defer(request,retryAtMillis)
    suspend fun prepareAck(request:ReconciliationPushRequest,httpStatus:Int,bytes:ByteArray):PreparedReconciliationAck=ReconciliationPushStore(this).prepareAck(request,httpStatus,bytes)
    suspend fun applyAck(prepared:PreparedReconciliationAck):ReconciliationAckResult=ReconciliationPushStore(this).applyAck(prepared)
    internal suspend fun latestCopy(lease:OwnerLease,expected:AccountBindingEntity,id:String):Pair<ServerSnapshotRun,ServerDiarySnapshot> {
        val plan=plan(lease,expected,id);check(groupsComplete(plan))
        val run=checkNotNull(snapshots.active(lease));val pull=checkNotNull(dao.pull(run.id));check(pull.planId==id)
        val pages=db.snapshotDao().pages(run.id)
        return run to ServerDiaryProtocol(schema).read(expected.syncEpoch,pages.map {ArchivedDiaryPage(it.queryJson,it.responseJson)})
    }
}
