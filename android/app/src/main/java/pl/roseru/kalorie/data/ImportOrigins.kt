package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson

/** First materialization of an origin is permanent; later source versions remain in import_sources. */
@Entity(tableName="import_origins",primaryKeys=["sourceScope","entityType","sourceId"],foreignKeys=[
    ForeignKey(entity=ImportPlan::class,parentColumns=["id"],childColumns=["firstPlanId"],onDelete=ForeignKey.RESTRICT),
    ForeignKey(entity=OutboxEntity::class,parentColumns=["operationId"],childColumns=["firstOperationId"],onDelete=ForeignKey.RESTRICT)],
    indices=[Index("targetScope"),Index("firstPlanId"),Index("firstOperationId")])
data class ImportOrigin(val sourceScope:String,val entityType:String,val sourceId:String,val targetScope:String,
    val firstPlanId:String,val firstOperationId:String,val firstFingerprint:String) {
    override fun toString()="ImportOrigin(redacted)"
}

/** Source identity is independent of a plan and of mutable queue progress. Original bytes stay archived. */
internal fun importOriginFingerprint(sourceJson:String,linkedOperations:Set<String>):String {
    val root=try {StrictJson.read(sourceJson.toByteArray())} catch(_:Exception) {
        return LegacyImportStore.digest("unparsed-source-v1:"+sourceJson)
    };val original=root.getJSONArray("outboxes");val outboxes=JSONArray()
    for(i in 0 until original.length()) {
        val value=JSONObject(original.getJSONObject(i).toString())
        if(value.getString("operationId") in linkedOperations)continue
        value.remove("status");value.remove("attempted")
        value.optJSONObject("__sqlite_types")?.let {it.remove("status");it.remove("attempted")}
        outboxes.put(value)
    }
    return LegacyImportStore.digest(StrictJson.canonical(JSONObject().put("row",root.getJSONObject("row"))
        .put("items",root.getJSONArray("items")).put("outboxes",outboxes)))
}

/** Room19 was exercised on the preserved private validation database; evolve it without wiping. */
val MIGRATION_19_20=object:Migration(19,20) {
    override fun migrate(db:SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE import_sources ADD COLUMN originFingerprint TEXT NOT NULL DEFAULT ''")
        db.execSQL("CREATE TABLE import_origins (sourceScope TEXT NOT NULL,entityType TEXT NOT NULL,sourceId TEXT NOT NULL,targetScope TEXT NOT NULL,firstPlanId TEXT NOT NULL,firstOperationId TEXT NOT NULL,firstFingerprint TEXT NOT NULL,PRIMARY KEY(sourceScope,entityType,sourceId),FOREIGN KEY(firstPlanId) REFERENCES import_plans(id) ON DELETE RESTRICT,FOREIGN KEY(firstOperationId) REFERENCES outbox(operationId) ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX index_import_origins_targetScope ON import_origins(targetScope)")
        db.execSQL("CREATE INDEX index_import_origins_firstPlanId ON import_origins(firstPlanId)")
        db.execSQL("CREATE INDEX index_import_origins_firstOperationId ON import_origins(firstOperationId)")
        val linked=db.query("SELECT operationId FROM import_sources WHERE operationId IS NOT NULL").use {cursor->
            buildSet {while(cursor.moveToNext())add(cursor.getString(0))}}
        db.query("SELECT s.planId,s.entityType,s.sourceId,s.sourceJson,s.operationId,p.sourceScope,p.targetScope,p.kind FROM import_sources s JOIN import_plans p ON p.id=s.planId ORDER BY p.rowid,s.ordinal").use {cursor->
            while(cursor.moveToNext()) {
                val plan=cursor.getString(0);val type=cursor.getString(1);val source=cursor.getString(2)
                val fingerprint=importOriginFingerprint(cursor.getString(3),linked)
                db.execSQL("UPDATE import_sources SET originFingerprint=? WHERE planId=? AND entityType=? AND sourceId=?",arrayOf(fingerprint,plan,type,source))
                if(!cursor.isNull(4) && cursor.getString(7) in setOf("guest","legacy"))
                    db.execSQL("INSERT OR IGNORE INTO import_origins(sourceScope,entityType,sourceId,targetScope,firstPlanId,firstOperationId,firstFingerprint) VALUES (?,?,?,?,?,?,?)",
                        arrayOf(cursor.getString(5),type,source,cursor.getString(6),plan,cursor.getString(4),fingerprint))
            }
        }
        db.execSQL("DROP TRIGGER IF EXISTS import_sources_immutable")
        importGuards(db)
    }
}
