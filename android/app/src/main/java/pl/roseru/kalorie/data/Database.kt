package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.flow.Flow
import pl.roseru.kalorie.core.Nutrients
import pl.roseru.kalorie.core.catalog.exactProductNutrients
import org.json.JSONObject
import pl.roseru.kalorie.core.ContractDecimal
import pl.roseru.kalorie.core.NutritionError
import pl.roseru.kalorie.core.catalog.StrictJson

@Entity(tableName = "products")
data class ProductEntity(
    @PrimaryKey val id: String, val name: String, val searchName: String,
    val kcal: Double, val protein: Double?, val fat: Double?, val carbs: Double?,
    val defaultGrams: Double, val category: String, val source: String, val catalogVersion: Int,
    val ownerScope: String? = null, val catalogJson: String? = null
) {
    val unit: String get() = catalogJson?.let { JSONObject(it).getString("basis_unit") } ?: "g"
    fun nutrients() = catalogJson?.let { exactProductNutrients(it, "100", unit) } ?: Nutrients(kcal, protein, fat, carbs)
    fun portion(amount: String, quantityUnit: String = unit) = catalogJson?.let { exactProductNutrients(it, amount, quantityUnit) }
        ?: nutrients().portion(amount.toDouble())
}

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
    val rationComponentId: String? = null, val snapshotJson: String? = null
) {
    val unit: String get() = snapshotJson?.let { JSONObject(it).getJSONObject("quantity").getString("unit") } ?: "g"
    val amountText: String get() = snapshotJson?.let { JSONObject(it).getJSONObject("quantity").getString("amount") } ?: grams.toBigDecimal().stripTrailingZeros().toPlainString()
    fun withAmount(text: String): MealItemEntity {
        val amount = ContractDecimal.userQuantity(text, 12) ?: throw NutritionError("quantity_range")
        val snapshot = snapshotJson?.let { JSONObject(it).apply {
            getJSONObject("quantity").put("amount", ContractDecimal.canonical(amount))
        }.let(StrictJson::canonical) }
        return copy(grams = amount.toDouble(), snapshotJson = snapshot)
    }
    fun consumed(): Nutrients = snapshotJson?.let {
        val snapshot = JSONObject(it); val quantity = snapshot.getJSONObject("quantity")
        exactProductNutrients(snapshot.getJSONObject("product").toString(), quantity.getString("amount"), quantity.getString("unit"))
    } ?: Nutrients(kcalPer100, proteinPer100, fatPer100, carbsPer100).portion(grams)
}

data class MealWithItems(@Embedded val meal: MealEntity, @Relation(parentColumn = "id", entityColumn = "mealId") val items: List<MealItemEntity>)

@Entity(tableName = "rations")
data class RationEntity(@PrimaryKey val id: String, val name: String, val description: String,
    val source: String, val catalogVersion: Int, val catalogJson: String? = null)

@Entity(tableName = "ration_components", foreignKeys = [
    ForeignKey(entity = RationEntity::class, parentColumns = ["id"], childColumns = ["rationId"], onDelete = ForeignKey.RESTRICT),
    ForeignKey(entity = ProductEntity::class, parentColumns = ["id"], childColumns = ["productId"], onDelete = ForeignKey.RESTRICT)
], indices = [Index("rationId"), Index("productId")])
data class RationComponentEntity(@PrimaryKey val id: String, val rationId: String, val productId: String,
    val packageGrams: Double, val position: Int, val quantityText: String? = null,
    @ColumnInfo(defaultValue = "'g'") val quantityUnit: String = "g")

data class RationWithComponents(@Embedded val ration: RationEntity,
    @Relation(parentColumn = "id", entityColumn = "rationId") val components: List<RationComponentEntity>)

@Entity(tableName = "goals", foreignKeys = [ForeignKey(entity = GoalEntity::class,
    parentColumns = ["ownerScope", "id"], childColumns = ["ownerScope", "correctionOf"], onDelete = ForeignKey.RESTRICT)],
    indices = [Index(value = ["ownerScope", "validFrom", "localSequence"]),
        Index(value = ["ownerScope", "id"], unique = true), Index(value = ["ownerScope", "correctionOf"])])
data class GoalEntity(@PrimaryKey val id: String, val ownerScope: String, val validFrom: String,
    val kcal: Double, val protein: Double?, val fat: Double?, val carbs: Double?,
    @ColumnInfo(defaultValue = "0") val localSequence: Int = 0,
    val decidedAt: String? = null, val zoneId: String? = null,
    @ColumnInfo(defaultValue = "'legacy'") val reason: String = "legacy", val correctionOf: String? = null)

