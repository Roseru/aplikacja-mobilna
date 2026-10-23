package pl.roseru.kalorie

import android.app.Application
import androidx.room.Room
import pl.roseru.kalorie.data.*
import kotlinx.coroutines.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.core.sync.*

class CalorieApplication : Application() {
    val database by lazy { Room.databaseBuilder(this, CalorieDatabase::class.java, "calorie-diary.db").addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5, MIGRATION_5_6, MIGRATION_6_7, MIGRATION_7_8, pl.roseru.kalorie.photo.MIGRATION_8_9, pl.roseru.kalorie.photo.MIGRATION_9_10, pl.roseru.kalorie.data.MIGRATION_10_11, pl.roseru.kalorie.data.MIGRATION_11_12, pl.roseru.kalorie.photo.MIGRATION_12_13, pl.roseru.kalorie.data.MIGRATION_13_14, pl.roseru.kalorie.data.MIGRATION_14_15, pl.roseru.kalorie.data.MIGRATION_15_16, pl.roseru.kalorie.data.MIGRATION_16_17, pl.roseru.kalorie.data.MIGRATION_17_18, pl.roseru.kalorie.data.MIGRATION_18_19, pl.roseru.kalorie.data.MIGRATION_19_20).addCallback(DATABASE_GUARDS).build() }
    // Legacy guest setup API. UI repositories always use the active, captured lease.
    val repository get() = DiaryRepository(database, this)
    val preferences by lazy { Preferences(this) }
    val sessionScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    val sessions by lazy { SessionController(database, SessionVault(this), AppAuthGateway(this), getString(R.string.oidc_issuer), packageName,
        bootstrapGateway = getString(R.string.api_base_url).takeIf { it.isNotEmpty() }?.let {
            // Invalid public configuration disables API access; it never blocks the offline diary.
            try { HttpsBootstrapGateway(it) } catch (_: Exception) { null }
        }, profileGateway = getString(R.string.api_base_url).takeIf { it.isNotEmpty() }?.let {
            try { HttpsProfileGateway(it) } catch (_: Exception) { null }
        }, snapshotGateway = getString(R.string.api_base_url).takeIf { it.isNotEmpty() }?.let {
            try { HttpsSnapshotGateway(it) } catch (_: Exception) { null }
        }, motivationGateway = getString(R.string.api_base_url).takeIf { it.isNotEmpty() }?.let {
            try { HttpsMotivationGateway(it) } catch (_: Exception) { null }
        }, rankingConsentGateway = getString(R.string.api_base_url).takeIf { it.isNotEmpty() }?.let {
            try { HttpsRankingConsentGateway(it) } catch (_: Exception) { null }
        }, rankingGateway = getString(R.string.api_base_url).takeIf { it.isNotEmpty() }?.let {
            try { HttpsRankingGateway(it) } catch (_: Exception) { null }
        }, nemesisGateway = getString(R.string.api_base_url).takeIf { it.isNotEmpty() }?.let {
            try { HttpsNemesisGateway(it) } catch (_: Exception) { null }
        }, nemesisWriteGateway = getString(R.string.api_base_url).takeIf { it.isNotEmpty() }?.let {
            try { HttpsNemesisWriteGateway(it) } catch (_: Exception) { null }
        }, photoCapabilitiesGateway = getString(R.string.api_base_url).takeIf { it.isNotEmpty() }?.let {
            try { HttpsPhotoCapabilitiesGateway(it) } catch (_: Exception) { null }
        }, photoAnalysisGateway = getString(R.string.api_base_url).takeIf { it.isNotEmpty() }?.let {
            try { HttpsPhotoAnalysisGateway(it) } catch (_: Exception) { null }
        }, mealPushGateway = getString(R.string.api_base_url).takeIf { it.isNotEmpty() }?.let {
            try { HttpsMealPushGateway(it) } catch (_: Exception) { null }
        }, mealPushStore = MealPushStore(database,CanonicalMealRows.schema(this)),
        mealPushProtocol = PushProtocol(CanonicalMealRows.schema(this)),
        conflictStore = SyncConflictStore(database,CanonicalMealRows.schema(this)),
        diaryStore = ServerDiaryStore(database,CanonicalMealRows.schema(this)),
        photoAnalysisStores = { lease -> pl.roseru.kalorie.photo.PhotoAnalysisStore(this,database,lease) }, snapshotProtocol = SnapshotProtocol(SyncWireSchema(SyncWireSchema.FILES.associateWith { file ->
            assets.open("sync/$file").use { it.readBytes() }
        }))) }
    override fun onCreate() {
        super.onCreate()
        // Finish process attachment before lazy Room initialization; Main.immediate
        // would perform it inline inside Application.onCreate on a cold process.
        sessionScope.launch(Dispatchers.Main) { sessions.start(); sessions.observeMotivationContext() }
    }
}
