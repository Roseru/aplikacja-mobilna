package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.migration.Migration
import androidx.room.withTransaction
import androidx.sqlite.db.SupportSQLiteDatabase
import pl.roseru.kalorie.core.PrivatePreviewKind
import pl.roseru.kalorie.core.PrivatePreviewProtocol
import pl.roseru.kalorie.core.PrivatePreviewValue

@Entity(tableName="private_preview_cache",primaryKeys=["ownerScope","wireContext","kind","resourceId"],
    foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT)],
    indices=[Index("ownerScope")])
data class PrivatePreviewEntity(val ownerScope:String,val wireContext:String,val kind:String,val resourceId:String,
    val payloadJson:String,val payloadHash:String,val fetchedAtMillis:Long,val sequence:Long) {
    override fun toString()="PrivatePreviewEntity(redacted)"
}
data class PrivatePreviewRef(val kind:String,val resourceId:String,val fetchedAtMillis:Long,val sequence:Long)
@Dao interface PrivatePreviewDao {
    @Query("SELECT * FROM private_preview_cache WHERE ownerScope=:owner AND wireContext=:context AND kind=:kind AND resourceId=:resource")
    suspend fun entry(owner:String,context:String,kind:String,resource:String):PrivatePreviewEntity?
    @Query("SELECT kind,resourceId,fetchedAtMillis,sequence FROM private_preview_cache WHERE ownerScope=:owner AND wireContext=:context ORDER BY sequence")
    suspend fun refs(owner:String,context:String):List<PrivatePreviewRef>
    @Query("SELECT COALESCE(SUM(LENGTH(CAST(payloadJson AS BLOB))),0) FROM private_preview_cache WHERE ownerScope=:owner")
    suspend fun bytes(owner:String):Long
    @Upsert suspend fun save(value:PrivatePreviewEntity)
    @Query("DELETE FROM private_preview_cache WHERE ownerScope=:owner AND wireContext!=:context") suspend fun retireOtherContexts(owner:String,context:String)
    @Query("DELETE FROM private_preview_cache WHERE ownerScope=:owner AND wireContext=:context AND kind=:kind AND resourceId=:resource")
    suspend fun remove(owner:String,context:String,kind:String,resource:String)
    @Query("DELETE FROM private_preview_cache WHERE ownerScope=:owner AND kind=:kind") suspend fun clearKind(owner:String,kind:String)
}

class SavedPrivatePreview(val kind:PrivatePreviewKind,val resource:String,val fetchedAtMillis:Long,val value:PrivatePreviewValue) {
    override fun toString()="SavedPrivatePreview(kind=$kind)"
}
class PrivatePreviewUnavailableException:IllegalStateException("Zapisany podgląd jest niedostępny dla bieżącego profilu")

