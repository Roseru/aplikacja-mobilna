package pl.roseru.kalorie.data

import androidx.room.withTransaction
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.util.UUID

/** Final atomic transition. The recovery flag is never temporarily lowered to bypass guards. */
internal class ReconciliationFinishStore(private val owner:ReconciliationStore) {
    private val db get()=owner.db
    private val dao get()=owner.dao
    suspend fun finish(lease:OwnerLease,expected:AccountBindingEntity,id:String):ServerDiaryApplication=withContext(Dispatchers.IO) {
        val completed=db.withTransaction {
            val plan=owner.plan(lease,expected,id)
            if(plan.state=="complete") {
                val proof=checkNotNull(dao.evidence(id).singleOrNull {it.kind=="completion"})
                checkNotNull(db.serverDiaryDao().application(proof.runId))
            } else null
        }
        if(completed!=null)return@withContext completed
        val source=db.withTransaction {
            val plan=owner.plan(lease,expected,id);check(plan.approvedAt!=null && owner.groupsComplete(plan))
            check(dao.batches(id).all {it.state=="complete"})
            val rows=dao.sources(id);check(rows.all {it.state in setOf("acked","retained","accept_server")})
            val copy=owner.latestCopy(lease,expected,id)
            rows.filter {it.state=="accept_server"}.forEach {owner.requireDecisionProof(it,copy.second)}
            // ACK followed by a fresh full read, rather than comparing against its older pre-push snapshot.
            check(dao.batches(id).none {it.snapshotRunId==copy.first.id})
            FinishSource(plan,rows,copy.first,copy.second,db.snapshotDao().pages(copy.first.id),
                LegacyImportStore(db,owner.schema).capture(lease.storageScope,true))
        }
        val current=source.currentRows.associate {entry->val root=StrictJson.read(entry.second.toByteArray())
            (entry.first to root.getJSONObject("row").getString("id")) to root}
        check(current.keys==source.rows.map {it.entityType to it.sourceId}.toSet())
        for(row in source.rows) {
            val old=StrictJson.read(row.sourceJson.toByteArray());val now=checkNotNull(current[row.entityType to row.sourceId])
            check(StrictJson.canonical(old.getJSONObject("row"))==StrictJson.canonical(now.getJSONObject("row")) &&
                StrictJson.canonical(old.getJSONArray("items"))==StrictJson.canonical(now.getJSONArray("items")))
            if(row.state=="acked") {
                val operation=checkNotNull(row.operationId?.let {db.dao().operation(it)})
                check(operation.status=="acked")
                val target=source.copy.entities.singleOrNull {it.type==row.entityType && it.id==row.wireId}
                if(operation.action=="delete")check(target==null || target.deleted)
                else check(target!=null && !target.deleted && target.payload==row.appliedPayload)
            }
        }
        db.withTransaction {
            check(owner.plan(lease,expected,id)==source.plan && dao.sources(id)==source.rows &&
                db.snapshotDao().pages(source.run.id)==source.pages &&
                LegacyImportStore(db,owner.schema).capture(lease.storageScope,true)==source.currentRows)
            check(owner.latestCopy(lease,expected,id).first==source.run)
            val capturedOperations=source.rows.flatMap {row->JSONArray(row.outboxesJson).let {ops->
                (0 until ops.length()).map {ops.getJSONObject(it).getString("operationId")} } }.toSet()+source.rows.mapNotNull {it.operationId}
            // A later write is a new proposal. It cannot disappear in an older plan's finalization.
            check(db.serverDiaryDao().unsettled(lease.storageScope).all {it.operationId in capturedOperations})
            val oldRecords=db.serverDiaryDao().records(lease.storageScope)
            for(row in oldRecords) {
                val text=StrictJson.canonical(JSONObject().put("entity_type",row.entityType).put("entity_id",row.entityId)
                    .put("local_id",row.localId ?: JSONObject.NULL).put("wire_context",row.wireContext).put("known_revision",row.knownRevision)
                    .put("deleted",row.deleted).put("absent",row.absent).put("payload",row.payload ?: JSONObject.NULL).put("disposition",row.disposition))
                dao.insert(ReconciliationEvidence(id,"previous_shadow",row.entityType+":"+row.entityId,text,LegacyImportStore.digest(text),row.runId))
            }
            val oldAliases=dao.identities(lease.storageScope)
            for(alias in oldAliases) {
                val text=StrictJson.canonical(JSONObject().put("type",alias.entityType).put("local_id",alias.localId).put("wire_id",alias.wireId)
                    .put("source_scope",alias.sourceScope).put("source_id",alias.sourceId).put("reason",alias.reason))
                dao.insert(ReconciliationEvidence(id,"previous_alias",alias.entityType+":"+alias.localId,text,LegacyImportStore.digest(text),source.run.id))
            }
            val context=source.plan.wireContext
            val sameEpoch=oldRecords.filter {StrictJson.read(it.wireContext.toByteArray()).getString("sync_epoch")==expected.syncEpoch}
            db.serverDiaryDao().retireContext(lease.storageScope)
            // Same-epoch absence remains deletion. Cross-epoch shadow stays archived and is never inferred absent.
            sameEpoch.forEach {db.serverDiaryDao().save(it.copy(wireContext=context))}
            val next=source.plan.copy(state="ready_to_apply");dao.update(next)
            val entities=source.copy.entities.associateBy {it.type to it.id}
            for(row in source.rows) {
                val target=entities[row.entityType to row.wireId]
                if(row.state in setOf("acked","accept_server") && target!=null && !target.deleted) {
                    val old=StrictJson.read(row.sourceJson.toByteArray())
                    val oldWire=old.getString("wire_id")
                    // A new immutable goal decision receives a new local projection; its old row stays intact.
                    val mapped=dao.wire(lease.storageScope,row.entityType,row.wireId)
                    val existingLocal=mapped?.localId ?: when(row.entityType) {
                        "meal"->db.dao().meal(row.wireId,lease.storageScope)?.meal?.id
                        "weight"->db.dao().weight(row.wireId,lease.storageScope)?.id
                        "goal"->db.dao().goalById(lease.storageScope,row.wireId)?.id
                        "profile"->db.serverDiaryDao().profile(row.wireId)?.takeIf {it.ownerScope==lease.storageScope}?.id
                        "diary_day"->db.serverDiaryDao().day(row.wireId)?.takeIf {it.ownerScope==lease.storageScope}?.id
                        "product_draft"->db.serverDiaryDao().product(row.wireId)?.takeIf {it.ownerScope==lease.storageScope && it.catalogJson==null}?.id
                        else->null
                    }
                    val merged=existingLocal!=null && existingLocal!=row.localId
                    val localId=existingLocal ?: if(row.entityType=="goal" && !old.isNull("canonical_payload") &&
                        old.getString("canonical_payload")!=target.payload)UUID.randomUUID().toString() else row.localId
                    val updated=row.copy(localId=localId,decisionCode=if(merged)"mapped_projection_retired" else row.decisionCode)
                    val alias=dao.local(lease.storageScope,row.entityType,row.localId)
                    if(localId!=row.localId) {
                        alias?.let {dao.retireIdentity(it.ownerScope,it.entityType,it.localId)}
                        if(mapped==null)dao.insert(ImportIdentity(lease.storageScope,row.entityType,localId,row.wireId,lease.storageScope,row.sourceId,"explicit_reconciled_goal_projection"))
                    } else {
                        val identity=ImportIdentity(lease.storageScope,row.entityType,localId,row.wireId,alias?.sourceScope ?: lease.storageScope,
                            alias?.sourceId ?: row.sourceId,"explicit_reconciliation_alias")
                        if(alias==null)dao.insert(identity) else dao.update(identity)
                    }
                    if(row.entityType in PrivateDomainsWire.types && oldWire!=row.wireId)
                        db.domainSyncDao().retire(lease.storageScope,row.entityType,oldWire)
                    if(row.entityType=="meal")installItemAliases(lease.storageScope,localId,checkNotNull(target.payload))
                    ImportProjection(db,owner.schema).apply(next,updated,checkNotNull(target.payload),expected,target.revision)
                    dao.update(updated)
                } else if(row.state in setOf("acked","accept_server") && row.sourceEpoch==expected.syncEpoch && (target==null || target.deleted)) {
                    val original=StrictJson.read(row.sourceJson.toByteArray());val oldId=original.getString("wire_id")
                    val knownProjectionRevision=original.getInt("server_revision")
                    if(target==null && knownProjectionRevision>0 && db.serverDiaryDao().records(lease.storageScope).none {it.entityType==row.entityType && it.entityId==oldId})
                        db.serverDiaryDao().save(ServerDiaryRecord(lease.storageScope,row.entityType,oldId,row.localId,context,
                            knownProjectionRevision,true,true,null,source.run.id,"pending_local"))
                    when(row.entityType) {
                        "meal"->db.dao().meal(row.localId,lease.storageScope)?.meal?.let {current->
                            db.dao().updateMeal(current.copy(wireContext=context,deleted=true,serverRevision=target?.revision ?: current.serverRevision))}
                        "weight"->{
                            db.dao().weight(row.localId,lease.storageScope)?.let {db.dao().saveWeight(it.copy(deleted=true))}
                            db.weightSyncDao().state(lease.storageScope,row.localId)?.let {
                                db.weightSyncDao().update(it.copy(wireContext=context,serverRevision=target?.revision ?: it.serverRevision))}
                        }
                        in PrivateDomainsWire.types->db.domainSyncDao().state(lease.storageScope,row.entityType,oldId)?.let {
                            db.domainSyncDao().save(it.copy(wireContext=context,deleted=true,serverRevision=target?.revision ?: it.serverRevision))}
                    }
                } else if(row.state=="accept_server" && row.sourceEpoch!=expected.syncEpoch && target==null) {
                    // Absence after restore is not deletion. Keep this explicitly local history visible.
                    dao.update(row.copy(state="retained",decisionCode="epoch_absence_retained"))
                }
            }
            // Explicit decisions resolve local work; an absent receipt is never changed into an ACK.
            for(row in source.rows) {
                val ids=JSONArray(row.outboxesJson).let {ops->(0 until ops.length()).map {ops.getJSONObject(it).getString("operationId")}}
                for(opId in ids) {
                    val operation=db.dao().operation(opId) ?: continue
                    if(operation.status !in setOf("acked","superseded","local_only"))
                        db.dao().updateOperation(operation.copy(status="local_only"))
                }
            }
            val pending=db.pushDao().pending(lease.storageScope)
            for(batch in pending) {
                val operations=StrictJson.read(batch.requestJson.toByteArray()).getJSONArray("operations")
                check((0 until operations.length()).all {i->db.dao().operation(operations.getJSONObject(i).getString("operation_id"))?.status in setOf("acked","superseded","local_only")})
                db.pushDao().update(batch.copy(state="archived_reconciled"))
            }
            // A restored epoch has its own confirmed axis. Archive the old axis rather than
            // letting ordinary snapshot application accept a foreign context or regress this epoch.
            db.domainSyncDao().timeline(lease.storageScope)?.let {previous->
                val oldEpoch=StrictJson.read(previous.wireContext.toByteArray()).getString("sync_epoch")
                if(oldEpoch==expected.syncEpoch)check(previous.revision<=source.copy.timelineRevision)
                val text=StrictJson.canonical(JSONObject().put("wire_context",previous.wireContext).put("revision",previous.revision))
                dao.insert(ReconciliationEvidence(id,"previous_timeline","goal",text,LegacyImportStore.digest(text),source.run.id))
            }
            db.domainSyncDao().save(CanonicalGoalTimeline(lease.storageScope,context,source.copy.timelineRevision))
            ensureServerAliases(lease.storageScope,source.copy)
            val application=ServerDiaryStore(db,owner.schema).applyReconciled(lease,source.run.id,id)
            check(owner.context(lease,expected)==expected)
            val completion=StrictJson.canonical(JSONObject().put("run_id",application.runId).put("included",application.included).put("held",application.held))
            dao.insert(ReconciliationEvidence(id,"completion","application",completion,LegacyImportStore.digest(completion),source.run.id))
            dao.update(next.copy(state="complete"))
            db.bootstrapDao().update(expected.copy(requiresRecovery=false))
            application
        }
    }
    private suspend fun installItemAliases(scope:String,localId:String,payload:String) {
        val items=StrictJson.read(payload.toByteArray()).getJSONArray("items")
        val known=dao.items(scope,localId)
        for(i in 0 until items.length()) {
            val id=items.getJSONObject(i).getString("item_id")
            if(known.any {it.wireId==id})continue
            val collision=db.dao().itemById(id)?.mealId?.let {it!=localId}==true
            if(collision)dao.insert(ImportItemIdentity(scope,UUID.randomUUID().toString(),id,localId,id))
        }
    }
    private suspend fun ensureServerAliases(scope:String,copy:ServerDiarySnapshot) {
        for(entity in copy.entities.filter {!it.deleted}) {
            if(dao.wire(scope,entity.type,entity.id)!=null)continue
            val foreign=when(entity.type) {
                "meal"->db.serverDiaryDao().mealOwner(entity.id)?.let {it!=scope}==true
                "weight"->db.dao().weightOwner(entity.id)?.let {it!=scope}==true
                "goal"->db.serverDiaryDao().goal(entity.id)?.ownerScope?.let {it!=scope}==true
                "profile"->db.serverDiaryDao().profile(entity.id)?.ownerScope?.let {it!=scope}==true
                "diary_day"->db.serverDiaryDao().day(entity.id)?.ownerScope?.let {it!=scope}==true
                "product_draft"->db.serverDiaryDao().product(entity.id)?.let {it.ownerScope!=scope || it.catalogJson!=null}==true
                else->false
            }
            if(foreign)dao.insert(ImportIdentity(scope,entity.type,UUID.randomUUID().toString(),entity.id,scope,entity.id,"server_uuid_collides_with_retained_local_owner"))
            if(entity.type=="meal")installItemAliases(scope,db.localSyncId(scope,"meal",entity.id),checkNotNull(entity.payload))
        }
    }
    private data class FinishSource(val plan:ImportPlan,val rows:List<ImportSource>,val run:ServerSnapshotRun,
        val copy:ServerDiarySnapshot,val pages:List<ServerSnapshotPage>,val currentRows:List<Pair<String,String>>)
}

/** Only the latest consciously approved plan for a local projection determines retention. */
internal suspend fun CalorieDatabase.retainedSyncSources(owner:String):List<ImportSource> {
    val latest=linkedMapOf<Pair<String,String>,ImportSource>()
    for(plan in importDao().plans(owner).filter {it.approvedAt!=null && it.sourceScope==owner}) {
        for(row in importDao().sources(plan.id))latest.putIfAbsent(row.entityType to row.sourceId,row)
    }
    return latest.values.filter {it.state=="retained"}
}

/** Resolved immutable originals remain history, rather than blocking every later server goal. */
internal suspend fun CalorieDatabase.resolvedOriginalGoals(owner:String):Set<String> {
    val result=mutableSetOf<String>()
    for(plan in importDao().plans(owner).filter {it.approvedAt!=null && it.sourceScope==owner}) {
        for(row in importDao().sources(plan.id).filter {it.entityType=="goal" && it.localId!=it.sourceId}) {
            if(row.state in setOf("acked","accept_server") || row.operationId?.let {dao().operation(it)?.status=="acked"}==true)
                result+=row.sourceId
        }
    }
    return result
}
