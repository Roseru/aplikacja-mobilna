package pl.roseru.kalorie.data

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/** Request scope is part of a frozen envelope, even though it is carried in a header.
 * Adding a capability never rewrites an old checkpoint, UUID, request body or digest.
 */
internal fun syncProtocolGuards(db:SupportSQLiteDatabase) {
    val scopes="('calorie-app','calorie-app:energy_estimates_v1')"
    for(table in listOf("server_snapshot_runs","sync_push_batches","reconciliation_batches")) {
        db.execSQL("CREATE TRIGGER IF NOT EXISTS ${table}_scope_valid BEFORE INSERT ON $table WHEN NEW.protocolScope NOT IN $scopes BEGIN SELECT RAISE(ABORT,'unsupported sync scope'); END")
        db.execSQL("CREATE TRIGGER IF NOT EXISTS ${table}_scope_immutable BEFORE UPDATE OF protocolScope ON $table WHEN NEW.protocolScope IS NOT OLD.protocolScope BEGIN SELECT RAISE(ABORT,'immutable sync scope'); END")
        db.execSQL("CREATE TRIGGER IF NOT EXISTS ${table}_scope_no_replace BEFORE INSERT ON $table WHEN EXISTS (SELECT 1 FROM $table old WHERE old.id=NEW.id AND old.protocolScope IS NOT NEW.protocolScope) BEGIN SELECT RAISE(ABORT,'immutable sync scope'); END")
    }
    for(table in listOf("sync_push_batches","reconciliation_batches")) {
        db.execSQL("CREATE TRIGGER IF NOT EXISTS ${table}_snapshot_scope BEFORE INSERT ON $table WHEN NOT EXISTS (SELECT 1 FROM server_snapshot_runs r WHERE r.id=NEW.snapshotRunId AND r.protocolScope=NEW.protocolScope) BEGIN SELECT RAISE(ABORT,'checkpoint scope mismatch'); END")
        db.execSQL("CREATE TRIGGER IF NOT EXISTS ${table}_snapshot_scope_update BEFORE UPDATE OF snapshotRunId ON $table WHEN NOT EXISTS (SELECT 1 FROM server_snapshot_runs r WHERE r.id=NEW.snapshotRunId AND r.protocolScope=NEW.protocolScope) BEGIN SELECT RAISE(ABORT,'checkpoint scope mismatch'); END")
    }
    val runIdentity=listOf("readMode","baseRunId","startingCheckpoint").joinToString(" OR ") {"NEW.$it IS NOT OLD.$it"}
    db.execSQL("CREATE TRIGGER IF NOT EXISTS server_copy_source_immutable BEFORE UPDATE ON server_snapshot_runs WHEN $runIdentity BEGIN SELECT RAISE(ABORT,'immutable read source'); END")
    val sourceReplacement=listOf("readMode","baseRunId","startingCheckpoint").joinToString(" OR ") {"NEW.$it IS NOT old.$it"}
    db.execSQL("CREATE TRIGGER IF NOT EXISTS server_copy_source_no_replace BEFORE INSERT ON server_snapshot_runs WHEN EXISTS (SELECT 1 FROM server_snapshot_runs old WHERE old.id=NEW.id AND ($sourceReplacement)) BEGIN SELECT RAISE(ABORT,'immutable read source'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS server_copy_source_valid BEFORE INSERT ON server_snapshot_runs WHEN NOT ((NEW.readMode='snapshot' AND NEW.baseRunId IS NULL AND NEW.startingCheckpoint IS NULL) OR (NEW.readMode='incremental' AND NEW.protocolScope='calorie-app:energy_estimates_v1' AND EXISTS (SELECT 1 FROM server_snapshot_runs r JOIN server_diary_applications a ON a.runId=r.id WHERE r.id=NEW.baseRunId AND r.ownerScope=NEW.ownerScope AND r.accountId=NEW.accountId AND r.accountGeneration=NEW.accountGeneration AND r.syncEpoch=NEW.syncEpoch AND r.contextRevision=NEW.contextRevision AND r.state='complete' AND r.protocolScope=NEW.protocolScope AND r.checkpoint=NEW.startingCheckpoint))) BEGIN SELECT RAISE(ABORT,'invalid read source'); END")
    val valid="((NEW.activeScope='calorie-app' AND NEW.phase IN ('draining','snapshot')) OR (NEW.activeScope='calorie-app:energy_estimates_v1' AND NEW.phase='active'))"
    db.execSQL("CREATE TRIGGER IF NOT EXISTS sync_protocol_state_valid BEFORE INSERT ON sync_protocol_states WHEN NOT $valid BEGIN SELECT RAISE(ABORT,'invalid sync transition'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS sync_protocol_state_no_replace BEFORE INSERT ON sync_protocol_states WHEN EXISTS (SELECT 1 FROM sync_protocol_states old WHERE old.ownerScope=NEW.ownerScope AND old.wireContext=NEW.wireContext) BEGIN SELECT RAISE(ABORT,'existing sync transition'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS sync_protocol_state_forward BEFORE UPDATE ON sync_protocol_states WHEN NOT $valid OR NEW.ownerScope IS NOT OLD.ownerScope OR NEW.wireContext IS NOT OLD.wireContext OR NEW.transitionId IS NOT OLD.transitionId OR (OLD.phase='snapshot' AND NEW.phase='draining') OR (OLD.phase='active' AND NEW.phase!='active') OR (OLD.phase='draining' AND NEW.phase='active') BEGIN SELECT RAISE(ABORT,'invalid sync transition'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS sync_protocol_state_no_delete BEFORE DELETE ON sync_protocol_states BEGIN SELECT RAISE(ABORT,'durable sync transition'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS canonical_energy_immutable BEFORE UPDATE ON canonical_energy_versions BEGIN SELECT RAISE(ABORT,'immutable energy axis'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS canonical_energy_no_delete BEFORE DELETE ON canonical_energy_versions BEGIN SELECT RAISE(ABORT,'immutable energy axis'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS canonical_energy_no_replace BEFORE INSERT ON canonical_energy_versions WHEN EXISTS (SELECT 1 FROM canonical_energy_versions old WHERE old.ownerScope=NEW.ownerScope AND old.wireContext=NEW.wireContext AND old.entityId=NEW.entityId) BEGIN SELECT RAISE(ABORT,'immutable energy axis'); END")
}

