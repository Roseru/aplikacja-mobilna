package pl.roseru.kalorie.data

import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

private fun immutableGoals(db: SupportSQLiteDatabase) {
    db.execSQL("CREATE TRIGGER IF NOT EXISTS goals_no_update BEFORE UPDATE ON goals BEGIN SELECT RAISE(ABORT, 'immutable goal version'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS goals_no_delete BEFORE DELETE ON goals BEGIN SELECT RAISE(ABORT, 'immutable goal version'); END")
    // REPLACE can bypass DELETE triggers when recursive_triggers is disabled. Compare before insertion.
    db.execSQL("CREATE TRIGGER IF NOT EXISTS goals_no_replace BEFORE INSERT ON goals WHEN EXISTS (SELECT 1 FROM goals WHERE id = NEW.id AND NOT (ownerScope IS NEW.ownerScope AND validFrom IS NEW.validFrom AND kcal IS NEW.kcal AND protein IS NEW.protein AND fat IS NEW.fat AND carbs IS NEW.carbs AND localSequence IS NEW.localSequence AND decidedAt IS NEW.decidedAt AND zoneId IS NEW.zoneId AND reason IS NEW.reason AND correctionOf IS NEW.correctionOf)) BEGIN SELECT RAISE(ABORT, 'immutable goal version'); END")
}

val DATABASE_GUARDS = object : RoomDatabase.Callback() {
    override fun onCreate(db: SupportSQLiteDatabase) = immutableGoals(db)
    override fun onOpen(db: SupportSQLiteDatabase) = immutableGoals(db)
}

val MIGRATION_5_6 = object : Migration(5, 6) {
    override fun migrate(db: SupportSQLiteDatabase) {
        // Android SQLite may retain the original name of a self-reference when a table is renamed.
        // Create the replacement under its final name so the foreign key is valid on every version.
        db.execSQL("ALTER TABLE goals RENAME TO goals_legacy")
        db.execSQL("CREATE TABLE goals (id TEXT NOT NULL PRIMARY KEY, ownerScope TEXT NOT NULL, validFrom TEXT NOT NULL, kcal REAL NOT NULL, protein REAL, fat REAL, carbs REAL, localSequence INTEGER NOT NULL DEFAULT 0, decidedAt TEXT, zoneId TEXT, reason TEXT NOT NULL DEFAULT 'legacy', correctionOf TEXT, FOREIGN KEY(ownerScope,correctionOf) REFERENCES goals(ownerScope,id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE UNIQUE INDEX index_goals_ownerScope_id ON goals(ownerScope, id)")
        db.execSQL("INSERT INTO goals (id,ownerScope,validFrom,kcal,protein,fat,carbs) SELECT id,ownerScope,validFrom,kcal,protein,fat,carbs FROM goals_legacy")
        db.execSQL("DROP TABLE goals_legacy")
        db.execSQL("CREATE INDEX index_goals_ownerScope_validFrom_localSequence ON goals(ownerScope, validFrom, localSequence)")
        db.execSQL("CREATE INDEX index_goals_ownerScope_correctionOf ON goals(ownerScope, correctionOf)")
        db.execSQL("CREATE TABLE account_bindings (ownerScope TEXT NOT NULL PRIMARY KEY, accountId TEXT NOT NULL, accountGeneration INTEGER NOT NULL, syncEpoch TEXT NOT NULL, serverTime TEXT NOT NULL, contextRevision INTEGER NOT NULL, requiresRecovery INTEGER NOT NULL, FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE UNIQUE INDEX index_account_bindings_accountId ON account_bindings(accountId)")
        db.execSQL("CREATE TABLE bootstrap_attempts (ownerScope TEXT NOT NULL PRIMARY KEY, operationId TEXT NOT NULL, leaseGeneration INTEGER NOT NULL, responseJson TEXT, FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE UNIQUE INDEX index_bootstrap_attempts_operationId ON bootstrap_attempts(operationId)")
        immutableGoals(db)
    }
}