@Entity(tableName = "outbox", indices = [Index("ownerScope"), Index("entityId")])
data class OutboxEntity(@PrimaryKey val operationId: String, val ownerScope: String, val entityType: String,
    val entityId: String, val action: String, val baseRevision: Int?, val payload: String,
    val createdAt: String, val status: String = "pending")

@Entity(tableName = "profiles", indices = [Index(value = ["ownerScope"], unique = true)])
data class ProfileEntity(@PrimaryKey val id: String, val ownerScope: String, val nickname: String,
    val heightCm: Double, val activityClass: String, val dietAim: String, val zoneId: String, val localRevision: Int)

@Entity(tableName = "weights", indices = [Index(value = ["ownerScope", "localDate", "deleted"])])
data class WeightEntity(@PrimaryKey val id: String, val ownerScope: String, val localDate: String,
    val occurredAt: String, val zoneId: String, val kg: Double, val deleted: Boolean = false, val localRevision: Int = 1)

@Entity(tableName = "diary_days", indices = [Index(value = ["ownerScope", "localDate"], unique = true)])
data class DiaryDayEntity(@PrimaryKey val id: String, val ownerScope: String, val localDate: String,
    val declaredComplete: Boolean, val localRevision: Int)

@Dao
interface CalorieDao {
    @Transaction @Query("SELECT * FROM meals WHERE ownerScope = :owner AND localDate BETWEEN :start AND :end AND deleted = 0 ORDER BY localDate, occurredAt, id")
    fun mealsBetween(owner: String, start: String, end: String): Flow<List<MealWithItems>>
    @Query("SELECT * FROM goals WHERE ownerScope = :owner AND validFrom <= :end ORDER BY validFrom, localSequence, id")
    fun goalsThrough(owner: String, end: String): Flow<List<GoalEntity>>
    @Query("SELECT * FROM diary_days WHERE ownerScope = :owner AND localDate BETWEEN :start AND :end ORDER BY localDate")
    fun daysBetween(owner: String, start: String, end: String): Flow<List<DiaryDayEntity>>
    @Query("SELECT * FROM weights WHERE ownerScope = :owner AND localDate BETWEEN :start AND :end AND deleted = 0 ORDER BY localDate, occurredAt, id")
    fun weightsBetween(owner: String, start: String, end: String): Flow<List<WeightEntity>>
    @Query("SELECT * FROM products WHERE (ownerScope IS NULL OR ownerScope = :owner) AND (catalogJson IS NULL OR id IN (SELECT recordId FROM catalog_members JOIN catalog_active ON catalog_members.generationId = catalog_active.generationId)) ORDER BY name") fun products(owner: String = "guest"): Flow<List<ProductEntity>>
    @Query("SELECT * FROM products WHERE id = :id AND (ownerScope IS NULL OR ownerScope = :owner)") suspend fun product(id: String, owner: String = "guest"): ProductEntity?
    @Insert suspend fun insertProduct(product: ProductEntity)
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun seedProducts(products: List<ProductEntity>)
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun seedRations(rations: List<RationEntity>)
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun seedComponents(components: List<RationComponentEntity>)
    @Transaction @Query("SELECT * FROM rations WHERE catalogJson IS NULL OR id IN (SELECT recordId FROM catalog_members JOIN catalog_active ON catalog_members.generationId = catalog_active.generationId) ORDER BY name") fun rations(): Flow<List<RationWithComponents>>
    @Transaction @Query("SELECT * FROM rations WHERE id = :id") suspend fun ration(id: String): RationWithComponents?
    @Transaction @Query("SELECT * FROM meals WHERE ownerScope = :owner AND localDate = :date AND deleted = 0 ORDER BY occurredAt, id")
    fun day(owner: String, date: String): Flow<List<MealWithItems>>
    @Transaction @Query("SELECT * FROM meals WHERE id = :id AND ownerScope = :owner") suspend fun meal(id: String, owner: String): MealWithItems?
    @Insert suspend fun insertMeal(meal: MealEntity)
    @Update suspend fun updateMeal(meal: MealEntity)
    @Insert suspend fun insertItem(item: MealItemEntity)
    @Update suspend fun updateItem(item: MealItemEntity)
    @Delete suspend fun removeItem(item: MealItemEntity)
    @Query("SELECT * FROM goals WHERE ownerScope = :owner AND validFrom <= :date ORDER BY validFrom DESC, localSequence DESC, id DESC LIMIT 1")
    fun goal(owner: String, date: String): Flow<GoalEntity?>
    @Query("SELECT * FROM goals WHERE ownerScope = :owner AND validFrom = :date ORDER BY localSequence DESC, id DESC LIMIT 1") suspend fun goalOn(owner: String, date: String): GoalEntity?
    @Query("SELECT * FROM goals WHERE ownerScope = :owner AND id = :id") suspend fun goalById(owner: String, id: String): GoalEntity?
    @Query("SELECT COALESCE(MAX(localSequence), 0) FROM goals WHERE ownerScope = :owner") suspend fun goalSequence(owner: String): Int
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun seedGoal(goal: GoalEntity)
    @Insert suspend fun saveGoal(goal: GoalEntity)
    @Insert suspend fun enqueue(operation: OutboxEntity)
    @Query("SELECT COUNT(*) FROM outbox WHERE ownerScope = :owner AND status = 'pending'") fun pending(owner: String): Flow<Int>
    @Query("SELECT COUNT(*) FROM outbox WHERE ownerScope = :owner") suspend fun operationCount(owner: String): Int
    @Query("SELECT DISTINCT productId FROM meal_items JOIN meals ON meals.id = meal_items.mealId WHERE meals.ownerScope = :owner AND meals.deleted = 0 ORDER BY meals.occurredAt DESC LIMIT 12")
    fun recent(owner: String): Flow<List<String>>
    @Query("SELECT * FROM profiles WHERE ownerScope = :owner LIMIT 1") fun profile(owner: String): Flow<ProfileEntity?>
    @Query("SELECT * FROM profiles WHERE ownerScope = :owner LIMIT 1") suspend fun currentProfile(owner: String): ProfileEntity?
    @Upsert suspend fun saveProfile(profile: ProfileEntity)
    @Query("SELECT * FROM weights WHERE ownerScope = :owner AND deleted = 0 ORDER BY localDate DESC, occurredAt DESC, id DESC") fun weights(owner: String): Flow<List<WeightEntity>>
    @Query("SELECT * FROM weights WHERE id = :id AND ownerScope = :owner") suspend fun weight(id: String, owner: String): WeightEntity?
    @Query("SELECT ownerScope FROM weights WHERE id = :id") suspend fun weightOwner(id: String): String?
    @Upsert suspend fun saveWeight(weight: WeightEntity)
    @Query("SELECT * FROM diary_days WHERE ownerScope = :owner AND localDate = :date LIMIT 1") fun diaryDay(owner: String, date: String): Flow<DiaryDayEntity?>
    @Query("SELECT * FROM diary_days WHERE ownerScope = :owner AND localDate = :date LIMIT 1") suspend fun currentDiaryDay(owner: String, date: String): DiaryDayEntity?
    @Upsert suspend fun saveDiaryDay(day: DiaryDayEntity)
}

