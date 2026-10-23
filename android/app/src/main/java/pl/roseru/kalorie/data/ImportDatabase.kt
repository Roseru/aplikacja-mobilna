package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/** Immutable source bytes and decisions are evidence; mutable progress never replaces them. */
@Entity(tableName="import_plans", indices=[Index(value=["sourceScope","targetScope","kind","fingerprint","wireContext"],unique=true),Index("targetScope")])
data class ImportPlan(@PrimaryKey val id:String,val sourceScope:String,val targetScope:String,
    val targetAccountId:String,val issuer:String,val subject:String,val kind:String,val fingerprint:String,
    val wireContext:String,val createdAt:String,val approvedAt:String?=null,val state:String="draft") {
    override fun toString()="ImportPlan(redacted)"
}
@Entity(tableName="guest_assignments",foreignKeys=[ForeignKey(entity=ImportPlan::class,parentColumns=["id"],childColumns=["planId"],onDelete=ForeignKey.RESTRICT)],indices=[Index("planId")])
data class GuestAssignment(@PrimaryKey val sourceScope:String,val targetScope:String,val accountId:String,
    val issuer:String,val subject:String,val planId:String,val consentAt:String) {
    override fun toString()="GuestAssignment(redacted)"
}
@Entity(tableName="import_sources",primaryKeys=["planId","entityType","sourceId"],foreignKeys=[ForeignKey(entity=ImportPlan::class,parentColumns=["id"],childColumns=["planId"],onDelete=ForeignKey.RESTRICT)],indices=[Index("operationId")])
data class ImportSource(val planId:String,val entityType:String,val sourceId:String,val ordinal:Int,
    val sourceJson:String,val sourceHash:String,val outboxesJson:String,val localId:String,val wireId:String,
    val sourceEpoch:String?=null,val sourceRevision:Int?=null,val sourceOperationId:String?=null,
    val metadataJson:String="{}",val state:String="pending",val decisionCode:String?=null,
    val operationId:String?=null,val appliedPayload:String?=null) {
    override fun toString()="ImportSource(redacted)"
}
@Entity(tableName="import_identities",primaryKeys=["ownerScope","entityType","localId"],
    indices=[Index(value=["ownerScope","entityType","wireId"],unique=true)])
data class ImportIdentity(val ownerScope:String,val entityType:String,val localId:String,val wireId:String,
    val sourceScope:String,val sourceId:String,val reason:String) {
    override fun toString()="ImportIdentity(redacted)"
}
@Entity(tableName="import_item_identities",primaryKeys=["ownerScope","localId"],
    indices=[Index(value=["ownerScope","wireId"],unique=true),Index(value=["ownerScope","mealLocalId"])])
data class ImportItemIdentity(val ownerScope:String,val localId:String,val wireId:String,val mealLocalId:String,
    val sourceId:String) {
    override fun toString()="ImportItemIdentity(redacted)"
}
@Entity(tableName="import_decisions",foreignKeys=[ForeignKey(entity=ImportPlan::class,parentColumns=["id"],childColumns=["planId"],onDelete=ForeignKey.RESTRICT)],indices=[Index("planId")])
data class ImportDecision(@PrimaryKey val id:String,val planId:String,val entityType:String,val sourceId:String,
    val sourceHash:String,val choiceJson:String,val decidedAt:String) {
    override fun toString()="ImportDecision(redacted)"
}
@Entity(tableName="reconciliation_batches",foreignKeys=[ForeignKey(entity=ImportPlan::class,parentColumns=["id"],childColumns=["planId"],onDelete=ForeignKey.RESTRICT),ForeignKey(entity=ServerSnapshotRun::class,parentColumns=["id"],childColumns=["snapshotRunId"],onDelete=ForeignKey.RESTRICT)],indices=[Index("planId"),Index("snapshotRunId")])
data class ReconciliationBatch(@PrimaryKey val id:String,val planId:String,val kind:String,val wireContext:String,
    val snapshotRunId:String,val requestJson:String,val requestHash:String,val originalBatchId:String?,
    val createdAt:String,val attempted:Boolean=false,val responseJson:String?=null,val state:String="pending",val retryAtMillis:Long=0) {
    override fun toString()="ReconciliationBatch(redacted)"
}
@Entity(tableName="reconciliation_evidence",primaryKeys=["planId","kind","identity"],
    foreignKeys=[ForeignKey(entity=ImportPlan::class,parentColumns=["id"],childColumns=["planId"],onDelete=ForeignKey.RESTRICT),ForeignKey(entity=ServerSnapshotRun::class,parentColumns=["id"],childColumns=["runId"],onDelete=ForeignKey.RESTRICT)],indices=[Index("runId")])
