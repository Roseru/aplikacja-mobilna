package pl.roseru.kalorie.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.*
import androidx.room.withTransaction
import pl.roseru.kalorie.core.*
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate

class AnalyticsRepository(private val dao: CalorieDao, private val clock: LocalDayClock = LocalDayClock()) {
    fun observe(owner: String, window: AnalyticsWindow): Flow<AnalyticsResult> {
        val inputs = combine(
            dao.mealsBetween(owner, window.start.toString(), window.end.toString()),
            dao.goalsThrough(owner, window.end.toString()),
            dao.daysBetween(owner, window.start.toString(), window.end.toString()),
            dao.weightsBetween(owner, window.start.toString(), window.end.toString())
        ) { meals, goals, days, weights ->
            AnalyticsInput(
                meals.map { AnalyticsMeal(LocalDate.parse(it.meal.localDate), it.items.map(MealItemEntity::consumed)) },
                goals.map { AnalyticsGoal(LocalDate.parse(it.validFrom), BigDecimal.valueOf(it.kcal), it.localSequence, it.id) },
                days.filter { it.declaredComplete }.map { LocalDate.parse(it.localDate) }.toSet(),
                weights.map { AnalyticsWeight(it.id, LocalDate.parse(it.localDate), Instant.parse(it.occurredAt), BigDecimal.valueOf(it.kg)) }
            )
        }
        return combine(inputs, clock.dates()) { input, today -> Analytics.build(window, input, today) }
            .flowOn(Dispatchers.Default)
    }
}

/** A read-only projection of durable local facts. A completed copy never acknowledges an outbox row. */
sealed interface AnalyticsSyncState {
    data object Loading : AnalyticsSyncState
    data object Guest : AnalyticsSyncState
    data object Stale : AnalyticsSyncState
    data object Unavailable : AnalyticsSyncState
    data class Account(
        val lastAppliedAt: String?, val serverTime: String?, val pendingOperations: Int,
        val rejectedOperations: Int, val conflictedOperations: Int, val legacyOperations: Int,
        val unconfirmedWrite: Boolean, val heldServerRecords: Int, val copyAwaitingApplication: Boolean,
        val requiresRecovery: Boolean, val syncStatus: String?
    ) : AnalyticsSyncState
}

/** Uses the same owner lease, binding and queue facts as the existing synchronization overview.
 * Reading a report performs no HTTP, preparation, retry, ACK or state transition.
 */
class AnalyticsSyncRepository(private val db: CalorieDatabase, private val lease: OwnerLease) {
    private val overviewStore = AccountSyncOverviewStore(db)
    fun observe(): Flow<AnalyticsSyncState> = overviewStore.changes().map { read() }.catch { error ->
        when (error) {
            is CancellationException -> throw error
            is StaleOwnerException -> emit(AnalyticsSyncState.Stale)
            else -> emit(AnalyticsSyncState.Unavailable)
        }
    }.distinctUntilChanged().flowOn(Dispatchers.IO)

    internal suspend fun read(): AnalyticsSyncState = db.withTransaction {
        LocalOwnerStore(db).requireCurrent(lease)
        if (db.ownerDao().byScope(lease.storageScope)?.kind == "guest") return@withTransaction AnalyticsSyncState.Guest
        val overview = overviewStore.read(lease)
        val binding = db.bootstrapDao().binding(lease.storageScope)
        val wireContext = binding?.let(CanonicalMealRows::context)
        val application = db.serverDiaryDao().latest(lease.storageScope)?.takeIf { it.wireContext == wireContext }
        val queue = db.serverDiaryDao().unsettled(lease.storageScope)
        val rejected = queue.count { it.status == "rejected" }
        val conflicts = queue.count { it.status == "conflict" }
        val newestCopy = if (binding == null) null else db.snapshotDao().runs(lease.storageScope).firstOrNull {
            it.state == "complete" && it.accountId == binding.accountId && it.accountGeneration == binding.accountGeneration &&
                it.syncEpoch == binding.syncEpoch && it.contextRevision == binding.contextRevision && db.importDao().pull(it.id) == null
        }
        AnalyticsSyncState.Account(application?.appliedAt, application?.serverTime,
            queue.size - rejected - conflicts, rejected, conflicts, overview.legacy, overview.unconfirmedWrite,
            application?.held ?: 0, newestCopy != null && db.serverDiaryDao().application(newestCopy.id) == null,
            overview.requiresRecovery || overview.accountBlocked, overview.work?.status)
    }
}