val MIGRATION_25_26=object:Migration(25,26) {
    override fun migrate(db:SupportSQLiteDatabase) {
        for(table in listOf("server_snapshot_runs","sync_push_batches","reconciliation_batches")) {
            db.execSQL("ALTER TABLE $table ADD COLUMN protocolScope TEXT NOT NULL DEFAULT 'calorie-app'")
        }
        db.execSQL("ALTER TABLE server_snapshot_runs ADD COLUMN readMode TEXT NOT NULL DEFAULT 'snapshot'")
        db.execSQL("ALTER TABLE server_snapshot_runs ADD COLUMN baseRunId TEXT REFERENCES server_snapshot_runs(id) ON UPDATE NO ACTION ON DELETE RESTRICT")
        db.execSQL("ALTER TABLE server_snapshot_runs ADD COLUMN startingCheckpoint TEXT")
        db.execSQL("ALTER TABLE server_snapshot_runs ADD COLUMN forceFull INTEGER NOT NULL DEFAULT 0")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_server_snapshot_runs_baseRunId ON server_snapshot_runs(baseRunId)")
        db.execSQL("CREATE TABLE IF NOT EXISTS sync_protocol_states (ownerScope TEXT NOT NULL,wireContext TEXT NOT NULL,activeScope TEXT NOT NULL,phase TEXT NOT NULL,transitionId TEXT NOT NULL,runId TEXT,updatedAt INTEGER NOT NULL,PRIMARY KEY(ownerScope,wireContext),FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT,FOREIGN KEY(runId) REFERENCES server_snapshot_runs(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_sync_protocol_states_runId ON sync_protocol_states(runId)")
        db.execSQL("CREATE TABLE IF NOT EXISTS canonical_energy_versions (ownerScope TEXT NOT NULL,wireContext TEXT NOT NULL,entityId TEXT NOT NULL,revision INTEGER NOT NULL,wire TEXT NOT NULL,sourceRunId TEXT NOT NULL,recordedAt INTEGER NOT NULL,PRIMARY KEY(ownerScope,wireContext,entityId),FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT,FOREIGN KEY(sourceRunId) REFERENCES server_snapshot_runs(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_canonical_energy_versions_ownerScope_wireContext_revision ON canonical_energy_versions(ownerScope,wireContext,revision)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_canonical_energy_versions_sourceRunId ON canonical_energy_versions(sourceRunId)")
        syncProtocolGuards(db)
    }
}