data class ReconciliationEvidence(val planId:String,val kind:String,val identity:String,val json:String,val sha256:String,val runId:String) {
    override fun toString()="ReconciliationEvidence(redacted)"
}

@Dao interface ImportDao {
    @Query("SELECT * FROM import_plans WHERE id=:id") suspend fun plan(id:String):ImportPlan?
    @Query("SELECT * FROM import_plans WHERE targetScope=:owner ORDER BY rowid DESC") suspend fun plans(owner:String):List<ImportPlan>
    @Insert suspend fun insert(plan:ImportPlan)
    @Update suspend fun update(plan:ImportPlan)
    @Query("SELECT * FROM guest_assignments WHERE sourceScope=:source") suspend fun assignment(source:String):GuestAssignment?
    @Insert suspend fun insert(assignment:GuestAssignment)
    @Query("SELECT * FROM import_sources WHERE planId=:plan ORDER BY ordinal") suspend fun sources(plan:String):List<ImportSource>
    @Query("SELECT * FROM import_sources WHERE planId=:plan AND entityType=:type AND sourceId=:id") suspend fun source(plan:String,type:String,id:String):ImportSource?
    @Insert suspend fun insert(source:ImportSource)
    @Update suspend fun update(source:ImportSource)
    @Query("SELECT * FROM import_identities WHERE ownerScope=:owner AND entityType=:type AND localId=:id") suspend fun local(owner:String,type:String,id:String):ImportIdentity?
    @Query("SELECT * FROM import_identities WHERE ownerScope=:owner AND entityType=:type AND wireId=:id") suspend fun wire(owner:String,type:String,id:String):ImportIdentity?
    @Query("SELECT * FROM import_identities WHERE ownerScope=:owner") suspend fun identities(owner:String):List<ImportIdentity>
    @Insert suspend fun insert(identity:ImportIdentity)
    @Query("SELECT * FROM import_item_identities WHERE ownerScope=:owner AND mealLocalId=:meal") suspend fun items(owner:String,meal:String):List<ImportItemIdentity>
    @Insert suspend fun insert(identity:ImportItemIdentity)
    @Insert suspend fun insert(decision:ImportDecision)
    @Query("SELECT * FROM import_decisions WHERE planId=:plan ORDER BY rowid") suspend fun decisions(plan:String):List<ImportDecision>
    @Query("SELECT * FROM reconciliation_batches WHERE id=:id") suspend fun batch(id:String):ReconciliationBatch?
    @Query("SELECT * FROM reconciliation_batches WHERE planId=:plan ORDER BY rowid") suspend fun batches(plan:String):List<ReconciliationBatch>
    @Insert suspend fun insert(batch:ReconciliationBatch)
    @Update suspend fun update(batch:ReconciliationBatch)
    @Query("SELECT * FROM reconciliation_evidence WHERE planId=:plan") suspend fun evidence(plan:String):List<ReconciliationEvidence>
    @Insert(onConflict=OnConflictStrategy.IGNORE) suspend fun insert(evidence:ReconciliationEvidence)
}

/** Alias affects local projection only. Wire UUID and all historical bodies remain unchanged. */
internal suspend fun CalorieDatabase.localSyncId(owner:String,type:String,wireId:String):String = importDao().wire(owner,type,wireId)?.localId ?: wireId
internal suspend fun CalorieDatabase.wireSyncId(owner:String,type:String,localId:String):String = importDao().local(owner,type,localId)?.wireId ?: localId
internal suspend fun CalorieDatabase.localMealItems(owner:String,meal:String,wire:pl.roseru.kalorie.core.sync.MealWire):List<MealItemEntity> {
    val aliases=importDao().items(owner,meal).associateBy {it.wireId}
    return CanonicalMealRows.items(meal,wire).map {it.copy(id=aliases[it.id]?.localId ?: it.id)}
}

