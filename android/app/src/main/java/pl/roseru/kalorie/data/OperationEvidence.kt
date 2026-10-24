package pl.roseru.kalorie.data

import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*

internal data class HistoricalOperationResult(val entityType:String,val entityId:String,val epoch:String,
    val action:String,val status:String,val revision:Int?)

/** Exact saved responses prove the revision of that operation; a current projection does not. */
internal suspend fun CalorieDatabase.provedOperationResults(schema:SyncWireSchema,owner:String):Map<String,HistoricalOperationResult> {
    val results=linkedMapOf<String,HistoricalOperationResult>()
    suspend fun collect(batch:PushBatch,receipt:PushReceipt) {
        val wire=batch.json().getJSONArray("operations");val outcomes=receipt.json().getJSONArray("results")
        for(i in 0 until wire.length()) {
            val operation=wire.getJSONObject(i);val outcome=outcomes.getJSONObject(i);val id=operation.getString("operation_id")
            val saved=checkNotNull(dao().operation(id))
            check(saved.ownerScope==owner && saved.wireJson==StrictJson.canonical(operation))
            val accepted=outcome.getString("status") in setOf("accepted","already_applied")
            val proof=HistoricalOperationResult(operation.getString("entity_type"),operation.getString("entity_id"),operation.getString("sync_epoch"),
                operation.getString("action"),if(accepted)"accepted" else outcome.getString("status"),if(accepted)outcome.getInt("revision") else null)
            val old=results.putIfAbsent(id,proof);check(old==null || old==proof)
        }
    }
    val ordinary=PushProtocol(schema);val recovery=RecoveryProtocol(schema)
    for(row in pushDao().received(owner)) {
        val batch=ordinary.restore(row.requestJson.toByteArray());check(batch.sha256==row.requestHash)
        collect(batch,ordinary.response(batch,200,checkNotNull(row.responseJson).toByteArray()))
    }
    for(row in importDao().received(owner)) {
        val recover=row.kind=="epoch_recovery"
        val batch=if(recover)recovery.restore(row.requestJson.toByteArray()) else ordinary.restore(row.requestJson.toByteArray())
        check(batch.sha256==row.requestHash)
        val receipt=if(recover)recovery.response(batch,200,checkNotNull(row.responseJson).toByteArray())
            else ordinary.response(batch,200,checkNotNull(row.responseJson).toByteArray())
        collect(batch,receipt)
    }
    return results
}
