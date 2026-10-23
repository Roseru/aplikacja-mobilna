package pl.roseru.kalorie.data

import androidx.room.withTransaction
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID

class ImportContextChangedException:IllegalStateException("Konto lub źródło importu zmieniło się; odśwież podsumowanie")
data class ImportProgress(val planId:String,val account:String,val issuer:String,val subject:String,
    val state:String,val total:Int,val queued:Int,val acknowledged:Int,val retained:Int,val decisions:List<ImportIssue>,
    val alreadyImported:Int=0,val pending:Int=0,val waiting:Int=0)
data class ImportIssue(val type:String,val sourceId:String,val code:String)

/** Consent, source capture and each materialized chunk commit in independent durable transactions. */
class LegacyImportStore(private val db:CalorieDatabase,private val schema:SyncWireSchema) {
    private val dao get()=db.importDao()
    private val owners=LocalOwnerStore(db)
    private suspend fun binding(lease:OwnerLease):AccountBindingEntity {
        owners.requireCurrent(lease)
        check(db.ownerDao().byScope(lease.storageScope)?.kind=="account")
        return checkNotNull(db.bootstrapDao().binding(lease.storageScope))
    }
    private suspend fun current(lease:OwnerLease,id:String):ImportPlan {
        val context=binding(lease);val plan=checkNotNull(dao.plan(id))
        if(plan.targetScope!=lease.storageScope || plan.targetAccountId!=context.accountId ||
            plan.wireContext!=CanonicalMealRows.context(context)) throw ImportContextChangedException()
        return plan
    }
    /** Target identity is captured from the binding and local OIDC identity, never a UI supplied owner. */
    suspend fun preview(lease:OwnerLease,sourceScope:String):ImportProgress=withContext(Dispatchers.IO) {
        db.withTransaction {
            val context=binding(lease);check(!context.requiresRecovery)
            val target=checkNotNull(db.ownerDao().byScope(lease.storageScope))
            val source=checkNotNull(db.ownerDao().byScope(sourceScope))
            require(source.kind=="guest" || source.storageScope==lease.storageScope)
            dao.assignment(sourceScope)?.let { require(it.targetScope==lease.storageScope && it.accountId==context.accountId) }
            val captured=capture(sourceScope,source.kind=="guest")
            val fingerprint=digest(captured.joinToString("\n") {it.first+":"+it.second})
            val wireContext=CanonicalMealRows.context(context)
            val kind=if(source.kind=="guest")"guest" else "legacy"
            val existing=dao.plans(lease.storageScope).firstOrNull {it.sourceScope==sourceScope && it.kind==kind &&
                it.fingerprint==fingerprint && it.wireContext==wireContext}
            if(existing!=null) return@withTransaction progress(existing)
            val plan=ImportPlan(UUID.randomUUID().toString(),sourceScope,lease.storageScope,context.accountId,
                checkNotNull(target.issuer),checkNotNull(target.subject),kind,fingerprint,wireContext,Instant.now().toString())
            dao.insert(plan)
            val linkedOperations=dao.linkedOperations().toSet()
            for((ordinal,entry) in captured.withIndex()) {
                val (type,json)=entry;val root=StrictJson.read(json.toByteArray());val row=root.getJSONObject("row")
                val id=row.getString("id")
                val originFingerprint=importOriginFingerprint(json,linkedOperations)
                val origin=dao.origin(sourceScope,type,id)
                if(origin!=null)check(origin.targetScope==lease.storageScope)
                val prior=dao.originHistory(sourceScope,lease.storageScope,type,id).firstOrNull {
                    it.operationId!=null && it.originFingerprint==originFingerprint }
                val alias=dao.identities(lease.storageScope).firstOrNull {
                    it.entityType==type && it.localId==(prior?.localId ?: "") } ?: dao.identities(lease.storageScope).firstOrNull {
                    it.entityType==type && it.sourceScope==sourceScope && it.sourceId==id }
                val wireId=alias?.wireId ?: prior?.wireId ?: validUuid(id) ?: UUID.randomUUID().toString()
                // Room uses global primary keys. A retained source needs a separate local projection ID.
                val localId=alias?.localId ?: prior?.localId ?: if(sourceScope==lease.storageScope)id else UUID.randomUUID().toString()
                val outboxes=root.getJSONArray("outboxes")
                val uncertain=(0 until outboxes.length()).any { i->val op=outboxes.getJSONObject(i)
                    op.optInt("attempted")==1 && op.optString("status") !in setOf("acked","superseded","local_only") }
                val collision=dao.wire(lease.storageScope,type,wireId)?.let {it.localId!=localId}==true ||
                    db.serverDiaryDao().records(lease.storageScope).any {it.entityType==type && it.entityId==wireId &&
                        (sourceScope!=lease.storageScope || it.localId!=id)}
                val issue=when {prior!=null->null;origin!=null->"previously_imported_source_changed"
                    uncertain->"uncertain_original_operation";collision->"uuid_collision";else->null}
                dao.insert(ImportSource(plan.id,type,id,ordinal,json,digest(json),StrictJson.canonical(outboxes),localId,wireId,
                    state=if(prior!=null)"already_imported" else if(issue==null)"pending" else "decision",decisionCode=issue,
                    originFingerprint=originFingerprint))
            }
            progress(plan)
        }
    }
    /** Double-click/restart returns the same consent; another account cannot acquire this guest. */
    suspend fun approve(lease:OwnerLease,planId:String,accountId:String,issuer:String,subject:String):ImportProgress=db.withTransaction {
        val plan=current(lease,planId)
        require(plan.targetAccountId==accountId && plan.issuer==issuer && plan.subject==subject)
        if(plan.approvedAt!=null) return@withTransaction progress(plan)
        val captured=capture(plan.sourceScope,plan.kind=="guest")
        if(digest(captured.joinToString("\n") {it.first+":"+it.second})!=plan.fingerprint) throw ImportContextChangedException()
        val time=Instant.now().toString()
        if(plan.kind=="guest") {
            val assignment=dao.assignment(plan.sourceScope)
            if(assignment==null) dao.insert(GuestAssignment(plan.sourceScope,plan.targetScope,accountId,issuer,subject,plan.id,time))
            else require(assignment.targetScope==plan.targetScope && assignment.accountId==accountId && assignment.issuer==issuer && assignment.subject==subject)
        }
        val approved=plan.copy(approvedAt=time,state="approved");dao.update(approved);progress(approved)
    }
    suspend fun status(lease:OwnerLease,planId:String):ImportProgress=db.withTransaction { current(lease,planId).let {progress(if(it.approvedAt!=null)refresh(it) else it)} }
    suspend fun plans(lease:OwnerLease):List<ImportProgress> = db.withTransaction {
        binding(lease);dao.plans(lease.storageScope).map {progress(it)}
    }
    /** A choice is append-only and bound to the exact source hash shown to the user. */
    suspend fun decide(lease:OwnerLease,planId:String,type:String,id:String,expectedHash:String,choiceJson:String):ImportProgress=withContext(Dispatchers.IO) {
        val choice=StrictJson.read(choiceJson.toByteArray());val canonical=StrictJson.canonical(choice)
        require(choice.getString("choice") in setOf("metadata","keep_local","new_identity"))
        db.withTransaction {
            val plan=current(lease,planId);check(plan.approvedAt!=null)
            val row=checkNotNull(dao.source(planId,type,id));require(row.sourceHash==expectedHash)
            check(row.operationId==null && row.state !in setOf("retained","acked","already_imported"))
            // An uncertain attempted operation needs receipts/replay reconciliation, not a second import.
            if(row.decisionCode=="uncertain_original_operation") require(choice.getString("choice")=="keep_local")
            if(row.decisionCode=="uuid_collision") require(choice.getString("choice") in setOf("new_identity","keep_local"))
            if(row.decisionCode=="previously_imported_source_changed") require(choice.getString("choice") in setOf("new_identity","keep_local"))
            dao.insert(ImportDecision(UUID.randomUUID().toString(),planId,type,id,expectedHash,canonical,Instant.now().toString()))
            dao.update(when(choice.getString("choice")) {
                "keep_local"->row.copy(state="retained",decisionCode=null,metadataJson=canonical)
                "new_identity"->row.copy(wireId=UUID.randomUUID().toString(),localId=UUID.randomUUID().toString(),state="pending",decisionCode=null,metadataJson=canonical)
                else->row.copy(metadataJson=canonical,state="pending",decisionCode=null)
            })
            progress(plan)
        }
    }
    suspend fun source(lease:OwnerLease,planId:String,type:String,id:String):ImportSource=db.withTransaction {
        current(lease,planId);checkNotNull(dao.source(planId,type,id))
    }
    /** A bounded chunk can finish while the screen is closed. No data is marked ACKed here. */
    suspend fun resume(lease:OwnerLease,planId:String,limit:Int=25):ImportProgress=withContext(Dispatchers.IO) {
        require(limit in 1..100)
        db.withTransaction {
            val plan=current(lease,planId);check(plan.approvedAt!=null && plan.kind in setOf("guest","legacy"))
            val context=binding(lease);check(!context.requiresRecovery)
            val gate=MealPushStore(db,schema).gate(lease)
            val rows=dao.sources(planId)
            val ids=rows.associate {"${it.entityType}:${it.sourceId}" to it.wireId}
            var axis=db.domainSyncDao().timeline(lease.storageScope)?.revision ?: Math.toIntExact(checkNotNull(gate.run.timelineRevision))
            axis=Math.addExact(axis,db.domainSyncDao().unsettled(lease.storageScope).count {it.entityType=="goal"})
            for(row in rows.filter {it.state in setOf("pending","waiting_dependency")}.take(limit)) {
                // Another approved plan may have materialized this source since this preview.
                val origin=dao.origin(plan.sourceScope,row.entityType,row.sourceId)
                if(origin!=null) {
                    check(origin.targetScope==plan.targetScope)
                    val prior=dao.originHistory(plan.sourceScope,plan.targetScope,row.entityType,row.sourceId).firstOrNull {
                        it.planId!=plan.id && it.operationId!=null && it.originFingerprint==row.originFingerprint }
                    if(prior!=null) {dao.update(row.copy(state="already_imported",decisionCode=null));continue}
                    if(StrictJson.read(row.metadataJson.toByteArray()).optString("choice")!="new_identity") {
                        dao.update(row.copy(state="decision",decisionCode="previously_imported_source_changed"));continue
                    }
                }
                val root=StrictJson.read(row.sourceJson.toByteArray());val original=root.getJSONObject("row")
                val items=root.getJSONArray("items")
                val itemIds=(0 until items.length()).associate {i->val id=items.getJSONObject(i).getString("id")
                    id to (validUuid(id) ?: UUID.nameUUIDFromBytes((planId+":item:"+id).toByteArray()).toString())}
                val metadata=metadata(row.metadataJson,if(row.entityType=="goal")axis else null)
                val result=LegacyImportWire.convert(LegacyImportSource(row.entityType,row.sourceId,StrictJson.canonical(original),
                    (0 until items.length()).map {StrictJson.canonical(items.getJSONObject(it))},
                    (0 until root.getJSONArray("outboxes").length()).map {StrictJson.canonical(root.getJSONArray("outboxes").getJSONObject(it))}),
                    LegacyImportIds(ids,itemIds),metadata,schema)
                if(result is LegacyImportConversion.NeedsDecision) {
                    dao.update(row.copy(state="decision",decisionCode=result.code));continue
                }
                result as LegacyImportConversion.Ready
                val known=db.serverDiaryDao().records(lease.storageScope).firstOrNull {it.entityType==row.entityType && it.entityId==row.wireId}
                if(known!=null && (known.deleted || known.absent)) {
                    dao.update(row.copy(state="decision",decisionCode="absent_same_epoch"));continue
                }
                if(result.deleted) {
                    // An unsent historical local tombstone is retained; it never creates a server record.
                    dao.update(row.copy(state="retained",decisionCode=null));continue
                }
                val dependency=result.dependencies.firstOrNull {dependency-> rows.firstOrNull {
                    it.entityType==dependency.entityType && it.sourceId==dependency.sourceLocalId }?.let {
                    dao.source(planId,it.entityType,it.sourceId)?.state !in setOf("queued","acked") }==true }
                if(dependency!=null) {dao.update(row.copy(state="waiting_dependency",decisionCode="dependency_pending"));continue}
                val payload=checkNotNull(result.payload)
                val naturalConflict=when(row.entityType) {
                    "profile"->db.dao().currentProfile(lease.storageScope)?.id?.let {it!=row.localId}==true
                    "diary_day"->db.dao().currentDiaryDay(lease.storageScope,StrictJson.read(payload.toByteArray()).getString("local_date"))?.id?.let {it!=row.localId}==true
                    else->false
                }
                if(naturalConflict){dao.update(row.copy(state="decision",decisionCode="natural_key_review"));continue}
                val opId=UUID.randomUUID().toString();val base=known?.knownRevision
                val wire=operation(opId,row.entityType,row.wireId,context.syncEpoch,base,payload)
                installIdentity(plan,row,items,itemIds)
                ImportProjection(db,schema).apply(plan,row,payload,context,base ?: 0)
                val queue=if(row.entityType=="goal" && db.domainSyncDao().unsettled(lease.storageScope).any {it.entityType=="goal"})"waiting_timeline" else "pending"
                db.dao().enqueue(OutboxEntity(opId,lease.storageScope,row.entityType,row.wireId,"upsert",base,payload,
                    Instant.now().toString(),queue,"sync-v1",wire,plan.wireContext))
                // Legacy bytes remain untouched. Only explicitly superseded local work changes status.
                if(plan.sourceScope==plan.targetScope) {
                    db.serverDiaryDao().unsettled(plan.sourceScope).filter {it.entityType==row.entityType && it.entityId==row.sourceId &&
                        it.wireFormat!="sync-v1" && !it.attempted}.forEach {db.dao().updateOperation(it.copy(status="superseded"))}
                }
                dao.update(row.copy(state="queued",decisionCode=null,operationId=opId,appliedPayload=payload))
                dao.insert(ImportOrigin(plan.sourceScope,row.entityType,row.sourceId,plan.targetScope,plan.id,opId,row.originFingerprint))
                if(row.entityType=="goal")axis=Math.addExact(axis,1)
            }
            val state=refresh(plan);progress(state)
        }
    }
    private suspend fun installIdentity(plan:ImportPlan,row:ImportSource,items:JSONArray,itemIds:Map<String,String>) {
        val existing=dao.local(plan.targetScope,row.entityType,row.localId)
        val identity=ImportIdentity(plan.targetScope,row.entityType,row.localId,row.wireId,plan.sourceScope,row.sourceId,
            if(row.wireId==row.sourceId)"source_uuid_preserved_local_projection_alias" else "legacy_or_explicit_collision_mapping")
        if(existing==null)dao.insert(identity) else check(existing==identity)
        val aliases=dao.items(plan.targetScope,row.localId)
        for(i in 0 until items.length()) {
            val id=items.getJSONObject(i).getString("id")
            if(aliases.none {it.sourceId==id})dao.insert(ImportItemIdentity(plan.targetScope,
                if(plan.sourceScope==plan.targetScope)id else UUID.randomUUID().toString(),itemIds.getValue(id),row.localId,id))
        }
    }
    private fun operation(op:String,type:String,id:String,epoch:String,revision:Int?,payload:String)=when(type) {
        "meal"->MealWire.operation(op,id,epoch,revision,payload,schema)
        "weight"->WeightWire.operation(op,id,epoch,revision,payload,schema)
        else->PrivateDomainsWire.operation(op,type,id,epoch,revision,payload,schema)
    }
    private fun metadata(json:String,axis:Int?):LegacyImportMetadata {
        val value=StrictJson.read(json.toByteArray())
        fun text(key:String)=if(value.has(key)&&!value.isNull(key))value.getString(key) else null
        return LegacyImportMetadata(confirmed=value.optString("choice")=="metadata",zone=text("zone"),
            goalDecidedAt=text("goal_decided_at"),goalReason=text("goal_reason"),goalAim=text("goal_aim"),
            goalActivity=text("goal_activity"),timelineBaseRevision=axis,correctionOfLocalId=text("correction_of"),correctedPayload=text("corrected_payload"))
    }
    private suspend fun refresh(plan:ImportPlan):ImportPlan {
        val rows=dao.sources(plan.id)
        rows.filter {it.state=="queued"}.forEach {source->
            val operation=source.operationId?.let {db.dao().operation(it)}
            if(operation?.status=="acked")dao.update(source.copy(state="acked"))
            else if(operation?.status in setOf("conflict","rejected"))dao.update(source.copy(state="decision",decisionCode="server_${operation?.status}"))
        }
        val updated=dao.sources(plan.id)
        val state=when {updated.all {it.state in setOf("acked","retained","already_imported")}->"complete"
            updated.any {it.state=="decision"}->"decisions";else->"running"}
        return plan.copy(state=state).also {dao.update(it)}
    }
    private suspend fun progress(plan:ImportPlan):ImportProgress {
        val rows=dao.sources(plan.id)
        return ImportProgress(plan.id,plan.targetAccountId,plan.issuer,plan.subject,plan.state,rows.size,
            rows.count {it.state=="queued"},rows.count {it.state=="acked"},rows.count {it.state=="retained"},
            rows.filter {it.state=="decision"}.map {ImportIssue(it.entityType,it.sourceId,it.decisionCode ?: "decision_required")},
            alreadyImported=rows.count {it.state=="already_imported"},pending=rows.count {it.state=="pending"},waiting=rows.count {it.state=="waiting_dependency"})
    }
    /** Full database rows (including records without outbox), exact embedded snapshots and original bodies. */
    internal suspend fun capture(scope:String,guest:Boolean):List<Pair<String,String>> {
        val database=db.openHelper.writableDatabase
        fun query(sql:String,args:Array<out Any?>):List<JSONObject> = database.query(sql,args).use {cursor->
            buildList {while(cursor.moveToNext()) add(JSONObject().apply {cursor.columnNames.forEachIndexed {index,name->
                put(name,when(cursor.getType(index)) {android.database.Cursor.FIELD_TYPE_NULL->JSONObject.NULL
                    android.database.Cursor.FIELD_TYPE_INTEGER->cursor.getLong(index)
                    android.database.Cursor.FIELD_TYPE_FLOAT->java.math.BigDecimal.valueOf(cursor.getDouble(index)).toPlainString()
                    else->cursor.getString(index)}) }
                put("__sqlite_types",JSONObject().apply {cursor.columnNames.forEachIndexed {index,name->put(name,cursor.getType(index))}})
            })}
        }
        val tables=listOf("goal" to "goals","profile" to "profiles","product_draft" to "products","diary_day" to "diary_days","meal" to "meals","weight" to "weights")
        val extracted=tables.flatMap {(type,table)->
            val order=if(type=="goal")"localSequence,rowid" else "rowid"
            query("SELECT * FROM $table WHERE ownerScope=? ORDER BY $order",arrayOf(scope)).mapNotNull {row->
                val id=row.getString("id")
                if(db.importDao().retired(scope,type,id)!=null)return@mapNotNull null
                val canonical=when(type) {"meal"->!row.isNull("wirePayload");"weight"->db.weightSyncDao().state(scope,id)!=null
                    else->db.domainSyncDao().local(scope,type,id)!=null}
                if(!guest && canonical)return@mapNotNull null
                val items=if(type=="meal")query("SELECT * FROM meal_items WHERE mealId=? ORDER BY rowid",arrayOf(id)) else emptyList()
                val wireId=db.wireSyncId(scope,type,id)
                val outboxes=query("SELECT * FROM outbox WHERE ownerScope=? AND entityType=? AND (entityId=? OR entityId=?) ORDER BY rowid",arrayOf(scope,type,id,wireId))
                val state=if(type in PrivateDomainsWire.types)db.domainSyncDao().local(scope,type,id) else null
                val weight=if(type=="weight")db.weightSyncDao().state(scope,id) else null
                val context=when(type){"meal"->if(row.isNull("wireContext"))null else row.getString("wireContext");"weight"->weight?.wireContext;else->state?.wireContext}
                val payload=when(type){"meal"->if(row.isNull("wirePayload"))null else row.getString("wirePayload");"weight"->weight?.wirePayload;else->state?.wirePayload}
                val revision=when(type){"meal"->row.optInt("serverRevision");"weight"->weight?.serverRevision ?: 0;else->state?.serverRevision ?: 0}
                type to StrictJson.canonical(JSONObject().put("row",row).put("items",JSONArray(items)).put("outboxes",JSONArray(outboxes))
                    .put("wire_id",wireId).put("wire_context",context ?: JSONObject.NULL).put("canonical_payload",payload ?: JSONObject.NULL).put("server_revision",revision))
            }
        }
        // Deleted profiles/products can have only an outbox left. Preserve those originals too.
        val represented=tables.flatMap {(type,table)->query("SELECT id FROM $table WHERE ownerScope=?",arrayOf(scope))
            .map {type to it.getString("id")} }.toSet()
        val orphaned=query("SELECT entityType,entityId,MIN(rowid) AS ordinal FROM outbox WHERE ownerScope=? AND entityType IN ('profile','goal','product_draft','diary_day','meal','weight') GROUP BY entityType,entityId ORDER BY MIN(rowid)",arrayOf(scope))
            .mapNotNull {identity->
                val type=identity.getString("entityType");val id=identity.getString("entityId")
                if((type to id) in represented || (type to db.localSyncId(scope,type,id)) in represented)return@mapNotNull null
                if(db.importDao().retired(scope,type,id)!=null)return@mapNotNull null
                val outboxes=query("SELECT * FROM outbox WHERE ownerScope=? AND entityType=? AND entityId=? ORDER BY rowid",arrayOf(scope,type,id))
                // A newly linked recovery proposal already has its immutable source in this ledger.
                // It is not a concurrent new user record and must not be imported a second time.
                if(outboxes.all {it.getString("wireFormat")=="sync-recovery-v1" && db.importDao().operationSource(scope,it.getString("operationId"))!=null})return@mapNotNull null
                if(!guest && outboxes.all {it.getString("wireFormat")=="sync-v1" && it.getString("status") in setOf("acked","superseded","local_only")})return@mapNotNull null
                val latest=outboxes.last()
                val wireContext=if(latest.isNull("wireContext"))null else latest.getString("wireContext")
                val row=JSONObject().put("id",id).put("missingProjection",true).put("deleted",true)
                type to StrictJson.canonical(JSONObject().put("row",row).put("items",JSONArray()).put("outboxes",JSONArray(outboxes))
                    .put("wire_id",id).put("wire_context",wireContext ?: JSONObject.NULL).put("canonical_payload",JSONObject.NULL)
                    .put("server_revision",if(latest.isNull("baseRevision"))0 else latest.getInt("baseRevision")))
            }
        return extracted+orphaned
    }
    companion object {
        internal fun digest(value:String)=MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString(""){"%02x".format(it)}
        private fun validUuid(value:String):String? = try {UUID.fromString(value).toString().takeIf {it==value}} catch(_:Exception){null}
    }
}