val MIGRATION_18_19=object:Migration(18,19) {
    override fun migrate(db:SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS import_plans (id TEXT NOT NULL,sourceScope TEXT NOT NULL,targetScope TEXT NOT NULL,targetAccountId TEXT NOT NULL,issuer TEXT NOT NULL,subject TEXT NOT NULL,kind TEXT NOT NULL,fingerprint TEXT NOT NULL,wireContext TEXT NOT NULL,createdAt TEXT NOT NULL,approvedAt TEXT,state TEXT NOT NULL,PRIMARY KEY(id))")
        db.execSQL("CREATE UNIQUE INDEX index_import_plans_sourceScope_targetScope_kind_fingerprint_wireContext ON import_plans(sourceScope,targetScope,kind,fingerprint,wireContext)")
        db.execSQL("CREATE INDEX index_import_plans_targetScope ON import_plans(targetScope)")
        db.execSQL("CREATE TABLE IF NOT EXISTS guest_assignments (sourceScope TEXT NOT NULL,targetScope TEXT NOT NULL,accountId TEXT NOT NULL,issuer TEXT NOT NULL,subject TEXT NOT NULL,planId TEXT NOT NULL,consentAt TEXT NOT NULL,PRIMARY KEY(sourceScope),FOREIGN KEY(planId) REFERENCES import_plans(id) ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX index_guest_assignments_planId ON guest_assignments(planId)")
        db.execSQL("CREATE TABLE IF NOT EXISTS import_sources (planId TEXT NOT NULL,entityType TEXT NOT NULL,sourceId TEXT NOT NULL,ordinal INTEGER NOT NULL,sourceJson TEXT NOT NULL,sourceHash TEXT NOT NULL,outboxesJson TEXT NOT NULL,localId TEXT NOT NULL,wireId TEXT NOT NULL,sourceEpoch TEXT,sourceRevision INTEGER,sourceOperationId TEXT,metadataJson TEXT NOT NULL,state TEXT NOT NULL,decisionCode TEXT,operationId TEXT,appliedPayload TEXT,PRIMARY KEY(planId,entityType,sourceId),FOREIGN KEY(planId) REFERENCES import_plans(id) ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX index_import_sources_operationId ON import_sources(operationId)")
        db.execSQL("CREATE TABLE IF NOT EXISTS import_identities (ownerScope TEXT NOT NULL,entityType TEXT NOT NULL,localId TEXT NOT NULL,wireId TEXT NOT NULL,sourceScope TEXT NOT NULL,sourceId TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(ownerScope,entityType,localId))")
        db.execSQL("CREATE UNIQUE INDEX index_import_identities_ownerScope_entityType_wireId ON import_identities(ownerScope,entityType,wireId)")
        db.execSQL("CREATE TABLE IF NOT EXISTS import_item_identities (ownerScope TEXT NOT NULL,localId TEXT NOT NULL,wireId TEXT NOT NULL,mealLocalId TEXT NOT NULL,sourceId TEXT NOT NULL,PRIMARY KEY(ownerScope,localId))")
        db.execSQL("CREATE UNIQUE INDEX index_import_item_identities_ownerScope_wireId ON import_item_identities(ownerScope,wireId)")
        db.execSQL("CREATE INDEX index_import_item_identities_ownerScope_mealLocalId ON import_item_identities(ownerScope,mealLocalId)")
        db.execSQL("CREATE TABLE IF NOT EXISTS import_decisions (id TEXT NOT NULL,planId TEXT NOT NULL,entityType TEXT NOT NULL,sourceId TEXT NOT NULL,sourceHash TEXT NOT NULL,choiceJson TEXT NOT NULL,decidedAt TEXT NOT NULL,PRIMARY KEY(id),FOREIGN KEY(planId) REFERENCES import_plans(id) ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX index_import_decisions_planId ON import_decisions(planId)")
        db.execSQL("CREATE TABLE IF NOT EXISTS reconciliation_batches (id TEXT NOT NULL,planId TEXT NOT NULL,kind TEXT NOT NULL,wireContext TEXT NOT NULL,snapshotRunId TEXT NOT NULL,requestJson TEXT NOT NULL,requestHash TEXT NOT NULL,originalBatchId TEXT,createdAt TEXT NOT NULL,attempted INTEGER NOT NULL,responseJson TEXT,state TEXT NOT NULL,retryAtMillis INTEGER NOT NULL,PRIMARY KEY(id),FOREIGN KEY(planId) REFERENCES import_plans(id) ON DELETE RESTRICT,FOREIGN KEY(snapshotRunId) REFERENCES server_snapshot_runs(id) ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX index_reconciliation_batches_planId ON reconciliation_batches(planId)")
        db.execSQL("CREATE INDEX index_reconciliation_batches_snapshotRunId ON reconciliation_batches(snapshotRunId)")
        db.execSQL("CREATE TABLE IF NOT EXISTS reconciliation_evidence (planId TEXT NOT NULL,kind TEXT NOT NULL,identity TEXT NOT NULL,json TEXT NOT NULL,sha256 TEXT NOT NULL,runId TEXT NOT NULL,PRIMARY KEY(planId,kind,identity),FOREIGN KEY(planId) REFERENCES import_plans(id) ON DELETE RESTRICT,FOREIGN KEY(runId) REFERENCES server_snapshot_runs(id) ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX index_reconciliation_evidence_runId ON reconciliation_evidence(runId)")
        importGuards(db)
    }
}

