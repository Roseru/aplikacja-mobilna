package pl.roseru.kalorie.energy

import androidx.room.*
import androidx.room.migration.Migration
import androidx.room.withTransaction
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import pl.roseru.kalorie.data.*
import java.security.MessageDigest
import java.util.UUID

@Entity(tableName="energy_cache",primaryKeys=["ownerScope","wireContext","kind","recordId"],
    foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT)])
data class EnergyCacheEntity(val ownerScope:String,val wireContext:String,val kind:String,val recordId:String,
    val revision:Int,val wire:String,val fetchedAt:Long) {override fun toString()="EnergyCacheEntity(redacted)"}

@Entity(tableName="energy_attempts",indices=[Index(value=["ownerScope","wireContext","resource","createdAt"])],
    foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT)])
data class EnergyAttemptEntity(@PrimaryKey val id:String,val ownerScope:String,val wireContext:String,val leaseGeneration:Long,val resource:String,val kind:String,
    val method:String,val path:String,val body:String,val ifMatch:String?,val fingerprint:String,val createdAt:Long,
    val attempted:Boolean,val state:String,val retryAt:Long,val responseJson:String?,val errorCode:String?) {
    override fun toString()="EnergyAttemptEntity(redacted)"
}
@Entity(tableName="energy_backoff",primaryKeys=["ownerScope","wireContext"],
    foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT)])
data class EnergyBackoffEntity(val ownerScope:String,val wireContext:String,val retryAt:Long)

@Dao interface EnergyDao {
    @Query("SELECT * FROM account_bindings WHERE ownerScope=:owner") fun observeBinding(owner:String):Flow<AccountBindingEntity?>
    @Query("SELECT * FROM energy_cache WHERE ownerScope=:owner AND wireContext=:context ORDER BY kind,revision DESC,recordId")
    suspend fun cache(owner:String,context:String):List<EnergyCacheEntity>
    @Query("SELECT * FROM energy_cache WHERE ownerScope=:owner AND wireContext=:context AND kind=:kind AND recordId=:id")
    suspend fun cache(owner:String,context:String,kind:String,id:String):EnergyCacheEntity?
    @Insert suspend fun insert(row:EnergyCacheEntity)
    @Update suspend fun update(row:EnergyCacheEntity)
    @Query("DELETE FROM energy_cache WHERE ownerScope=:owner AND wireContext=:context AND kind=:kind AND recordId=:id")
    suspend fun removeCache(owner:String,context:String,kind:String,id:String)
    @Query("SELECT * FROM energy_attempts WHERE ownerScope=:owner ORDER BY createdAt DESC,id LIMIT 256")
    suspend fun attempts(owner:String):List<EnergyAttemptEntity>
    @Query("SELECT count(*) FROM energy_attempts WHERE ownerScope=:owner AND state IN ('prepared','unknown','needs_reconciliation')")
    suspend fun pendingCount(owner:String):Int
    @Query("SELECT * FROM energy_attempts WHERE id=:id") suspend fun attempt(id:String):EnergyAttemptEntity?
    @Insert suspend fun insert(row:EnergyAttemptEntity)
    @Update suspend fun update(row:EnergyAttemptEntity)
    @Query("DELETE FROM energy_attempts WHERE id=:id") suspend fun removeAttempt(id:String)
    @Query("SELECT * FROM energy_backoff WHERE ownerScope=:owner AND wireContext=:context")
    suspend fun backoff(owner:String,context:String):EnergyBackoffEntity?
    @Upsert suspend fun save(row:EnergyBackoffEntity)
}

class EnergyAccessFailure(val reason:String):IllegalStateException(reason)

/** Uses the already shared session bridge; this is not a second authentication context. */
@ConsistentCopyVisibility
data class EnergyScope internal constructor(val session:CommunityScope) {
    val lease get()=session.lease
    val binding get()=session.binding
    val wireContext get()=session.wireContext
    override fun toString()="EnergyScope(redacted)"
}

