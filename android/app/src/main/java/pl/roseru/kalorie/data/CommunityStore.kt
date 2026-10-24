package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import pl.roseru.kalorie.community.*
import java.security.MessageDigest
import java.util.UUID

@Entity(tableName="community_cache",primaryKeys=["ownerScope","wireContext","productId","revision"],
    foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT)],
    indices=[Index(value=["ownerScope","wireContext","fetchedAt"])])
data class CommunityCacheEntity(val ownerScope:String,val wireContext:String,val productId:String,val revision:Int,
    val searchName:String,val productJson:String,val feedbackJson:String?,val fetchedAt:Long) {
    override fun toString()="CommunityCacheEntity(redacted)"
}

@Entity(tableName="community_attempts",foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,
    parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT)],
    indices=[Index(value=["ownerScope","wireContext","resource","createdAt"])])
data class CommunityAttemptEntity(@PrimaryKey val id:String,val ownerScope:String,val wireContext:String,
    val resource:String,val kind:String,val method:String,val path:String,val body:String?,val ifMatch:String?,
    val fingerprint:String,val createdAt:Long,val attempted:Boolean,val state:String,val retryAt:Long,
    val responseJson:String?,val errorCode:String?) {
    override fun toString()="CommunityAttemptEntity(redacted)"
}

@Entity(tableName="community_backoff",primaryKeys=["ownerScope","wireContext"],
    foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT)])
data class CommunityBackoffEntity(val ownerScope:String,val wireContext:String,val retryAt:Long)

@Dao interface CommunityDao {
    @Query("SELECT * FROM community_cache WHERE ownerScope=:owner AND wireContext=:context ORDER BY fetchedAt DESC, productId, revision DESC")
    suspend fun cached(owner:String,context:String):List<CommunityCacheEntity>
    @Query("SELECT * FROM community_cache WHERE ownerScope=:owner AND wireContext=:context AND productId=:id AND revision=:revision")
    suspend fun cached(owner:String,context:String,id:String,revision:Int):CommunityCacheEntity?
    @Upsert suspend fun save(row:CommunityCacheEntity)
    @Query("DELETE FROM community_cache WHERE ownerScope=:owner AND wireContext=:context AND productId=:id AND revision=:revision")
    suspend fun removeCached(owner:String,context:String,id:String,revision:Int)
    @Query("SELECT * FROM community_attempts WHERE ownerScope=:owner AND wireContext=:context ORDER BY createdAt DESC,id")
    suspend fun attempts(owner:String,context:String):List<CommunityAttemptEntity>
    @Query("SELECT * FROM community_attempts WHERE ownerScope=:owner AND wireContext<>:context AND state IN ('prepared','unknown','needs_reconciliation') ORDER BY createdAt DESC,id LIMIT 64")
    suspend fun archivedAttempts(owner:String,context:String):List<CommunityAttemptEntity>
    @Query("SELECT * FROM community_attempts WHERE id=:id") suspend fun attempt(id:String):CommunityAttemptEntity?
    @Insert suspend fun insert(row:CommunityAttemptEntity)
    @Update suspend fun update(row:CommunityAttemptEntity)
    @Query("DELETE FROM community_attempts WHERE id=:id") suspend fun removeAttempt(id:String)
    @Query("SELECT * FROM community_backoff WHERE ownerScope=:owner AND wireContext=:context")
    suspend fun backoff(owner:String,context:String):CommunityBackoffEntity?
    @Upsert suspend fun save(row:CommunityBackoffEntity)
    @Query("SELECT * FROM canonical_domains WHERE ownerScope=:owner AND wireContext=:context AND entityType='product_draft' AND deleted=0 AND serverRevision>0 AND wirePayload IS NOT NULL ORDER BY localId")
    suspend fun publicationDrafts(owner:String,context:String):List<CanonicalDomainState>
}

@ConsistentCopyVisibility
data class CommunityScope internal constructor(val lease:OwnerLease,val binding:AccountBindingEntity,val wireContext:String) {
    override fun toString()="CommunityScope(redacted)"
}
data class PublicationDraft(val id:String,val revision:Int,val localId:String,val name:String,val payload:String) {
    override fun toString()="PublicationDraft(redacted)"
}

