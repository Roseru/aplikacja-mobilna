package pl.roseru.kalorie.data

import androidx.room.withTransaction
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.time.Instant
import java.util.UUID

class ReconciliationPushRequest internal constructor(val id:String,internal val lease:OwnerLease,
    internal val binding:AccountBindingEntity,val planId:String,val batch:PushBatch,
    internal val row:ReconciliationBatch,internal val operations:List<OutboxEntity>) {
    val needsAckRevalidation:Boolean get()=row.state=="awaiting_snapshot"
    fun savedResponse():ByteArray?=row.responseJson?.toByteArray(Charsets.UTF_8)
    override fun toString()="ReconciliationPushRequest(redacted)"
}
data class ReconciliationAckResult(val acknowledged:Int,val refused:Int,val awaitingSnapshot:Boolean=false,val replay:Boolean=false)
class PreparedReconciliationAck internal constructor(internal val request:ReconciliationPushRequest,
    internal val original:ReconciliationBatch,internal val response:PushReceipt,internal val sources:List<ImportSource>,
    internal val activeRun:ServerSnapshotRun,internal val copy:ServerDiarySnapshot,
    val result:ReconciliationAckResult) {
    override fun toString()="PreparedReconciliationAck(redacted)"
}

/** Transport-independent recovery envelope. Existing SessionController owns authentication and HTTP. */
internal class ReconciliationPushStore(private val owner:ReconciliationStore) {
    private val db get()=owner.db
    private val schema get()=owner.schema
    private val dao get()=owner.dao
    private val ordinary get()=PushProtocol(schema)
    private val recovery get()=RecoveryProtocol(schema)
    suspend fun prepare(lease:OwnerLease,expected:AccountBindingEntity,id:String):ReconciliationPushRequest?=withContext(Dispatchers.IO) {
        db.withTransaction {
            val plan=owner.plan(lease,expected,id);check(plan.approvedAt!=null && owner.groupsComplete(plan))
            dao.batches(id).firstOrNull {it.state in setOf("pending","awaiting_snapshot")}?.let {return@withTransaction open(lease,expected,id,it.id)}
            val (run,copy)=owner.latestCopy(lease,expected,id)
            val sources=dao.sources(id)
            val source=sources.firstOrNull {it.state=="approved_source"} ?: return@withTransaction null
            sources.filter {it.state=="approved_source"}.forEach {owner.requireDecisionProof(it,copy)}
            val choice=StrictJson.read(source.metadataJson.toByteArray()).getString("choice")
            if(choice=="replay_original")return@withTransaction replay(lease,expected,plan,run,source,sources)
            check(source.sourceEpoch!=null && source.sourceEpoch!=expected.syncEpoch)
            val root=StrictJson.read(source.sourceJson.toByteArray())
            val oldId=root.getString("wire_id")
            val decision=StrictJson.read(source.metadataJson.toByteArray())
            val original=source.sourceOperationId?.let {db.dao().operation(it)}
            if(original!=null) {
                check(original.ownerScope==lease.storageScope && original.entityType==source.entityType && original.entityId==oldId)
                val wire=StrictJson.read(checkNotNull(original.wireJson).toByteArray())
                check(wire.getString("sync_epoch")==source.sourceEpoch && wire.getString("action")=="upsert")
            }
            val localProof=source.sourceOperationId?.let {db.provedOperationResults(schema,lease.storageScope)[it]}
            if(localProof!=null)check(localProof.status=="accepted" && localProof.entityId==oldId && localProof.epoch==source.sourceEpoch)
            if(original!=null)check(original.status !in setOf("conflict","rejected"))
            val receipt=dao.evidence(id).firstOrNull {it.kind=="receipt" && it.identity==source.sourceOperationId}
                ?.let {StrictJson.read(it.json.toByteArray())}
            if(receipt!=null) {
                check(receipt.getString("source_epoch")==source.sourceEpoch && receipt.getString("entity_id")==oldId && receipt.getString("status")=="accepted")
                if(localProof!=null)check(receipt.getInt("revision")==localProof.revision)
                val wire=original?.wireJson?.let {StrictJson.read(it.toByteArray())}
                if(wire!=null && !wire.has("recovery")) {
                    val base=if(wire.isNull("base_revision"))0L else wire.getLong("base_revision")
                    check(receipt.getLong("revision")==base+1) // Validate the received receipt against its own frozen operation.
                }
            }
            // Old milestone plans may contain a projection revision paired with an uncertain update.
            // Preserve that original evidence but use only a bound receipt/response for this operation.
            val sourceRevision=if(source.sourceOperationId==null)source.sourceRevision
                else if(receipt!=null)receipt.getInt("revision") else localProof?.revision
            val proposed=source.wireId
            val target=copy.entities.singleOrNull {it.id==proposed}
            val mapping=copy.mappings.map {StrictJson.read(it.toByteArray())}.singleOrNull {
                it.getString("source_epoch")==source.sourceEpoch && it.getString("source_entity_id")==oldId }
            if(mapping!=null) {
                val mappedTarget=copy.entities.singleOrNull {it.id==mapping.getString("target_entity_id")}
                // Deletion/retention keeps the mapping reservation; it is not permission for another recreate.
                check(mappedTarget!=null && !mappedTarget.deleted && mappedTarget.type==source.entityType &&
                    mappedTarget.revision==mapping.getInt("target_revision"))
            }
            val payloadText=when(val supplied=decision.opt("payload")) {
                is JSONObject->StrictJson.canonical(supplied)
                is String->StrictJson.canonical(StrictJson.read(supplied.toByteArray()))
                else->if(root.isNull("canonical_payload"))throw ReconciliationProofException() else root.getString("canonical_payload")
            }
            val payload=remapDependencies(source,payloadText,sources)
            val resolve=choice=="resolve_existing"
            val base=if(resolve)checkNotNull(target).also {check(!it.deleted && it.type==source.entityType)}.revision else null
            if(!resolve) {
                check(choice in setOf("recreate_missing","new_goal_decision") && proposed!=oldId && target==null)
                check(copy.entities.none {it.id==oldId}) // A known tombstone/reservation is not recreation permission.
            }
            if(source.entityType=="goal") {
                val value=StrictJson.read(payload.toByteArray())
                val mapped=mapping!=null && target!=null && !target.deleted && target.type=="goal" &&
                    target.id==mapping.getString("target_entity_id") && target.revision==mapping.getInt("target_revision") && target.payload==payload
                if(resolve)check(mapped) // Goals cannot be ordinary updates.
                if(!mapped)check(choice=="new_goal_decision" && decision.has("payload") &&
                    value.getInt("timeline_base_revision")==copy.timelineRevision)
            }
            val sourceMeta=StrictJson.canonical(JSONObject().put("source_epoch",source.sourceEpoch).put("source_entity_id",oldId)
                .put("source_revision",sourceRevision ?: JSONObject.NULL).put("source_operation_id",source.sourceOperationId ?: JSONObject.NULL)
                .put("decision",if(resolve)"resolve_existing" else "recreate_missing"))
            val opId=UUID.randomUUID().toString()
            val operation=recovery.operation(opId,source.entityType,proposed,expected.syncEpoch,base,payload,sourceMeta)
            val batch=recovery.prepare(expected.syncEpoch,checkNotNull(run.checkpoint),listOf(operation)).withScope(SyncProtocolScope.parse(run.protocolScope))
            val outbox=OutboxEntity(opId,lease.storageScope,source.entityType,proposed,"upsert",base,payload,Instant.now().toString(),
                "recovery_pending","sync-recovery-v1",operation,plan.wireContext,true)
            val envelope=ReconciliationBatch(UUID.randomUUID().toString(),id,"epoch_recovery",plan.wireContext,run.id,
                batch.canonical,batch.sha256,null,Instant.now().toString(),protocolScope=batch.protocolScope.installationId)
            db.dao().enqueue(outbox);dao.insert(envelope)
            dao.update(source.copy(state="queued",operationId=opId,appliedPayload=payload))
            ReconciliationPushRequest(envelope.id,lease,expected,id,batch,envelope,listOf(outbox))
        }
    }
    private suspend fun replay(lease:OwnerLease,expected:AccountBindingEntity,plan:ImportPlan,run:ServerSnapshotRun,
        source:ImportSource,sources:List<ImportSource>):ReconciliationPushRequest? {
        check(source.sourceEpoch==expected.syncEpoch)
        val originals=org.json.JSONArray(source.outboxesJson)
        val candidates=(0 until originals.length()).map {originals.getJSONObject(it)}.filter {
            it.optString("wireFormat")=="sync-v1" && !it.isNull("wireJson") &&
                it.optString("status") !in setOf("acked","superseded","local_only") }
        if(candidates.isEmpty())throw ReconciliationProofException()
        val first=candidates.first();val opId=first.getString("operationId")
        val original=db.pushDao().pending(lease.storageScope).firstOrNull {row->
            ordinary.restore(row.requestJson.toByteArray()).json().getJSONArray("operations").let {ops->
                (0 until ops.length()).any {ops.getJSONObject(it).getString("operation_id")==opId} } }
        val operationTexts=if(original==null)listOf(first.getString("wireJson")) else {
            val old=ordinary.restore(original.requestJson.toByteArray());check(old.sha256==original.requestHash)
            val ops=old.json().getJSONArray("operations")
            (0 until ops.length()).map {StrictJson.canonical(ops.getJSONObject(it))}.filter {text->
                val op=StrictJson.read(text.toByteArray())
                val match=sources.singleOrNull {it.entityType==op.getString("entity_type") &&
                    StrictJson.read(it.sourceJson.toByteArray()).getString("wire_id")==op.getString("entity_id")}
                match?.state=="approved_source" && StrictJson.read(match.metadataJson.toByteArray()).optString("choice")=="replay_original"
            }
        }
        if(operationTexts.isEmpty())return null
        val batch=ordinary.prepare(expected.syncEpoch,checkNotNull(run.checkpoint),operationTexts).withScope(SyncProtocolScope.parse(run.protocolScope))
        val wire=batch.json().getJSONArray("operations")
        val operations=(0 until wire.length()).map {i->
            val op=wire.getJSONObject(i);val row=checkNotNull(db.dao().operation(op.getString("operation_id")))
            check(row.ownerScope==lease.storageScope && row.wireFormat=="sync-v1" && row.wireJson==StrictJson.canonical(op) &&
                op.getString("sync_epoch")==expected.syncEpoch)
            val old=StrictJson.read(checkNotNull(row.wireContext).toByteArray());check(old.getString("account_id")==expected.accountId)
            row.copy(attempted=true).also {db.dao().updateOperation(it)}
        }
        val envelope=ReconciliationBatch(UUID.randomUUID().toString(),plan.id,"checkpoint_replay",plan.wireContext,run.id,
            batch.canonical,batch.sha256,original?.id,Instant.now().toString(),protocolScope=batch.protocolScope.installationId)
        dao.insert(envelope)
        for(row in operations) {
            val match=sources.single {it.entityType==row.entityType && StrictJson.read(it.sourceJson.toByteArray()).getString("wire_id")==row.entityId}
            dao.update(match.copy(state="queued",operationId=row.operationId,appliedPayload=row.payload.takeUnless {it=="null"}))
        }
        return ReconciliationPushRequest(envelope.id,lease,expected,plan.id,batch,envelope,operations)
    }
    /** New dependent operations may use confirmed aliases; old wire bytes are never rewritten. */
    private fun remapDependencies(source:ImportSource,text:String,sources:List<ImportSource>):String {
        val value=StrictJson.read(text.toByteArray())
        val field=when(source.entityType){"meal"->"goal_id";"goal"->"correction_of";else->return text}
        if(value.isNull(field))return text
        val id=value.getString(field)
        val parent=sources.singleOrNull {it.entityType=="goal" && StrictJson.read(it.sourceJson.toByteArray()).getString("wire_id")==id} ?:return text
        check(parent.state=="acked")
        value.put(field,parent.wireId)
        return StrictJson.canonical(value)
    }
    suspend fun open(lease:OwnerLease,expected:AccountBindingEntity,planId:String,id:String):ReconciliationPushRequest=db.withTransaction {
        owner.plan(lease,expected,planId)
        val row=checkNotNull(dao.batch(id));check(row.planId==planId && row.wireContext==CanonicalMealRows.context(expected))
        val batch=(if(row.kind=="epoch_recovery")recovery.restore(row.requestJson.toByteArray()) else ordinary.restore(row.requestJson.toByteArray()))
            .withScope(SyncProtocolScope.parse(row.protocolScope))
        check(batch.sha256==row.requestHash)
        check(db.snapshotDao().run(row.snapshotRunId)?.protocolScope==row.protocolScope)
        val wire=batch.json().getJSONArray("operations")
        val operations=(0 until wire.length()).map {i->val op=wire.getJSONObject(i)
            checkNotNull(db.dao().operation(op.getString("operation_id"))).also {outbox->
                check(outbox.ownerScope==lease.storageScope && outbox.attempted && outbox.wireJson==StrictJson.canonical(op))}}
        ReconciliationPushRequest(id,lease,expected,planId,batch,row,operations)
    }
    private suspend fun current(request:ReconciliationPushRequest):ReconciliationBatch {
        owner.plan(request.lease,request.binding,request.planId)
        val row=checkNotNull(dao.batch(request.id))
        check(row.copy(attempted=request.row.attempted,responseJson=request.row.responseJson,state=request.row.state,retryAtMillis=request.row.retryAtMillis)==request.row)
        check(row.protocolScope==request.batch.protocolScope.installationId && db.snapshotDao().run(row.snapshotRunId)?.protocolScope==row.protocolScope)
        request.operations.forEach {old->check(db.dao().operation(old.operationId)?.copy(status=old.status)==old)}
        return row
    }
    suspend fun requireCurrent(request:ReconciliationPushRequest)=db.withTransaction {
        val row=current(request);check(row.state=="pending" && row.responseJson==null)
    }
    suspend fun markAttempted(request:ReconciliationPushRequest,nowMillis:Long=System.currentTimeMillis())=db.withTransaction {
        val row=current(request);check(row.state=="pending" && row.responseJson==null && row.retryAtMillis<=nowMillis)
        dao.update(row.copy(attempted=true))
    }
    suspend fun defer(request:ReconciliationPushRequest,retryAtMillis:Long)=db.withTransaction {
        val row=current(request);check(row.state=="pending" && row.attempted && retryAtMillis>=row.retryAtMillis)
        dao.update(row.copy(retryAtMillis=retryAtMillis))
    }
    suspend fun prepareAck(request:ReconciliationPushRequest,httpStatus:Int,bytes:ByteArray):PreparedReconciliationAck=withContext(Dispatchers.IO) {
        // No database mutation precedes complete structural, ordering, source and result validation.
        val receipt=if(request.row.kind=="epoch_recovery")recovery.response(request.batch,httpStatus,bytes) else ordinary.response(request.batch,httpStatus,bytes)
        val captured=db.withTransaction {
            val row=current(request);check(row.attempted)
            val (run,copy)=owner.latestCopy(request.lease,request.binding,request.planId)
            Triple(row,dao.sources(request.planId),run to copy)
        }
        val (row,sources,copyPair)=captured
        val results=receipt.json().getJSONArray("results")
        if(row.state=="complete") {
            check(sameDecision(request.batch,checkNotNull(row.responseJson),receipt.canonical,row.kind))
            return@withContext PreparedReconciliationAck(request,row,receipt,sources,copyPair.first,copyPair.second,
                ReconciliationAckResult(0,0,replay=true))
        }
        check(row.state in setOf("pending","awaiting_snapshot"))
        if(row.responseJson!=null)check(sameDecision(request.batch,row.responseJson,receipt.canonical,row.kind))
        var acknowledged=0;var refused=0;var needsSnapshot=false
        request.operations.forEachIndexed {index,operation->
            val source=sources.single {it.operationId==operation.operationId}
            check(source.state=="queued")
            val outcome=results.getJSONObject(index)
            if(outcome.getString("status") in setOf("accepted","already_applied")) {
                acknowledged++
                if(row.kind=="epoch_recovery") {
                    val mapping=outcome.getJSONObject("recovery_mapping")
                    val targetId=mapping.getString("target_entity_id")
                    val prior=dao.evidence(request.planId).firstOrNull {it.kind=="mapping" &&
                        it.identity==source.sourceEpoch+":"+StrictJson.read(source.sourceJson.toByteArray()).getString("wire_id")}
                    if(prior!=null)check(StrictJson.read(prior.json.toByteArray()).getString("target_entity_id")==targetId)
                    if(targetId!=operation.entityId) {
                        val target=copyPair.second.entities.singleOrNull {it.id==targetId}
                        val observed=copyPair.second.mappings.map {StrictJson.read(it.toByteArray())}.singleOrNull {
                            it.getString("source_epoch")==mapping.getString("source_epoch") &&
                                it.getString("source_entity_id")==mapping.getString("source_entity_id")}
                        if(target==null || observed==null)needsSnapshot=true
                        else check(!target.deleted && target.type==operation.entityType && target.payload==operation.payload &&
                            observed.getString("target_entity_id")==targetId && observed.getInt("target_revision")==target.revision &&
                            target.revision>=mapping.getInt("target_revision"))
                    }
                }
            } else refused++
        }
        PreparedReconciliationAck(request,row,receipt,sources,copyPair.first,copyPair.second,
            ReconciliationAckResult(if(needsSnapshot)0 else acknowledged,if(needsSnapshot)0 else refused,needsSnapshot))
    }
    private fun sameDecision(batch:PushBatch,first:String,next:String,kind:String):Boolean {
        if(kind!="epoch_recovery")return ordinary.sameDecision(batch,ordinary.response(batch,200,first.toByteArray()),ordinary.response(batch,200,next.toByteArray()))
        val a=recovery.response(batch,200,first.toByteArray()).json().getJSONArray("results")
        val b=recovery.response(batch,200,next.toByteArray()).json().getJSONArray("results")
        return (0 until a.length()).all {i->
            val old=a.getJSONObject(i);val fresh=b.getJSONObject(i)
            if(old.getString("status") in setOf("accepted","already_applied") && fresh.getString("status") in setOf("accepted","already_applied")) {
                old.put("status","accepted");fresh.put("status","accepted")
                val x=old.getJSONObject("recovery_mapping");val y=fresh.getJSONObject("recovery_mapping")
                if(y.getInt("target_revision")<x.getInt("target_revision"))return@all false
                y.put("target_revision",x.getInt("target_revision"))
            }
            StrictJson.canonical(old)==StrictJson.canonical(fresh)
        }
    }
    suspend fun applyAck(prepared:PreparedReconciliationAck):ReconciliationAckResult=db.withTransaction {
        val request=prepared.request;val row=current(request)
        if(row.state=="complete") {
            check(sameDecision(request.batch,checkNotNull(row.responseJson),prepared.response.canonical,row.kind))
            return@withTransaction prepared.result.copy(acknowledged=0,refused=0,replay=true)
        }
        check(row==prepared.original && dao.sources(request.planId)==prepared.sources)
        check(owner.latestCopy(request.lease,request.binding,request.planId).first==prepared.activeRun)
        if(prepared.result.awaitingSnapshot) {
            dao.update(row.copy(responseJson=prepared.response.canonical,state="awaiting_snapshot"))
            return@withTransaction prepared.result
        }
        val results=prepared.response.json().getJSONArray("results")
        request.operations.forEachIndexed {index,operation->
            val source=prepared.sources.single {it.operationId==operation.operationId}
            val outcome=results.getJSONObject(index);val accepted=outcome.getString("status") in setOf("accepted","already_applied")
            val target=if(accepted && row.kind=="epoch_recovery")outcome.getJSONObject("recovery_mapping").getString("target_entity_id") else source.wireId
            if(accepted && row.kind=="epoch_recovery") {
                val mapping=StrictJson.canonical(outcome.getJSONObject("recovery_mapping"))
                dao.insert(ReconciliationEvidence(request.planId,"ack_mapping",operation.operationId,mapping,LegacyImportStore.digest(mapping),row.snapshotRunId))
            }
            val resultJson=StrictJson.canonical(outcome)
            dao.insert(ReconciliationEvidence(request.planId,"ack_result",operation.operationId,resultJson,LegacyImportStore.digest(resultJson),row.snapshotRunId))
            db.dao().updateOperation(operation.copy(status=if(accepted)"acked" else outcome.getString("status")))
            val root=StrictJson.read(source.sourceJson.toByteArray())
            val originals=root.getJSONArray("outboxes")
            val laterOperation=(0 until originals.length()).map {originals.getJSONObject(it)}.any {
                it.getString("operationId")!=operation.operationId && it.getString("wireFormat")=="sync-v1" &&
                    it.getString("status") !in setOf("acked","superseded","local_only") }
            val currentPayload=if(root.isNull("canonical_payload"))null else root.getString("canonical_payload")
            val localDeleted=root.getJSONObject("row").optBoolean("missingProjection",false) ||
                root.getJSONObject("row").optInt("deleted",0)==1 || root.getJSONObject("row").optBoolean("deleted",false)
            val laterIntent=accepted && row.kind=="checkpoint_replay" && (laterOperation ||
                (operation.action=="upsert" && (currentPayload!=operation.payload || localDeleted)))
            // ACK belongs only to the frozen operation. A newer captured proposal remains queued;
            // selecting replay_original never authorizes accepting server data over that proposal.
            dao.update(source.copy(state=if(accepted && !laterIntent)"acked" else "decision",wireId=target,
                decisionCode=if(laterIntent)"later_local_intent" else if(accepted)null else "server_"+outcome.getString("status")))
        }
        dao.update(row.copy(responseJson=prepared.response.canonical,state="complete"))
        prepared.result
    }

}