class EnergyStore(private val db:CalorieDatabase) {
    private val owners=LocalOwnerStore(db)
    private val dao get()=db.energyDao()
    fun observeBinding(lease:OwnerLease)=dao.observeBinding(lease.storageScope)
    fun localChanges():Flow<Unit> = db.invalidationTracker.createFlow("energy_cache","energy_attempts","canonical_energy_versions","sync_protocol_states").map {Unit}
    suspend fun scope(lease:OwnerLease):EnergyScope?=db.withTransaction {
        owners.requireCurrent(lease)
        if(db.ownerDao().byScope(lease.storageScope)?.kind!="account")return@withTransaction null
        db.bootstrapDao().binding(lease.storageScope)?.let {EnergyScope(CommunityScope(lease,it,CanonicalMealRows.context(it)))}
    }
    suspend fun requireScope(scope:EnergyScope) {
        owners.requireCurrent(scope.lease)
        if(db.bootstrapDao().binding(scope.lease.storageScope)!=scope.binding)throw EnergyAccessFailure("stale_context")
    }
    suspend fun cached(scope:EnergyScope):List<EnergyCacheEntity> = db.withTransaction {
        requireScope(scope)
        val preview=dao.cache(scope.lease.storageScope,scope.wireContext)
        val canonical=db.canonicalEnergyDao().latest(scope.lease.storageScope,scope.wireContext)
        val versions=preview.filter {it.kind=="version"}.associateBy {it.recordId}.toMutableMap()
        for(row in canonical) {
            versions[row.entityId]?.let {require(it.revision==row.revision && it.wire==row.wire)}
            versions[row.entityId]=EnergyCacheEntity(row.ownerScope,row.wireContext,"version",row.entityId,row.revision,row.wire,row.recordedAt)
        }
        preview.filter {it.kind!="version"}+versions.values
    }
    internal suspend fun <T> transaction(scope:EnergyScope,block:suspend ()->T):T=db.withTransaction {requireScope(scope);block()}
    suspend fun cache(scope:EnergyScope,kind:String,id:String,revision:Int,wire:String,now:Long)=db.withTransaction {
        requireScope(scope)
        require(kind in setOf("state","version","analysis","profile","capabilities","unavailable","consent_uncertain") && revision>=0)
        require(wire.toByteArray(Charsets.UTF_8).size in 1..1_048_576)
        val old=dao.cache(scope.lease.storageScope,scope.wireContext,kind,id)
        if(kind=="version" && old!=null)require(old.revision==revision && old.wire==wire)
        if(kind=="version")db.canonicalEnergyDao().version(scope.lease.storageScope,scope.wireContext,id)?.let {
            require(it.revision==revision && it.wire==wire)
        }
        if(old!=null && revision<old.revision)return@withTransaction
        val row=EnergyCacheEntity(scope.lease.storageScope,scope.wireContext,kind,id,revision,wire,now)
        if(old==null)dao.insert(row)else dao.update(row)
        val all=dao.cache(scope.lease.storageScope,scope.wireContext)
        if(all.size>1000 || all.sumOf {it.wire.toByteArray(Charsets.UTF_8).size.toLong()}>4L*1_048_576)throw EnergyAccessFailure("cache_full")
    }
    suspend fun invalidateState(scope:EnergyScope)=db.withTransaction {
        requireScope(scope);dao.removeCache(scope.lease.storageScope,scope.wireContext,"state","state")
    }
    suspend fun invalidateProfile(scope:EnergyScope)=db.withTransaction {
        requireScope(scope);dao.removeCache(scope.lease.storageScope,scope.wireContext,"profile","profile")
    }
    suspend fun consentMarker(scope:EnergyScope):String?=db.withTransaction {
        requireScope(scope);dao.cache(scope.lease.storageScope,scope.wireContext,"consent_uncertain","consent")?.wire
    }
    suspend fun clearConsentMarker(scope:EnergyScope,expected:String?)=db.withTransaction {
        requireScope(scope)
        if(consentMarker(scope)==expected)dao.removeCache(scope.lease.storageScope,scope.wireContext,"consent_uncertain","consent")
    }
    suspend fun attempts(scope:EnergyScope):List<EnergyAttemptEntity> = db.withTransaction {requireScope(scope);dao.attempts(scope.lease.storageScope)}
    suspend fun retryAt(scope:EnergyScope):Long=db.withTransaction {requireScope(scope);dao.backoff(scope.lease.storageScope,scope.wireContext)?.retryAt?:0}
    suspend fun defer(scope:EnergyScope,until:Long)=db.withTransaction {
        requireScope(scope);dao.save(EnergyBackoffEntity(scope.lease.storageScope,scope.wireContext,maxOf(until,retryAt(scope))))
    }
    suspend fun prepare(scope:EnergyScope,resource:String,kind:String,method:String,path:String,body:String,ifMatch:String?,now:Long):EnergyAttemptEntity=db.withTransaction {
        requireScope(scope);check(!scope.binding.requiresRecovery)
        require(kind in setOf("create","accept","reject","revert","affirm","consent"))
        require((kind=="consent" && method=="PUT" && path=="/me/consents") ||
            (method=="POST" && path in setOf("/me/energy/analyses","/me/energy/analyses/accept","/me/energy/analyses/reject","/me/energy/revert","/me/energy/affirm")))
        require(body.toByteArray(Charsets.UTF_8).size in 1..65_536)
        val previous=dao.attempts(scope.lease.storageScope)
        if(previous.any {it.wireContext==scope.wireContext && it.resource==resource && it.state in pendingStates})throw EnergyAccessFailure("pending_operation")
        if(dao.pendingCount(scope.lease.storageScope)>=64)throw EnergyAccessFailure("pending_limit")
        val fingerprint=fingerprint(method,path,body,ifMatch,scope.wireContext,scope.lease.generation)
        EnergyAttemptEntity(UUID.randomUUID().toString(),scope.lease.storageScope,scope.wireContext,scope.lease.generation,resource,kind,method,path,body,ifMatch,
            fingerprint,now,false,"prepared",0,null,null).also {row->
                dao.insert(row)
                previous.filter {it.state !in pendingStates}.drop(99).forEach {dao.removeAttempt(it.id)}
            }
    }
    suspend fun open(scope:EnergyScope,id:String):EnergyAttemptEntity=db.withTransaction {
        requireScope(scope)
        val row=checkNotNull(dao.attempt(id))
        if(row.ownerScope!=scope.lease.storageScope || row.wireContext!=scope.wireContext)throw EnergyAccessFailure("stale_context")
        require(row.leaseGeneration>0 && row.state in pendingStates && row.fingerprint==fingerprint(row.method,row.path,row.body,row.ifMatch,row.wireContext,row.leaseGeneration))
        row
    }
    suspend fun attempted(scope:EnergyScope,expected:EnergyAttemptEntity)=db.withTransaction {
        val row=open(scope,expected.id);check(row==expected)
        dao.update(row.copy(attempted=true,state="unknown"))
    }
    suspend fun finish(scope:EnergyScope,id:String,state:String,response:String?,code:String?,retryAt:Long=0):EnergyAttemptEntity=db.withTransaction {
        val row=open(scope,id)
        require(state in setOf("unknown","succeeded","rejected","needs_reconciliation") && retryAt>=0)
        require(response==null || response.toByteArray(Charsets.UTF_8).size<=1_048_576)
        row.copy(state=state,responseJson=response,errorCode=code,retryAt=retryAt).also {dao.update(it)}
    }
    suspend fun discardUnsent(scope:EnergyScope,id:String)=db.withTransaction {
        val row=open(scope,id);check(!row.attempted);dao.removeAttempt(id)
    }
    companion object {
        val pendingStates=setOf("prepared","unknown","needs_reconciliation")
        private fun fingerprint(method:String,path:String,body:String,ifMatch:String?,context:String,lease:Long)=
            MessageDigest.getInstance("SHA-256").digest(listOf(method,path,body,ifMatch?:"",context,lease.toString()).joinToString("\u0000").toByteArray(Charsets.UTF_8))
                .joinToString(""){"%02x".format(it)}
    }
}

