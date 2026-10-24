package pl.roseru.kalorie.data

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/** Never reconstruct an estimate from a historical calorie goal. */
internal fun goalEstimateGuards(db: SupportSQLiteDatabase) {
    db.execSQL("CREATE TRIGGER IF NOT EXISTS goals_estimate_no_replace BEFORE INSERT ON goals WHEN EXISTS (SELECT 1 FROM goals WHERE id=NEW.id AND estimateJson IS NOT NEW.estimateJson) BEGIN SELECT RAISE(ABORT,'immutable goal estimate'); END")
}

val MIGRATION_23_24 = object : Migration(23, 24) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE goals ADD COLUMN estimateJson TEXT DEFAULT NULL")
        goalEstimateGuards(db)
    }
}