@Database(entities = [ProductEntity::class, MealEntity::class, MealItemEntity::class, GoalEntity::class, OutboxEntity::class,
    RationEntity::class, RationComponentEntity::class, ProfileEntity::class, WeightEntity::class, DiaryDayEntity::class,
    CatalogGenerationEntity::class, CatalogRecordEntity::class, CatalogMemberEntity::class, CatalogActiveEntity::class,
    LocalOwnerEntity::class, LocalActiveOwnerEntity::class, AccountBindingEntity::class,
    BootstrapAttemptEntity::class], version = 6, exportSchema = true)
abstract class CalorieDatabase : RoomDatabase() {
    abstract fun dao(): CalorieDao
    abstract fun catalogDao(): CatalogDao
    abstract fun ownerDao(): LocalOwnerDao
    abstract fun bootstrapDao(): AccountBootstrapDao
}

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

val MIGRATION_2_3 = object : Migration(2, 3) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE products ADD COLUMN ownerScope TEXT")
        db.execSQL("CREATE TABLE IF NOT EXISTS profiles (id TEXT NOT NULL, ownerScope TEXT NOT NULL, nickname TEXT NOT NULL, heightCm REAL NOT NULL, activityClass TEXT NOT NULL, dietAim TEXT NOT NULL, zoneId TEXT NOT NULL, localRevision INTEGER NOT NULL, PRIMARY KEY(id))")
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_profiles_ownerScope ON profiles(ownerScope)")
        db.execSQL("CREATE TABLE IF NOT EXISTS weights (id TEXT NOT NULL, ownerScope TEXT NOT NULL, localDate TEXT NOT NULL, occurredAt TEXT NOT NULL, zoneId TEXT NOT NULL, kg REAL NOT NULL, deleted INTEGER NOT NULL, localRevision INTEGER NOT NULL, PRIMARY KEY(id))")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_weights_ownerScope_localDate_deleted ON weights(ownerScope, localDate, deleted)")
        db.execSQL("CREATE TABLE IF NOT EXISTS diary_days (id TEXT NOT NULL, ownerScope TEXT NOT NULL, localDate TEXT NOT NULL, declaredComplete INTEGER NOT NULL, localRevision INTEGER NOT NULL, PRIMARY KEY(id))")
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_diary_days_ownerScope_localDate ON diary_days(ownerScope, localDate)")
    }
}
