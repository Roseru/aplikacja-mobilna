package pl.roseru.kalorie

import android.app.Application
import androidx.room.Room
import pl.roseru.kalorie.data.*
import kotlinx.coroutines.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.core.sync.*

class CalorieApplication : Application() {
    val database by lazy { Room.databaseBuilder(this, CalorieDatabase::class.java, "calorie-diary.db").addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5, MIGRATION_5_6, MIGRATION_6_7, MIGRATION_7_8).addCallback(DATABASE_GUARDS).build() }
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
        }, snapshotProtocol = SnapshotProtocol(SyncWireSchema(SyncWireSchema.FILES.associateWith { file ->
            assets.open("sync/$file").use { it.readBytes() }
        }))) }
    override fun onCreate() {
        super.onCreate()
        sessionScope.launch { sessions.start(); sessions.observeMotivationContext() }
    }
}
