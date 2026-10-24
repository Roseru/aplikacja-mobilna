package pl.roseru.kalorie.data

import android.content.Context
import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.math.BigDecimal
import java.time.Instant
import java.util.UUID

/** Exact current proposal is separate from immutable attempted outbox/request bytes. */
@Entity(tableName = "canonical_domains", primaryKeys = ["ownerScope", "entityType", "entityId"],
    foreignKeys = [ForeignKey(entity = LocalOwnerEntity::class, parentColumns = ["storageScope"],
        childColumns = ["ownerScope"], onDelete = ForeignKey.RESTRICT)],
    indices = [Index(value = ["ownerScope", "entityType", "localId"], unique = true)])
data class CanonicalDomainState(val ownerScope: String, val entityType: String, val entityId: String,
    val localId: String, val wirePayload: String?, val wireContext: String, val serverRevision: Int = 0,
    val deleted: Boolean = false) {
    override fun toString() = "CanonicalDomainState(redacted)"
}

@Entity(tableName = "canonical_goal_timelines", foreignKeys = [ForeignKey(entity = LocalOwnerEntity::class,
    parentColumns = ["storageScope"], childColumns = ["ownerScope"], onDelete = ForeignKey.RESTRICT)])
data class CanonicalGoalTimeline(@PrimaryKey val ownerScope: String, val wireContext: String, val revision: Int) {
    override fun toString() = "CanonicalGoalTimeline(redacted)"
}

@Dao interface CanonicalDomainDao {
    @Query("SELECT * FROM canonical_domains WHERE ownerScope=:owner AND entityType=:type AND entityId=:id")
    suspend fun state(owner: String, type: String, id: String): CanonicalDomainState?
    @Query("SELECT * FROM canonical_domains WHERE ownerScope=:owner AND entityType=:type AND localId=:id")
    suspend fun local(owner: String, type: String, id: String): CanonicalDomainState?
    @Query("SELECT * FROM canonical_domains WHERE ownerScope=:owner AND entityType=:type AND localId=:id")
    fun observeLocal(owner: String, type: String, id: String): kotlinx.coroutines.flow.Flow<CanonicalDomainState?>
    @Upsert suspend fun save(state: CanonicalDomainState)
    @Query("DELETE FROM canonical_domains WHERE ownerScope=:owner AND entityType=:type AND entityId=:id")
    suspend fun retire(owner:String,type:String,id:String)
    @Query("SELECT * FROM canonical_goal_timelines WHERE ownerScope=:owner")
    suspend fun timeline(owner: String): CanonicalGoalTimeline?
    @Upsert suspend fun save(timeline: CanonicalGoalTimeline)
    @Query("SELECT * FROM outbox WHERE ownerScope=:owner AND entityType=:type AND entityId=:id AND wireFormat='sync-v1' AND status NOT IN ('acked','superseded','local_only') ORDER BY rowid")
    suspend fun operations(owner: String, type: String, id: String): List<OutboxEntity>
    @Query("SELECT * FROM outbox WHERE ownerScope=:owner AND entityType IN ('profile','goal','diary_day','product_draft') AND wireFormat='sync-v1' AND status NOT IN ('acked','superseded','local_only') ORDER BY rowid")
    suspend fun unsettled(owner: String): List<OutboxEntity>
}

/** Caller owns the Room transaction containing the projection and this producer. */
internal class CanonicalDomainEditor(private val db: CalorieDatabase, private val context: Context, private val lease: OwnerLease) {
    private val dao = db.domainSyncDao()
    private val schema get() = CanonicalMealRows.schema(context)
    private suspend fun binding(): AccountBindingEntity? {
        LocalOwnerStore(db).requireCurrent(lease)
        if (db.ownerDao().byScope(lease.storageScope)?.kind != "account") return null
        return db.bootstrapDao().binding(lease.storageScope)?.takeUnless { it.requiresRecovery }
    }

