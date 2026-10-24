package pl.roseru.kalorie.data

import androidx.room.withTransaction
import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.time.Instant

/** Raw retention is bounded; receipts keep original run/checkpoint identity and FK evidence. */
class SnapshotArchiveStore(private val db:CalorieDatabase) {
    private val archive get()=db.snapshotArchiveDao()
    companion object {
        const val MAX_RAW_RUNS=8
        const val MAX_OWNER_BYTES=128L*1_048_576
        const val MAX_RUN_BYTES=64L*1_048_576
    }
    /** Failure rolls back both the caller's reservation/page and this compaction. */
    internal suspend fun reserve(lease:OwnerLease,expected:AccountBindingEntity,extraRuns:Int=0,extraBytes:Long=0)=db.withTransaction {
        require(extraRuns>=0 && extraBytes>=0)
        requireCurrent(lease,expected)
        while(archive.rawRuns(lease.storageScope).size+extraRuns>MAX_RAW_RUNS ||
            Math.addExact(archive.ownerRawBytes(lease.storageScope),extraBytes)>MAX_OWNER_BYTES) {
            val protected=protectedRaw(lease.storageScope)
            val candidate=archive.rawRuns(lease.storageScope).firstOrNull {
                it.id !in protected && it.state in setOf("complete","expired") } ?: throw SnapshotCapacityException()
            compact(candidate)
        }
        requireCurrent(lease,expected)
    }
    private suspend fun requireCurrent(lease:OwnerLease,expected:AccountBindingEntity) {
        LocalOwnerStore(db).requireCurrent(lease)
        val current=checkNotNull(db.bootstrapDao().binding(lease.storageScope))
        if(CanonicalMealRows.context(current)!=CanonicalMealRows.context(expected))throw SnapshotConflictException()
    }
    private suspend fun protectedRaw(owner:String):Set<String> {
        val result=mutableSetOf<String>()
        db.snapshotDao().access(owner)?.activeRunId?.let(result::add)
        result+=db.snapshotDao().runs(owner).filter {it.state=="pending"}.map {it.id}
        db.serverDiaryDao().latest(owner)?.runId?.let(result::add)
        result+=archive.frozenOrigins(owner)
        result+=archive.unresolvedOrigins(owner)
        result+=archive.conflictOrigins(owner)
        result+=archive.pendingRecordOrigins(owner)
        for(plan in db.importDao().plans(owner).filter {it.state!="complete" && it.approvedAt!=null}) {
            result+=db.importDao().pulls(plan.id).map {it.runId}
            result+=archive.evidenceOrigins(plan.id)
            result+=db.importDao().batches(plan.id).map {it.snapshotRunId}
        }
        return result
    }
    private suspend fun compact(run:ServerSnapshotRun) {
        check(archive.receipt(run.id)==null && run.state in setOf("complete","expired"))
        check(run.pageCount in 0..2000 && run.itemCount in 0..100_000)
        check(archive.pageCount(run.id)==run.pageCount)
        val pages=JSONArray();var responseBytes=0L;var rawBytes=0L
        // Hash one bounded page at a time rather than duplicating a 64MiB archive in the heap.
        repeat(run.pageCount) {index->
            val page=checkNotNull(db.snapshotDao().page(run.id,index))
            val query=page.queryJson.toByteArray(Charsets.UTF_8);val body=page.responseJson.toByteArray(Charsets.UTF_8)
            responseBytes=Math.addExact(responseBytes,body.size.toLong())
            rawBytes=Math.addExact(rawBytes,query.size.toLong()+body.size)
            pages.put(JSONObject().put("index",index).put("query_sha256",LegacyImportStore.digest(page.queryJson))
                .put("response_sha256",LegacyImportStore.digest(page.responseJson)).put("query_bytes",query.size).put("response_bytes",body.size))
        }
        check(responseBytes==run.byteCount && rawBytes==archive.rawBytes(run.id))
        if(run.state=="complete")check(run.pageCount>0 && run.checkpoint!=null && run.nextPage==null)
        val manifest=StrictJson.canonical(JSONObject().put("version",1).put("run_id",run.id).put("owner_scope",run.ownerScope)
            .put("lease_generation",run.leaseGeneration).put("account_id",run.accountId).put("account_generation",run.accountGeneration)
            .put("sync_epoch",run.syncEpoch).put("context_revision",run.contextRevision).put("state",run.state)
            .put("checkpoint",run.checkpoint ?: JSONObject.NULL).put("snapshot_token",run.snapshotToken ?: JSONObject.NULL)
            .put("next_page",run.nextPage ?: JSONObject.NULL).put("server_time",run.serverTime ?: JSONObject.NULL)
            .put("timeline_revision",run.timelineRevision ?: JSONObject.NULL).put("page_count",run.pageCount)
            .put("item_count",run.itemCount).put("response_bytes",run.byteCount).put("raw_bytes",rawBytes).put("pages",pages))
        archive.insert(SnapshotArchiveReceipt(run.id,run.pageCount,run.itemCount,run.byteCount,rawBytes,
            manifest,LegacyImportStore.digest(manifest),Instant.now().toString()))
        archive.releasePages(run.id);archive.releaseIdentities(run.id)
        check(db.snapshotDao().run(run.id)==run)
    }
    internal suspend fun verifiesPage(runId:String,index:Int,query:String,response:String):Boolean {
        val receipt=archive.receipt(runId) ?: return false
        if(receipt.manifestHash!=LegacyImportStore.digest(receipt.manifestJson))throw SnapshotConflictException()
        val manifest=StrictJson.read(receipt.manifestJson.toByteArray())
        check(manifest.getString("run_id")==runId && manifest.getInt("version")==1)
        val pages=manifest.getJSONArray("pages")
        if(index !in 0 until pages.length())return false
        val page=pages.getJSONObject(index)
        return page.getInt("index")==index && page.getString("query_sha256")==LegacyImportStore.digest(query) &&
            page.getString("response_sha256")==LegacyImportStore.digest(response)
    }
}