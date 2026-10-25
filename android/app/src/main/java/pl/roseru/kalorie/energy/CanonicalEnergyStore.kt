package pl.roseru.kalorie.energy

import androidx.room.*
import androidx.room.withTransaction
import pl.roseru.kalorie.core.sync.SyncProtocolScope
import pl.roseru.kalorie.data.*

/** Complete immutable axis from opt-in sync; independent of the bounded REST preview cache. */
@Entity(tableName="canonical_energy_versions",primaryKeys=["ownerScope","wireContext","entityId"],
    foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT),
        ForeignKey(entity=ServerSnapshotRun::class,parentColumns=["id"],childColumns=["sourceRunId"],onDelete=ForeignKey.RESTRICT)],
    indices=[Index(value=["ownerScope","wireContext","revision"],unique=true),Index("sourceRunId")])
data class CanonicalEnergyVersion(val ownerScope:String,val wireContext:String,val entityId:String,
    val revision:Int,val wire:String,val sourceRunId:String,val recordedAt:Long) {
    override fun toString()="CanonicalEnergyVersion(redacted)"
}

@Dao interface CanonicalEnergyDao {
    @Query("SELECT * FROM canonical_energy_versions WHERE ownerScope=:owner AND wireContext=:context ORDER BY revision")
    suspend fun all(owner:String,context:String):List<CanonicalEnergyVersion>
    @Query("SELECT * FROM canonical_energy_versions WHERE ownerScope=:owner AND wireContext=:context ORDER BY revision DESC LIMIT :limit")
    suspend fun latest(owner:String,context:String,limit:Int=1000):List<CanonicalEnergyVersion>
    @Query("SELECT * FROM canonical_energy_versions WHERE ownerScope=:owner AND wireContext=:context AND entityId=:id")
    suspend fun version(owner:String,context:String,id:String):CanonicalEnergyVersion?
    @Insert suspend fun insert(row:CanonicalEnergyVersion)
}

/** Invoked inside full-copy commit. Absence cannot delete immutable history in the same context. */
internal class CanonicalEnergyStore(private val db:CalorieDatabase,private val now:()->Long=System::currentTimeMillis) {
    suspend fun applyFull(lease:OwnerLease,binding:AccountBindingEntity,run:ServerSnapshotRun,versions:List<EnergyVersion>)=db.withTransaction {
        LocalOwnerStore(db).requireCurrent(lease)
        check(db.bootstrapDao().binding(lease.storageScope)==binding && run.ownerScope==lease.storageScope && run.state=="complete" &&
            run.protocolScope==SyncProtocolScope.ENERGY_V1.installationId && run.accountId==binding.accountId &&
            run.accountGeneration==binding.accountGeneration && run.syncEpoch==binding.syncEpoch && run.contextRevision==binding.contextRevision)
        val context=CanonicalMealRows.context(binding)
        val incoming=versions.associateBy {it.id}
        check(incoming.size==versions.size && versions.map {it.revision}.distinct().size==versions.size)
        val previous=db.canonicalEnergyDao().all(lease.storageScope,context)
        check(previous.all {old->incoming[old.entityId]?.let {it.revision==old.revision && it.wire==old.wire}==true})
        val preview=db.energyDao().cache(lease.storageScope,context).filter {it.kind=="version"}
        preview.forEach {old->incoming[old.recordId]?.let {check(it.revision==old.revision && it.wire==old.wire)}}
        val existing=previous.map {it.entityId}.toSet()
        val fresh=versions.filter {it.id !in existing}
        fresh.forEach {value->db.canonicalEnergyDao().insert(CanonicalEnergyVersion(lease.storageScope,context,value.id,
            value.revision,value.wire,run.id,now()))}
        if(fresh.isNotEmpty()) {
            val scope=EnergyScope(CommunityScope(lease,binding,context))
            EnergyStore(db).invalidateState(scope)
        }
    }
}
