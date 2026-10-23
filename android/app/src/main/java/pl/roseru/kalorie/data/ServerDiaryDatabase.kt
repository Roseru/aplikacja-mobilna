package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/** Exact last observed server version; a pending local proposal is retained separately. */
@Entity(tableName = "server_diary_records", primaryKeys = ["ownerScope", "entityType", "entityId"], foreignKeys = [
    ForeignKey(entity = LocalOwnerEntity::class, parentColumns = ["storageScope"], childColumns = ["ownerScope"], onDelete = ForeignKey.RESTRICT),
    ForeignKey(entity = ServerSnapshotRun::class, parentColumns = ["id"], childColumns = ["runId"], onDelete = ForeignKey.RESTRICT)
], indices = [Index("runId")])
data class ServerDiaryRecord(val ownerScope: String, val entityType: String, val entityId: String,
    val localId: String?, val wireContext: String, val knownRevision: Int, val deleted: Boolean,
    val absent: Boolean, val payload: String?, val runId: String, val disposition: String) {
    override fun toString() = "ServerDiaryRecord(redacted)"
}

@Entity(tableName = "server_diary_applications", foreignKeys = [
    ForeignKey(entity = LocalOwnerEntity::class, parentColumns = ["storageScope"], childColumns = ["ownerScope"], onDelete = ForeignKey.RESTRICT),
    ForeignKey(entity = ServerSnapshotRun::class, parentColumns = ["id"], childColumns = ["runId"], onDelete = ForeignKey.RESTRICT)
], indices = [Index("ownerScope")])
data class ServerDiaryApplication(@PrimaryKey val runId: String, val ownerScope: String,
    val wireContext: String, val serverTime: String, val timelineRevision: Int,
    val included: Int, val held: Int, val appliedAt: String) {
    override fun toString() = "ServerDiaryApplication(included=$included, held=$held)"
}

@Dao interface ServerDiaryDao {
    @Query("SELECT * FROM server_diary_records WHERE ownerScope=:owner") suspend fun records(owner: String): List<ServerDiaryRecord>
    @Upsert suspend fun save(record: ServerDiaryRecord)
    @Query("DELETE FROM server_diary_records WHERE ownerScope=:owner") suspend fun retireContext(owner:String)
    @Query("SELECT * FROM server_diary_applications WHERE runId=:run") suspend fun application(run: String): ServerDiaryApplication?
    @Query("SELECT * FROM server_diary_applications WHERE ownerScope=:owner ORDER BY rowid DESC LIMIT 1")
    suspend fun latest(owner: String): ServerDiaryApplication?
    @Insert suspend fun insert(application: ServerDiaryApplication)
    @Query("SELECT * FROM outbox WHERE ownerScope=:owner AND status NOT IN ('acked','superseded','local_only') ORDER BY rowid")
    suspend fun unsettled(owner: String): List<OutboxEntity>
    @Query("SELECT ownerScope FROM meals WHERE id=:id") suspend fun mealOwner(id: String): String?
    @Query("SELECT * FROM goals WHERE ownerScope=:owner AND NOT EXISTS (SELECT 1 FROM import_sources si JOIN import_plans pi ON pi.id=si.planId WHERE pi.targetScope=goals.ownerScope AND pi.state IN ('complete','ready_to_apply') AND si.entityType='goal' AND si.sourceId=goals.id AND si.state='acked' AND si.decisionCode='mapped_projection_retired') ORDER BY localSequence,id") suspend fun allGoals(owner: String): List<GoalEntity>
    @Query("SELECT * FROM goals WHERE id=:id") suspend fun goal(id: String): GoalEntity?
    @Query("SELECT * FROM products WHERE id=:id") suspend fun product(id: String): ProductEntity?
    @Query("SELECT * FROM profiles WHERE id=:id") suspend fun profile(id: String): ProfileEntity?
    @Query("SELECT * FROM diary_days WHERE id=:id") suspend fun day(id: String): DiaryDayEntity?
    @Update suspend fun update(product: ProductEntity)
    @Delete suspend fun delete(product: ProductEntity)
    @Delete suspend fun delete(profile: ProfileEntity)
}

val MIGRATION_16_17 = object : Migration(16, 17) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE server_diary_records (ownerScope TEXT NOT NULL, entityType TEXT NOT NULL, entityId TEXT NOT NULL, localId TEXT, wireContext TEXT NOT NULL, knownRevision INTEGER NOT NULL, deleted INTEGER NOT NULL, absent INTEGER NOT NULL, payload TEXT, runId TEXT NOT NULL, disposition TEXT NOT NULL, PRIMARY KEY(ownerScope,entityType,entityId), FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT, FOREIGN KEY(runId) REFERENCES server_snapshot_runs(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX index_server_diary_records_runId ON server_diary_records(runId)")
        db.execSQL("CREATE TABLE server_diary_applications (runId TEXT NOT NULL PRIMARY KEY, ownerScope TEXT NOT NULL, wireContext TEXT NOT NULL, serverTime TEXT NOT NULL, timelineRevision INTEGER NOT NULL, included INTEGER NOT NULL, held INTEGER NOT NULL, appliedAt TEXT NOT NULL, FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT, FOREIGN KEY(runId) REFERENCES server_snapshot_runs(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX index_server_diary_applications_ownerScope ON server_diary_applications(ownerScope)")
        db.execSQL("ALTER TABLE products ADD COLUMN wirePayload TEXT")
        // A missing server height must remain null. Preserve every old value and rowid.
        db.execSQL("ALTER TABLE profiles RENAME TO profiles_room16")
        db.execSQL("CREATE TABLE profiles (id TEXT NOT NULL PRIMARY KEY, ownerScope TEXT NOT NULL, nickname TEXT NOT NULL, heightCm REAL, activityClass TEXT NOT NULL, dietAim TEXT NOT NULL, zoneId TEXT NOT NULL, localRevision INTEGER NOT NULL)")
        db.execSQL("INSERT INTO profiles (rowid,id,ownerScope,nickname,heightCm,activityClass,dietAim,zoneId,localRevision) SELECT rowid,id,ownerScope,nickname,heightCm,activityClass,dietAim,zoneId,localRevision FROM profiles_room16")
        db.execSQL("DROP TABLE profiles_room16")
        db.execSQL("CREATE UNIQUE INDEX index_profiles_ownerScope ON profiles(ownerScope)")
    }
}