/** Temporary snapshots only. No access token, callback authority, outbox ACK or canonical entity. */
class PrivatePreviewStore(private val db:CalorieDatabase) {
    companion object {const val MAX_ENTRIES=32;const val MAX_OWNER_BYTES=8L*1_048_576}
    private val dao get()=db.privatePreviewDao()
    private suspend fun requireCurrent(lease:OwnerLease,expected:AccountBindingEntity):String {
        LocalOwnerStore(db).requireCurrent(lease)
        if(db.ownerDao().byScope(lease.storageScope)?.kind!="account")throw PrivatePreviewUnavailableException()
        val binding=db.bootstrapDao().binding(lease.storageScope)?:throw PrivatePreviewUnavailableException()
        if(binding.requiresRecovery || db.snapshotDao().access(lease.storageScope)?.blocked==true ||
            CanonicalMealRows.context(binding)!=CanonicalMealRows.context(expected))throw PrivatePreviewUnavailableException()
        return CanonicalMealRows.context(binding)
    }
    suspend fun save(lease:OwnerLease,expected:AccountBindingEntity,kind:PrivatePreviewKind,resource:String,
        payload:ByteArray,fetchedAtMillis:Long)=db.withTransaction {
        val context=requireCurrent(lease,expected)
        require(fetchedAtMillis>=0 && payload.size in 1..PrivatePreviewProtocol.MAX_BYTES)
        val canonical=PrivatePreviewProtocol.canonicalForStorage(kind,resource,payload,expected.accountGeneration,expected.syncEpoch)
        dao.retireOtherContexts(lease.storageScope,context)
        val sequence=Math.addExact(dao.refs(lease.storageScope,context).maxOfOrNull {it.sequence}?:0,1L)
        dao.save(PrivatePreviewEntity(lease.storageScope,context,kind.name,resource,canonical,LegacyImportStore.digest(canonical),fetchedAtMillis,sequence))
        while(true) {
            val rows=dao.refs(lease.storageScope,context)
            if(rows.size<=MAX_ENTRIES && dao.bytes(lease.storageScope)<=MAX_OWNER_BYTES)break
            val old=rows.firstOrNull {it.kind==PrivatePreviewKind.NEMESIS_DETAIL.name && !(it.kind==kind.name && it.resourceId==resource)}
                ?:rows.firstOrNull {!(it.kind==kind.name && it.resourceId==resource)}?:throw PrivatePreviewUnavailableException()
            dao.remove(lease.storageScope,context,old.kind,old.resourceId)
        }
    }
    suspend fun read(lease:OwnerLease,expected:AccountBindingEntity,kind:PrivatePreviewKind,resource:String):SavedPrivatePreview?=db.withTransaction {
        PrivatePreviewProtocol.requireKey(kind,resource)
        val context=requireCurrent(lease,expected)
        val row=dao.entry(lease.storageScope,context,kind.name,resource)?:return@withTransaction null
        if(row.fetchedAtMillis<0 || row.payloadHash!=LegacyImportStore.digest(row.payloadJson))throw PrivatePreviewUnavailableException()
        val value=PrivatePreviewProtocol.decode(kind,resource,row.payloadJson.toByteArray(Charsets.UTF_8),expected.accountGeneration,expected.syncEpoch)
        SavedPrivatePreview(kind,resource,row.fetchedAtMillis,value)
    }
    suspend fun availableNemesisDetails(lease:OwnerLease,expected:AccountBindingEntity):Set<String> = db.withTransaction {
        val context=requireCurrent(lease,expected)
        dao.refs(lease.storageScope,context).filter {it.kind==PrivatePreviewKind.NEMESIS_DETAIL.name}.map {it.resourceId}.toSet()
    }
    suspend fun clearCurrent(lease:OwnerLease,expected:AccountBindingEntity,kinds:Set<PrivatePreviewKind>)=db.withTransaction {
        requireCurrent(lease,expected)
        for(kind in kinds)dao.clearKind(lease.storageScope,kind.name)
    }
    /** Explicit local removal; old callbacks cannot clear a newly selected owner's preview. */
    suspend fun clear(lease:OwnerLease,kinds:Set<PrivatePreviewKind>)=db.withTransaction {
        LocalOwnerStore(db).requireCurrent(lease)
        if(db.ownerDao().byScope(lease.storageScope)?.kind!="account")throw PrivatePreviewUnavailableException()
        for(kind in kinds)dao.clearKind(lease.storageScope,kind.name)
    }
}

val MIGRATION_26_27=object:Migration(26,27) {
    override fun migrate(db:SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS private_preview_cache (ownerScope TEXT NOT NULL, wireContext TEXT NOT NULL, kind TEXT NOT NULL, resourceId TEXT NOT NULL, payloadJson TEXT NOT NULL, payloadHash TEXT NOT NULL, fetchedAtMillis INTEGER NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY(ownerScope,wireContext,kind,resourceId), FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_private_preview_cache_ownerScope ON private_preview_cache(ownerScope)")
    }
}