internal fun importGuards(db:SupportSQLiteDatabase) {
    db.execSQL("CREATE TRIGGER IF NOT EXISTS import_sources_immutable BEFORE UPDATE OF planId,entityType,sourceId,ordinal,sourceJson,sourceHash,outboxesJson,sourceEpoch,sourceRevision,sourceOperationId ON import_sources WHEN NEW.planId IS NOT OLD.planId OR NEW.entityType IS NOT OLD.entityType OR NEW.sourceId IS NOT OLD.sourceId OR NEW.ordinal IS NOT OLD.ordinal OR NEW.sourceJson IS NOT OLD.sourceJson OR NEW.sourceHash IS NOT OLD.sourceHash OR NEW.outboxesJson IS NOT OLD.outboxesJson OR NEW.sourceEpoch IS NOT OLD.sourceEpoch OR NEW.sourceRevision IS NOT OLD.sourceRevision OR NEW.sourceOperationId IS NOT OLD.sourceOperationId BEGIN SELECT RAISE(ABORT,'immutable import source'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS import_decisions_immutable BEFORE UPDATE ON import_decisions WHEN NEW.id IS NOT OLD.id OR NEW.planId IS NOT OLD.planId OR NEW.entityType IS NOT OLD.entityType OR NEW.sourceId IS NOT OLD.sourceId OR NEW.sourceHash IS NOT OLD.sourceHash OR NEW.choiceJson IS NOT OLD.choiceJson OR NEW.decidedAt IS NOT OLD.decidedAt BEGIN SELECT RAISE(ABORT,'immutable import decision'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS guest_assignment_immutable BEFORE UPDATE ON guest_assignments WHEN NEW.sourceScope IS NOT OLD.sourceScope OR NEW.targetScope IS NOT OLD.targetScope OR NEW.accountId IS NOT OLD.accountId OR NEW.issuer IS NOT OLD.issuer OR NEW.subject IS NOT OLD.subject OR NEW.planId IS NOT OLD.planId OR NEW.consentAt IS NOT OLD.consentAt BEGIN SELECT RAISE(ABORT,'immutable guest assignment'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS reconciliation_batch_immutable BEFORE UPDATE OF id,planId,kind,wireContext,snapshotRunId,requestJson,requestHash,originalBatchId,createdAt ON reconciliation_batches WHEN NEW.id IS NOT OLD.id OR NEW.planId IS NOT OLD.planId OR NEW.kind IS NOT OLD.kind OR NEW.wireContext IS NOT OLD.wireContext OR NEW.snapshotRunId IS NOT OLD.snapshotRunId OR NEW.requestJson IS NOT OLD.requestJson OR NEW.requestHash IS NOT OLD.requestHash OR NEW.originalBatchId IS NOT OLD.originalBatchId OR NEW.createdAt IS NOT OLD.createdAt BEGIN SELECT RAISE(ABORT,'immutable reconciliation envelope'); END")
}
