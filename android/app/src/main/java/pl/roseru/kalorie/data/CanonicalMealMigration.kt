package pl.roseru.kalorie.data

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/** Preserve every old column; nullable identity/energy represent missing AI data honestly. */
val MIGRATION_10_11=object:Migration(10,11) {
    override fun migrate(db:SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE meals ADD COLUMN wirePayload TEXT")
        db.execSQL("ALTER TABLE meals ADD COLUMN wireContext TEXT")
        db.execSQL("CREATE TABLE IF NOT EXISTS `_new_meal_items` (`id` TEXT NOT NULL, `mealId` TEXT NOT NULL, `productId` TEXT, `productName` TEXT NOT NULL, `grams` REAL NOT NULL, `kcalPer100` REAL, `proteinPer100` REAL, `fatPer100` REAL, `carbsPer100` REAL, `rationComponentId` TEXT, `snapshotJson` TEXT, `rationComponentPosition` INTEGER, `wirePayload` TEXT, PRIMARY KEY(`id`), FOREIGN KEY(`mealId`) REFERENCES `meals`(`id`) ON UPDATE NO ACTION ON DELETE RESTRICT )")
        db.execSQL("INSERT INTO _new_meal_items (rowid,`id`,`mealId`,`productId`,`productName`,`grams`,`kcalPer100`,`proteinPer100`,`fatPer100`,`carbsPer100`,`rationComponentId`,`snapshotJson`,`rationComponentPosition`) SELECT rowid,`id`,`mealId`,`productId`,`productName`,`grams`,`kcalPer100`,`proteinPer100`,`fatPer100`,`carbsPer100`,`rationComponentId`,`snapshotJson`,`rationComponentPosition` FROM meal_items")
        db.execSQL("DROP TABLE meal_items")
        db.execSQL("ALTER TABLE _new_meal_items RENAME TO meal_items")
        db.execSQL("CREATE INDEX index_meal_items_mealId ON meal_items(mealId)")
        db.execSQL("ALTER TABLE outbox ADD COLUMN wireFormat TEXT NOT NULL DEFAULT 'legacy'")
        db.execSQL("ALTER TABLE outbox ADD COLUMN wireJson TEXT")
        db.execSQL("ALTER TABLE outbox ADD COLUMN wireContext TEXT")
        db.execSQL("ALTER TABLE outbox ADD COLUMN attempted INTEGER NOT NULL DEFAULT 0")
        db.execSQL("CREATE TABLE IF NOT EXISTS photo_materializations (ownerScope TEXT NOT NULL, analysisId TEXT NOT NULL, mealId TEXT NOT NULL, sourceOperationId TEXT NOT NULL, sourcePhotoId TEXT NOT NULL, confirmationKey TEXT NOT NULL, receiptJson TEXT NOT NULL, snapshotJson TEXT NOT NULL, provenanceJson TEXT NOT NULL, wireContext TEXT NOT NULL, firstOutboxId TEXT NOT NULL, createdAt TEXT NOT NULL, PRIMARY KEY(ownerScope,analysisId), FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT, FOREIGN KEY(mealId) REFERENCES meals(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE UNIQUE INDEX index_photo_materializations_mealId ON photo_materializations(mealId)")
    }
}