    /** Existing legacy projections are not silently converted or assigned a server identity. */
    suspend fun save(type: String, localId: String, payload: String?, allowNew: Boolean): Boolean {
        require(type in PrivateDomainsWire.types && type != "goal")
        val owner = lease.storageScope
        val old = dao.local(owner, type, localId)
        val binding = binding()
        if (old == null && (!allowNew || binding == null)) return false
        val wireContext = old?.wireContext ?: CanonicalMealRows.context(checkNotNull(binding))
        val current = binding != null && CanonicalMealRows.context(binding) == wireContext
        val id = old?.entityId ?: localId
        check(old?.deleted != true || payload == null) // A retired identity is never resurrected.
        val value = try { payload?.let { PrivateDomainsWire.read(type, it, schema) } }
            catch (_: SyncWireException) { return false }
        val queue = dao.operations(owner, type, id)
        val base = old?.serverRevision?.takeIf { it > 0 }
        val status = when {
            !current -> "waiting_recovery"
            queue.any { it.attempted } -> "waiting_revision"
            value == null && base == null -> "local_only"
            // A replacement live profile waits until its predecessor's delete is acknowledged.
            type == "profile" && dao.unsettled(owner).any { it.entityType == "profile" && it.entityId != id } -> "waiting_profile"
            else -> "pending"
        }
        val operationId = UUID.randomUUID().toString()
        val epoch = StrictJson.read(wireContext.toByteArray()).getString("sync_epoch")
        val wire = if (status == "pending") PrivateDomainsWire.operation(operationId, type, id, epoch, base, value, schema) else null
        queue.filter { !it.attempted }.forEach { db.dao().updateOperation(it.copy(status = "superseded")) }
        dao.save(CanonicalDomainState(owner, type, id, localId, value ?: old?.wirePayload, wireContext,
            old?.serverRevision ?: 0, value == null))
        db.dao().enqueue(OutboxEntity(operationId, owner, type, id, if (value == null) "delete" else "upsert", base,
            value ?: "null", Instant.now().toString(), status, "sync-v1", wire, wireContext))
        return true
    }

    suspend fun profile(row: ProfileEntity, isNew: Boolean): Boolean = save("profile", row.id,
        StrictJson.canonical(JSONObject().put("pseudonym", row.nickname).put("height_cm", decimal(row.heightCm))
            .put("activity_class", activity(row.activityClass)).put("time_zone", row.zoneId)), isNew)

    suspend fun day(row: DiaryDayEntity, zone: String, isNew: Boolean): Boolean = save("diary_day", row.id,
        StrictJson.canonical(JSONObject().put("local_date", row.localDate).put("declared_complete", row.declaredComplete)
            .put("time_zone", zone)), isNew)

    suspend fun product(row: ProductEntity, isNew: Boolean = true): Boolean {
        val value = row.wirePayload?.let { StrictJson.read(it.toByteArray()) } ?: JSONObject()
            .put("brand", JSONObject.NULL).put("variant", JSONObject.NULL).put("package_quantity", JSONObject.NULL)
            .put("density_g_per_ml", JSONObject.NULL).put("density_source", JSONObject.NULL)
        val payload = StrictJson.canonical(value.put("name", row.name).put("basis_unit", row.unit)
            .put("nutrition_per_100", JSONObject().put("energy_kcal", decimal(row.kcal)).put("protein_g", decimal(row.protein))
                .put("fat_g", decimal(row.fat)).put("carbs_g", decimal(row.carbs)))
            .put("source_description", row.source))
        return save("product_draft", row.id, payload, isNew)
    }

    /** A retained local historical goal is not necessarily an entity in the current server epoch. */
    suspend fun goalPredecessor(previous:GoalEntity?):GoalEntity? {
        if(previous==null)return null
        val binding=binding() ?: return previous // Guest/recovery work keeps its local historical relationship.
        return previous.takeIf {legalGoalReference(it,CanonicalMealRows.context(binding))!=null}
    }
    private suspend fun legalGoalReference(previous:GoalEntity,wireContext:String):CanonicalDomainState? {
        val state=dao.local(lease.storageScope,"goal",previous.id) ?: return null
        if(state.wireContext!=wireContext || state.deleted)return null
        val ownPending=dao.operations(lease.storageScope,"goal",state.entityId).any {
            it.wireContext==wireContext && it.action=="upsert" && it.status in setOf("pending","waiting_timeline","waiting_revision")}
        return state.takeIf {it.serverRevision>0 || ownPending}
    }