/** All state belongs to one account/context. No tokens, photos or private diary enter public requests. */
class CommunityStore(private val db:CalorieDatabase) {
    private val dao=db.communityDao()
    private val owners=LocalOwnerStore(db)
    suspend fun scope(lease:OwnerLease):CommunityScope?=db.withTransaction {
        owners.requireCurrent(lease)
        if(db.ownerDao().byScope(lease.storageScope)?.kind!="account")return@withTransaction null
        db.bootstrapDao().binding(lease.storageScope)?.let {CommunityScope(lease,it,CanonicalMealRows.context(it))}
    }
    suspend fun requireScope(scope:CommunityScope) {
        owners.requireCurrent(scope.lease)
        check(db.bootstrapDao().binding(scope.lease.storageScope)==scope.binding)
    }
    suspend fun cached(scope:CommunityScope,query:String=""):List<CommunityProduct> = db.withTransaction {
        requireScope(scope)
        val search=pl.roseru.kalorie.core.normalizeSearch(query)
        dao.cached(scope.lease.storageScope,scope.wireContext).asSequence().filter {search.isEmpty() || it.searchName.contains(search)}
            .distinctBy {it.productId}.mapNotNull {try{CommunityProtocol.product(it.productJson.toByteArray())}catch(_:Exception){null}}
            .filter {it.visible}.take(100).toList()
    }
    suspend fun cache(scope:CommunityScope,products:List<CommunityProduct>,now:Long)=db.withTransaction {
        requireScope(scope)
        products.forEach { product ->
            val old=dao.cached(scope.lease.storageScope,scope.wireContext,product.ref.id,product.ref.revision)
            dao.save(CommunityCacheEntity(scope.lease.storageScope,scope.wireContext,product.ref.id,product.ref.revision,
                pl.roseru.kalorie.core.normalizeSearch((listOf(product.name)+product.aliases).joinToString(" ")),
                product.stored(),old?.feedbackJson,now))
        }
        // A bounded fragment, never a promise that the whole public catalogue is installed.
        var bytes=0L
        dao.cached(scope.lease.storageScope,scope.wireContext).forEachIndexed { index,row ->
            bytes+=row.productJson.toByteArray().size+(row.feedbackJson?.toByteArray()?.size?:0)
            if(index>=100 || bytes>4L*1024*1024)dao.removeCached(row.ownerScope,row.wireContext,row.productId,row.revision)
        }
    }
    suspend fun saveFeedback(scope:CommunityScope,product:PublicProductRef,bytes:ByteArray)=db.withTransaction {
        requireScope(scope);val feedback=CommunityProtocol.feedback(bytes)
        val row=dao.cached(scope.lease.storageScope,scope.wireContext,product.id,product.revision)?:return@withTransaction
        require(feedback.product.id==CommunityProtocol.product(row.productJson.toByteArray()).canonicalRef.id)
        dao.save(row.copy(feedbackJson=bytes.toString(Charsets.UTF_8)))
    }
    suspend fun feedback(scope:CommunityScope,product:PublicProductRef):CommunityFeedback?=db.withTransaction {
        requireScope(scope)
        dao.cached(scope.lease.storageScope,scope.wireContext,product.id,product.revision)?.feedbackJson?.let {
            try{CommunityProtocol.feedback(it.toByteArray())}catch(_:Exception){null}
        }
    }
    suspend fun drafts(scope:CommunityScope):List<PublicationDraft> = db.withTransaction {
        requireScope(scope)
        buildList {for(row in dao.publicationDrafts(scope.lease.storageScope,scope.wireContext)) {
                val id=row.entityId
                // Do not publish a revision while an edit/delete is still queued or uncertain.
                if(db.domainSyncDao().operations(scope.lease.storageScope,"product_draft",id).isNotEmpty())continue
                val payload=checkNotNull(row.wirePayload)
                val name=try{CommunityProtocol.read(payload.toByteArray()).getString("name")}catch(_:Exception){continue}
                add(PublicationDraft(id,row.serverRevision,row.localId,name,payload))
        }}
    }
    suspend fun attempts(scope:CommunityScope):List<CommunityAttemptEntity> = db.withTransaction {
        requireScope(scope);dao.attempts(scope.lease.storageScope,scope.wireContext)+dao.archivedAttempts(scope.lease.storageScope,scope.wireContext)
    }
    suspend fun retryAt(scope:CommunityScope):Long=db.withTransaction {
        requireScope(scope);dao.backoff(scope.lease.storageScope,scope.wireContext)?.retryAt?:0
    }
    suspend fun defer(scope:CommunityScope,until:Long)=db.withTransaction {
        requireScope(scope)
        dao.save(CommunityBackoffEntity(scope.lease.storageScope,scope.wireContext,maxOf(until,retryAt(scope))))
    }
    suspend fun prepare(scope:CommunityScope,resource:String,kind:String,method:String,path:String,body:String?,ifMatch:String?,now:Long):CommunityAttemptEntity=db.withTransaction {
        requireScope(scope);check(!scope.binding.requiresRecovery)
        require(kind in setOf("publish","vote","withdraw","report"))
        require(method in setOf("POST","PUT","DELETE") && path.startsWith("/products"))
        require(body==null || body.toByteArray().size<=1_048_576)
        val rows=dao.attempts(scope.lease.storageScope,scope.wireContext)
        check(rows.none {it.resource==resource && it.state in pendingStates})
        check(rows.count {it.state in pendingStates}<64)
        val fingerprint=hash(listOf(method,path,body?:"",ifMatch?:"",scope.wireContext).joinToString("\u0000"))
        CommunityAttemptEntity(UUID.randomUUID().toString(),scope.lease.storageScope,scope.wireContext,resource,kind,
            method,path,body,ifMatch,fingerprint,now,false,"prepared",0,null,null).also {
            dao.insert(it)
            // Pending/unknown outcomes are never evicted. Bound only completed history.
            rows.filter {row->row.state !in pendingStates}.drop(99).forEach {row->dao.removeAttempt(row.id)}
        }
    }
    suspend fun open(scope:CommunityScope,id:String):CommunityAttemptEntity=db.withTransaction {
        requireScope(scope);val row=checkNotNull(dao.attempt(id))
        require(row.ownerScope==scope.lease.storageScope && row.wireContext==scope.wireContext && row.state in pendingStates)
        require(hash(listOf(row.method,row.path,row.body?:"",row.ifMatch?:"",row.wireContext).joinToString("\u0000"))==row.fingerprint)
        row
    }
    suspend fun attempted(scope:CommunityScope,row:CommunityAttemptEntity)=db.withTransaction {
        val current=open(scope,row.id);check(current==row)
        dao.update(current.copy(attempted=true,state="unknown"))
    }
    suspend fun finish(scope:CommunityScope,id:String,state:String,response:String?,code:String?,retryAt:Long=0)=db.withTransaction {
        val row=open(scope,id);require(state in setOf("unknown","succeeded","rejected","needs_reconciliation"))
        require(response==null || response.toByteArray().size<=65_536)
        dao.update(row.copy(state=state,responseJson=response,errorCode=code,retryAt=retryAt))
    }
    suspend fun discardUnsent(scope:CommunityScope,id:String)=db.withTransaction {
        val row=open(scope,id);check(!row.attempted);dao.removeAttempt(row.id)
    }
    companion object {
        val pendingStates=setOf("prepared","unknown","needs_reconciliation")
        private fun hash(text:String)=MessageDigest.getInstance("SHA-256").digest(text.toByteArray()).joinToString(""){"%02x".format(it)}
    }
}