internal fun energyGuards(db:SupportSQLiteDatabase) {
    val fixed=listOf("id","ownerScope","wireContext","leaseGeneration","resource","kind","method","path","body","ifMatch","fingerprint","createdAt")
        .joinToString(" OR "){"NEW.$it IS NOT OLD.$it"}
    db.execSQL("CREATE TRIGGER IF NOT EXISTS energy_attempt_frozen BEFORE UPDATE ON energy_attempts WHEN $fixed OR (OLD.attempted=1 AND NEW.attempted=0) BEGIN SELECT RAISE(ABORT,'immutable energy request'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS energy_attempt_pending_no_delete BEFORE DELETE ON energy_attempts WHEN OLD.attempted=1 AND OLD.state IN ('prepared','unknown','needs_reconciliation') BEGIN SELECT RAISE(ABORT,'unresolved energy request'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS energy_version_immutable BEFORE UPDATE ON energy_cache WHEN OLD.kind='version' AND (NEW.ownerScope IS NOT OLD.ownerScope OR NEW.wireContext IS NOT OLD.wireContext OR NEW.kind IS NOT OLD.kind OR NEW.recordId IS NOT OLD.recordId OR NEW.revision IS NOT OLD.revision OR NEW.wire IS NOT OLD.wire) BEGIN SELECT RAISE(ABORT,'immutable cached energy'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS energy_version_no_replace BEFORE INSERT ON energy_cache WHEN NEW.kind='version' AND EXISTS (SELECT 1 FROM energy_cache old WHERE old.ownerScope=NEW.ownerScope AND old.wireContext=NEW.wireContext AND old.kind=NEW.kind AND old.recordId=NEW.recordId AND (old.revision IS NOT NEW.revision OR old.wire IS NOT NEW.wire)) BEGIN SELECT RAISE(ABORT,'immutable cached energy'); END")
}
val MIGRATION_24_25=object:Migration(24,25) {
    override fun migrate(db:SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS energy_cache (ownerScope TEXT NOT NULL,wireContext TEXT NOT NULL,kind TEXT NOT NULL,recordId TEXT NOT NULL,revision INTEGER NOT NULL,wire TEXT NOT NULL,fetchedAt INTEGER NOT NULL,PRIMARY KEY(ownerScope,wireContext,kind,recordId),FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE TABLE IF NOT EXISTS energy_attempts (id TEXT NOT NULL PRIMARY KEY,ownerScope TEXT NOT NULL,wireContext TEXT NOT NULL,leaseGeneration INTEGER NOT NULL,resource TEXT NOT NULL,kind TEXT NOT NULL,method TEXT NOT NULL,path TEXT NOT NULL,body TEXT NOT NULL,ifMatch TEXT,fingerprint TEXT NOT NULL,createdAt INTEGER NOT NULL,attempted INTEGER NOT NULL,state TEXT NOT NULL,retryAt INTEGER NOT NULL,responseJson TEXT,errorCode TEXT,FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_energy_attempts_ownerScope_wireContext_resource_createdAt ON energy_attempts(ownerScope,wireContext,resource,createdAt)")
        db.execSQL("CREATE TABLE IF NOT EXISTS energy_backoff (ownerScope TEXT NOT NULL,wireContext TEXT NOT NULL,retryAt INTEGER NOT NULL,PRIMARY KEY(ownerScope,wireContext),FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        energyGuards(db)
    }
}