    /** New immutable goal versions serialize against the last confirmed axis, in creation order. */
    suspend fun goal(row: GoalEntity, previous: GoalEntity?, selectedAim: DietAim? = null): Boolean {
        val binding = binding() ?: return false
        val wireContext = CanonicalMealRows.context(binding)
        val reference=previous?.let {legalGoalReference(it,wireContext) ?: return false}
        val known = dao.timeline(lease.storageScope) ?: run {
            val gate = try { MealPushStore(db, schema).gate(lease) } catch (_: IllegalStateException) { return false }
            CanonicalGoalTimeline(lease.storageScope, wireContext, Math.toIntExact(checkNotNull(gate.run.timelineRevision)))
                .also { dao.save(it) }
        }
        if (known.wireContext != wireContext) return false
        val pending = dao.unsettled(lease.storageScope).filter { it.entityType == "goal" }
        val base = try { Math.addExact(known.revision, pending.size) } catch (_: ArithmeticException) { return false }
        if (base == Int.MAX_VALUE) return false
        val profile = db.dao().currentProfile(lease.storageScope)
        val estimate=row.estimateJson?.let(MaintenanceEstimate::read)
        val value = JSONObject().put("effective_from", row.validFrom).put("decided_at", row.decidedAt)
            .put("time_zone", row.zoneId).put("goal_type", when (selectedAim?.name ?: profile?.dietAim ?: DietAim.MAINTAIN.name) {
                DietAim.REDUCE.name -> "reduce"; DietAim.SURPLUS.name -> "gain"; else -> "maintain" })
            .put("energy_kcal", decimal(row.kcal)).put("protein_g", decimal(row.protein)).put("fat_g", decimal(row.fat))
            .put("carbs_g", decimal(row.carbs)).put("activity_class", activity(estimate?.input?.activity?.name ?: profile?.activityClass ?: ActivityClass.GARRISON.name))
            .put("estimate", estimate?.json() ?: JSONObject.NULL).put("timeline_base_revision", base).put("reason", row.reason)
            .put("correction_of", reference?.entityId ?: JSONObject.NULL)
        val payload = try { PrivateDomainsWire.read("goal", StrictJson.canonical(value), schema) }
            catch (_: SyncWireException) { return false }
        val operationId = UUID.randomUUID().toString()
        val wire = PrivateDomainsWire.operation(operationId, "goal", row.id, binding.syncEpoch, null, payload, schema, base)
        dao.save(CanonicalDomainState(lease.storageScope, "goal", row.id, row.id, payload, wireContext))
        db.dao().enqueue(OutboxEntity(operationId, lease.storageScope, "goal", row.id, "upsert", null, payload,
            Instant.now().toString(), if (pending.isEmpty()) "pending" else "waiting_timeline", "sync-v1", wire, wireContext))
        return true
    }

    companion object {
        private fun decimal(value: Double?): Any = value?.let { ContractDecimal.canonical(BigDecimal.valueOf(it)) } ?: JSONObject.NULL
        private fun activity(value: String) = when (value) {
            ActivityClass.GARRISON.name -> "stationary"; ActivityClass.LINE.name -> "line"; ActivityClass.COMMANDO.name -> "commando"
            else -> error("Unknown local activity")
        }
    }
}

val MIGRATION_17_18 = object : Migration(17, 18) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE canonical_domains (ownerScope TEXT NOT NULL, entityType TEXT NOT NULL, entityId TEXT NOT NULL, localId TEXT NOT NULL, wirePayload TEXT, wireContext TEXT NOT NULL, serverRevision INTEGER NOT NULL, deleted INTEGER NOT NULL, PRIMARY KEY(ownerScope,entityType,entityId), FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE UNIQUE INDEX index_canonical_domains_ownerScope_entityType_localId ON canonical_domains(ownerScope,entityType,localId)")
        db.execSQL("CREATE TABLE canonical_goal_timelines (ownerScope TEXT NOT NULL PRIMARY KEY, wireContext TEXT NOT NULL, revision INTEGER NOT NULL, FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        // Only proven server projections become canonical. Legacy outbox and every old table stay byte/value intact.
        db.execSQL("INSERT INTO canonical_domains SELECT ownerScope,entityType,entityId,localId,payload,wireContext,knownRevision,deleted FROM server_diary_records WHERE entityType IN ('profile','goal','diary_day','product_draft') AND disposition='applied' AND localId IS NOT NULL")
        db.execSQL("INSERT INTO canonical_goal_timelines SELECT ownerScope,wireContext,timelineRevision FROM server_diary_applications a WHERE a.rowid=(SELECT MAX(b.rowid) FROM server_diary_applications b WHERE b.ownerScope=a.ownerScope)")
    }
}
