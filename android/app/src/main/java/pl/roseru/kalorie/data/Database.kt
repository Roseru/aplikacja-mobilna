package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.flow.Flow
import pl.roseru.kalorie.core.Nutrients

@Entity(tableName = "products")
data class ProductEntity(
    @PrimaryKey val id: String, val name: String, val searchName: String,
    val kcal: Double, val protein: Double?, val fat: Double?, val carbs: Double?,
    val defaultGrams: Double, val category: String, val source: String, val catalogVersion: Int
) { fun nutrients() = Nutrients(kcal, protein, fat, carbs) }

@Entity(tableName = "meals", indices = [Index(value = ["ownerScope", "localDate", "deleted"])])
data class MealEntity(
    @PrimaryKey val id: String, val ownerScope: String, val localDate: String,
    val occurredAt: String, val zoneId: String, val mealType: String,
    val serverRevision: Int = 0, val localRevision: Int = 1, val deleted: Boolean = false,
    val rationId: String? = null, val rationName: String? = null
)

@Entity(tableName = "meal_items", foreignKeys = [ForeignKey(
    entity = MealEntity::class, parentColumns = ["id"], childColumns = ["mealId"], onDelete = ForeignKey.RESTRICT
)], indices = [Index("mealId")])
data class MealItemEntity(
    @PrimaryKey val id: String, val mealId: String, val productId: String,
    val productName: String, val grams: Double, val kcalPer100: Double,
    val proteinPer100: Double?, val fatPer100: Double?, val carbsPer100: Double?,
    val rationComponentId: String? = null
) { fun consumed() = Nutrients(kcalPer100, proteinPer100, fatPer100, carbsPer100).portion(grams) }

data class MealWithItems(@Embedded val meal: MealEntity, @Relation(parentColumn = "id", entityColumn = "mealId") val items: List<MealItemEntity>)

@Entity(tableName = "rations")
data class RationEntity(@PrimaryKey val id: String, val name: String, val description: String,
    val source: String, val catalogVersion: Int)

@Entity(tableName = "ration_components", foreignKeys = [
    ForeignKey(entity = RationEntity::class, parentColumns = ["id"], childColumns = ["rationId"], onDelete = ForeignKey.RESTRICT),
    ForeignKey(entity = ProductEntity::class, parentColumns = ["id"], childColumns = ["productId"], onDelete = ForeignKey.RESTRICT)
], indices = [Index("rationId"), Index("productId")])
data class RationComponentEntity(@PrimaryKey val id: String, val rationId: String, val productId: String,
    val packageGrams: Double, val position: Int)

data class RationWithComponents(@Embedded val ration: RationEntity,
    @Relation(parentColumn = "id", entityColumn = "rationId") val components: List<RationComponentEntity>)

@Entity(tableName = "goals", indices = [Index(value = ["ownerScope", "validFrom"], unique = true)])
data class GoalEntity(@PrimaryKey val id: String, val ownerScope: String, val validFrom: String,
    val kcal: Double, val protein: Double?, val fat: Double?, val carbs: Double?)

@Entity(tableName = "outbox", indices = [Index("ownerScope"), Index("entityId")])
data class OutboxEntity(@PrimaryKey val operationId: String, val ownerScope: String, val entityType: String,
    val entityId: String, val action: String, val baseRevision: Int?, val payload: String,
    val createdAt: String, val status: String = "pending")

@Dao
interface CalorieDao {
    @Query("SELECT * FROM products ORDER BY name") fun products(): Flow<List<ProductEntity>>
    @Query("SELECT * FROM products WHERE id = :id") suspend fun product(id: String): ProductEntity?
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun seedProducts(products: List<ProductEntity>)
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun seedRations(rations: List<RationEntity>)
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun seedComponents(components: List<RationComponentEntity>)
    @Transaction @Query("SELECT * FROM rations ORDER BY name") fun rations(): Flow<List<RationWithComponents>>
    @Transaction @Query("SELECT * FROM rations WHERE id = :id") suspend fun ration(id: String): RationWithComponents?
    @Transaction @Query("SELECT * FROM meals WHERE ownerScope = :owner AND localDate = :date AND deleted = 0 ORDER BY occurredAt, id")
    fun day(owner: String, date: String): Flow<List<MealWithItems>>
    @Transaction @Query("SELECT * FROM meals WHERE id = :id AND ownerScope = :owner") suspend fun meal(id: String, owner: String): MealWithItems?
    @Insert suspend fun insertMeal(meal: MealEntity)
    @Update suspend fun updateMeal(meal: MealEntity)
    @Insert suspend fun insertItem(item: MealItemEntity)
    @Update suspend fun updateItem(item: MealItemEntity)
    @Delete suspend fun removeItem(item: MealItemEntity)
    @Query("SELECT * FROM goals WHERE ownerScope = :owner AND validFrom <= :date ORDER BY validFrom DESC LIMIT 1")
    fun goal(owner: String, date: String): Flow<GoalEntity?>
    @Query("SELECT * FROM goals WHERE ownerScope = :owner AND validFrom = :date LIMIT 1") suspend fun goalOn(owner: String, date: String): GoalEntity?
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun seedGoal(goal: GoalEntity)
    @Upsert suspend fun saveGoal(goal: GoalEntity)
    @Insert suspend fun enqueue(operation: OutboxEntity)
    @Query("SELECT COUNT(*) FROM outbox WHERE ownerScope = :owner AND status = 'pending'") fun pending(owner: String): Flow<Int>
    @Query("SELECT COUNT(*) FROM outbox WHERE ownerScope = :owner") suspend fun operationCount(owner: String): Int
    @Query("SELECT DISTINCT productId FROM meal_items JOIN meals ON meals.id = meal_items.mealId WHERE meals.ownerScope = :owner AND meals.deleted = 0 ORDER BY meals.occurredAt DESC LIMIT 12")
    fun recent(owner: String): Flow<List<String>>
}

@Database(entities = [ProductEntity::class, MealEntity::class, MealItemEntity::class, GoalEntity::class, OutboxEntity::class,
    RationEntity::class, RationComponentEntity::class], version = 2, exportSchema = true)
abstract class CalorieDatabase : RoomDatabase() { abstract fun dao(): CalorieDao }

val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE meals ADD COLUMN rationId TEXT")
        db.execSQL("ALTER TABLE meals ADD COLUMN rationName TEXT")
        db.execSQL("ALTER TABLE meal_items ADD COLUMN rationComponentId TEXT")
        db.execSQL("CREATE TABLE IF NOT EXISTS rations (id TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, source TEXT NOT NULL, catalogVersion INTEGER NOT NULL, PRIMARY KEY(id))")
        db.execSQL("CREATE TABLE IF NOT EXISTS ration_components (id TEXT NOT NULL, rationId TEXT NOT NULL, productId TEXT NOT NULL, packageGrams REAL NOT NULL, position INTEGER NOT NULL, PRIMARY KEY(id), FOREIGN KEY(rationId) REFERENCES rations(id) ON UPDATE NO ACTION ON DELETE RESTRICT, FOREIGN KEY(productId) REFERENCES products(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_ration_components_rationId ON ration_components(rationId)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_ration_components_productId ON ration_components(productId)")
    }
}
