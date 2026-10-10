package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Entity(tableName = "catalog_generations", indices = [Index(value = ["packageId", "kind", "release"], unique = true)])
data class CatalogGenerationEntity(@PrimaryKey val id: String, val packageId: String, val kind: String, val release: Int,
    val sha256: String, val manifestJson: String, val payloadJson: String, val complete: Boolean)

@Entity(tableName = "catalog_records")
data class CatalogRecordEntity(@PrimaryKey val id: String, val entityType: String, val payloadJson: String)

@Entity(tableName = "catalog_members", primaryKeys = ["generationId", "recordId"], foreignKeys = [
    ForeignKey(entity = CatalogGenerationEntity::class, parentColumns = ["id"], childColumns = ["generationId"], onDelete = ForeignKey.RESTRICT),
    ForeignKey(entity = CatalogRecordEntity::class, parentColumns = ["id"], childColumns = ["recordId"], onDelete = ForeignKey.RESTRICT)
], indices = [Index("recordId")])
data class CatalogMemberEntity(val generationId: String, val recordId: String)

@Entity(tableName = "catalog_active", foreignKeys = [ForeignKey(entity = CatalogGenerationEntity::class,
    parentColumns = ["id"], childColumns = ["generationId"], onDelete = ForeignKey.RESTRICT)], indices = [Index("generationId")])
data class CatalogActiveEntity(@PrimaryKey val packageId: String, val kind: String, val release: Int, val generationId: String)

@Dao interface CatalogDao {
    @Query("SELECT * FROM catalog_generations WHERE packageId = :packageId AND release = :release LIMIT 1") suspend fun generation(packageId: String, release: Int): CatalogGenerationEntity?
    @Query("SELECT * FROM catalog_generations WHERE id = :id") suspend fun generationById(id: String): CatalogGenerationEntity?
    @Query("SELECT * FROM catalog_generations WHERE packageId = :packageId AND kind != :kind LIMIT 1") suspend fun otherKind(packageId: String, kind: String): CatalogGenerationEntity?
    @Query("SELECT * FROM catalog_active WHERE packageId = :packageId") suspend fun active(packageId: String): CatalogActiveEntity?
    @Query("SELECT * FROM catalog_records WHERE id = :id") suspend fun record(id: String): CatalogRecordEntity?
    @Insert suspend fun insertGeneration(value: CatalogGenerationEntity)
    @Update suspend fun updateGeneration(value: CatalogGenerationEntity)
    @Insert suspend fun insertRecord(value: CatalogRecordEntity)
    @Insert suspend fun insertMember(value: CatalogMemberEntity)
    @Upsert suspend fun setActive(value: CatalogActiveEntity)
}

val MIGRATION_3_4 = object : Migration(3, 4) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE products ADD COLUMN catalogJson TEXT")
        db.execSQL("ALTER TABLE rations ADD COLUMN catalogJson TEXT")
        db.execSQL("ALTER TABLE ration_components ADD COLUMN quantityText TEXT")
        db.execSQL("ALTER TABLE ration_components ADD COLUMN quantityUnit TEXT NOT NULL DEFAULT 'g'")
        db.execSQL("ALTER TABLE meal_items ADD COLUMN snapshotJson TEXT")
        db.execSQL("CREATE TABLE IF NOT EXISTS catalog_generations (id TEXT NOT NULL PRIMARY KEY, packageId TEXT NOT NULL, kind TEXT NOT NULL, release INTEGER NOT NULL, sha256 TEXT NOT NULL, manifestJson TEXT NOT NULL, payloadJson TEXT NOT NULL, complete INTEGER NOT NULL)")
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_catalog_generations_packageId_kind_release ON catalog_generations(packageId, kind, release)")
        db.execSQL("CREATE TABLE IF NOT EXISTS catalog_records (id TEXT NOT NULL PRIMARY KEY, entityType TEXT NOT NULL, payloadJson TEXT NOT NULL)")
        db.execSQL("CREATE TABLE IF NOT EXISTS catalog_members (generationId TEXT NOT NULL, recordId TEXT NOT NULL, PRIMARY KEY(generationId, recordId), FOREIGN KEY(generationId) REFERENCES catalog_generations(id) ON UPDATE NO ACTION ON DELETE RESTRICT, FOREIGN KEY(recordId) REFERENCES catalog_records(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_catalog_members_recordId ON catalog_members(recordId)")
        db.execSQL("CREATE TABLE IF NOT EXISTS catalog_active (packageId TEXT NOT NULL PRIMARY KEY, kind TEXT NOT NULL, release INTEGER NOT NULL, generationId TEXT NOT NULL, FOREIGN KEY(generationId) REFERENCES catalog_generations(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_catalog_active_generationId ON catalog_active(generationId)")
    }
}