val MIGRATION_22_23=object:Migration(22,23) {
    override fun migrate(db:SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS community_cache (ownerScope TEXT NOT NULL,wireContext TEXT NOT NULL,productId TEXT NOT NULL,revision INTEGER NOT NULL,searchName TEXT NOT NULL,productJson TEXT NOT NULL,feedbackJson TEXT,fetchedAt INTEGER NOT NULL,PRIMARY KEY(ownerScope,wireContext,productId,revision),FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_community_cache_ownerScope_wireContext_fetchedAt ON community_cache(ownerScope,wireContext,fetchedAt)")
        db.execSQL("CREATE TABLE IF NOT EXISTS community_attempts (id TEXT NOT NULL PRIMARY KEY,ownerScope TEXT NOT NULL,wireContext TEXT NOT NULL,resource TEXT NOT NULL,kind TEXT NOT NULL,method TEXT NOT NULL,path TEXT NOT NULL,body TEXT,ifMatch TEXT,fingerprint TEXT NOT NULL,createdAt INTEGER NOT NULL,attempted INTEGER NOT NULL,state TEXT NOT NULL,retryAt INTEGER NOT NULL,responseJson TEXT,errorCode TEXT,FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_community_attempts_ownerScope_wireContext_resource_createdAt ON community_attempts(ownerScope,wireContext,resource,createdAt)")
        db.execSQL("CREATE TABLE IF NOT EXISTS community_backoff (ownerScope TEXT NOT NULL,wireContext TEXT NOT NULL,retryAt INTEGER NOT NULL,PRIMARY KEY(ownerScope,wireContext),FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
    }
}
