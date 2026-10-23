package pl.roseru.kalorie.session

import android.content.Intent
import android.net.Uri
import androidx.room.withTransaction
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import net.openid.appauth.*
import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.photo.*
import java.util.UUID

data class SessionBinding(val owner: LocalOwnerEntity, val lease: OwnerLease)
data class SessionView(val binding: SessionBinding? = null, val busy: Boolean = false,
    val pendingLogin: Boolean = false, val configured: Boolean = false, val hasSession: Boolean = false,
    val message: String? = null, val apiConfigured: Boolean = false, val bootstrapBusy: Boolean = false,
    val serverLinked: Boolean = false, val requiresRecovery: Boolean = false,
    val profileBusy: Boolean = false, val serverProfile: ProfileRead? = null,
    val snapshotBusy: Boolean = false, val snapshot: SnapshotStatus? = null,
    val mealPushConfigured:Boolean=false,val mealPushBusy:Boolean=false,val mealPush:MealPushStatus?=null,
    val mealPushMessage:String?=null,val mealPushRetryAt:Long=0,
    val motivationConfigured: Boolean = false, val motivationBusy: Boolean = false,
    val motivation: MotivationState = MotivationState.NotRequested,
    val rankingConsentConfigured: Boolean = false, val rankingConsentBusy: Boolean = false,
    val rankingConsent: RankingConsentState = RankingConsentState.NotRequested,
    val rankingConfigured: Boolean = false, val rankingBusy: Boolean = false,
    val ranking: RankingState = RankingState.NotRequested,
    val nemesisConfigured: Boolean = false, val nemesisBusy: Boolean = false,
    val nemesis: NemesisState = NemesisState.NotRequested,
    val nemesisDecision: NemesisDecisionSource? = null,
    val nemesisMutationConfigured: Boolean = false, val nemesisMutationBusy: Boolean = false,
    val nemesisMutation: NemesisMutationState = NemesisMutationState.Idle,
    val photoCapabilitiesConfigured: Boolean = false, val photoCapabilitiesBusy: Boolean = false,
    val photoCapabilities: PhotoCapabilitiesState = PhotoCapabilitiesState.NotRequested,
    val photoUploadConfigured:Boolean=false,val photoUploadBusy:Boolean=false,
    val photoUpload:PhotoUploadStatus?=null,val photoUploadMessage:String?=null,
    val photoReadBusy:Boolean=false,val photoAnalysis:PhotoAnalysisPreview?=null,
    val photoCancelBusy:Boolean=false,val photoCancellation:PhotoCancellationStatus?=null,
    val photoConfirmBusy:Boolean=false,val photoConfirmation:PhotoConfirmationStatus?=null,
    val photoDraftBusy:Boolean=false,val photoCanEditProposal:Boolean=false,val photoMealDraft:PhotoMealDraftPreview?=null,
    val conflictBusy:Boolean=false,val conflicts:ConflictListView=ConflictListView(),
    val diaryApplication:ServerDiaryApplication?=null,val diaryApplying:Boolean=false)

/** Serializes durable decisions, not network waits. A callback/refresh is fenced by a captured
 * owner lease AND an operation ID, so logout and A→B→A cannot apply an old response.
 */
class SessionController internal constructor(private val db: CalorieDatabase, private val vault: SessionVault,
    private val gateway: OidcGateway, private val issuer: String, private val applicationId: String,
    private val now: () -> Long = System::currentTimeMillis,
    private val bootstrapGateway: BootstrapGateway? = null,
    private val profileGateway: ProfileGateway? = null,
    private val snapshotGateway: SnapshotGateway? = null, snapshotProtocol: SnapshotProtocol? = null,
    private val motivationGateway: MotivationGateway? = null,
    private val rankingConsentGateway: RankingConsentGateway? = null,
    private val rankingGateway: RankingGateway? = null,
    private val nemesisGateway: NemesisGateway? = null,
    private val nemesisWriteGateway: NemesisWriteGateway? = null,
    private val photoCapabilitiesGateway: PhotoCapabilitiesGateway? = null,
    private val photoAnalysisGateway:PhotoAnalysisGateway?=null,
    private val photoAnalysisStores:((OwnerLease)->PhotoAnalysisStore)?=null,
    private val mealPushGateway:MealPushGateway?=null,private val mealPushStore:MealPushStore?=null,
    private val mealPushProtocol:pl.roseru.kalorie.core.sync.PushProtocol?=null,
    private val conflictStore:SyncConflictStore?=null,
    private val diaryStore:ServerDiaryStore?=null) {
    private val owners = LocalOwnerStore(db)
    private val mutex = Mutex()
    /** A nullable server binding is also an expectation: the first bootstrap must still be first. */
    private data class SyncContextFence(val lease: OwnerLease, val server: AccountBindingEntity?) {
        override fun toString() = "SyncContextFence(redacted)"
    }
    private class SyncContextChangedException : IllegalStateException("Captured synchronization context changed")
    /** Internal outcomes; the O2 boundary maps them without inspecting any UI message. */
    internal sealed interface SyncCommandOutcome {
        data class Bootstrapped(val context: AccountBindingEntity) : SyncCommandOutcome {
            override fun toString() = "Bootstrapped(redacted)"
        }
        data class Pulled(val runId: String, val applied: Boolean) : SyncCommandOutcome {
            override fun toString() = "Pulled(redacted)"
        }
        data class Pushed(val acknowledged: Int, val refused: Int, val more: Boolean) : SyncCommandOutcome
        data object Busy : SyncCommandOutcome
        data class RetryAt(val epochMillis: Long) : SyncCommandOutcome
        data object LoginRequired : SyncCommandOutcome
        data class ReconciliationRequired(val code: String) : SyncCommandOutcome
        data object StaleContext : SyncCommandOutcome
        data object TransientFailure : SyncCommandOutcome
        data object NotConfigured : SyncCommandOutcome
    }
    // Called inside the session mutex; network/apply callers additionally own the Room transaction.
    private suspend fun requireSyncContext(fence: SyncContextFence) {
        owners.requireCurrent(fence.lease)
        if (db.bootstrapDao().binding(fence.lease.storageScope) != fence.server) throw SyncContextChangedException()
    }
    private suspend fun completeSyncCommand(fence: SyncContextFence, outcome: SyncCommandOutcome): SyncCommandOutcome = mutex.withLock {
        db.withTransaction { requireSyncContext(fence); outcome }
    }
    private var record = JSONObject()
    private var operation: String? = null
    private var bootstrapOperation: String? = null
    private var profileOperation: String? = null
    private enum class PrivateReadKind { PROFILE, MOTIVATION, CONSENTS, RANKING, NEMESIS, PHOTO }
    private var photoUploadOperation:String?=null
    private var photoUploadMessage:String?=null
    private var photoUploadFence:Pair<OwnerLease,Long>?=null
    private var photoUploadContext:Triple<String,Int,String>?=null
    private var photoReadMode=false
    private var photoCancelMode=false
    private var photoConfirmMode=false
    private var photoConfirmationStatus:PhotoConfirmationStatus?=null
    private var photoEditMode=false
    private var photoCanEditProposal=false
    private var photoMealDraft:PhotoMealDraftPreview?=null
    private var photoCancellationStatus:PhotoCancellationStatus?=null
    private var photoAnalysisPreview:PhotoAnalysisPreview?=null
    private var photoPreviewSource:String?=null
    private fun clearPhotoUpload() {
        photoUploadOperation=null;photoUploadMessage=null;photoUploadFence=null;photoUploadContext=null
        photoReadMode=false;photoCancelMode=false;photoConfirmMode=false;photoEditMode=false;photoCanEditProposal=false;photoMealDraft=null;photoCancellationStatus=null;photoConfirmationStatus=null;photoAnalysisPreview=null;photoPreviewSource=null
        mutable.value=mutable.value.copy(photoUploadBusy=false,photoUpload=null,photoUploadMessage=null,
            photoReadBusy=false,photoAnalysis=null,photoCancelBusy=false,photoCancellation=null,photoConfirmBusy=false,photoConfirmation=null,photoDraftBusy=false,photoCanEditProposal=false,photoMealDraft=null)
    }
    private var photoCapabilitiesState: PhotoCapabilitiesState = PhotoCapabilitiesState.NotRequested
    private var photoCapabilitiesFence: Pair<OwnerLease, Long>? = null
    private var photoCapabilitiesContext: Triple<String, Int, String>? = null
    private enum class RankingStep { FIRST, NEXT, RETRY }
    private var privateReadKind = PrivateReadKind.PROFILE
    private var motivationState: MotivationState = MotivationState.NotRequested
    private var motivationFence: Pair<OwnerLease, Long>? = null
    private var consentState: RankingConsentState = RankingConsentState.NotRequested
    private var consentFence: Pair<OwnerLease, Long>? = null
    private var consentServerContext: Pair<Int, String>? = null
    private var consentOperation: String? = null
    private var rankingState: RankingState = RankingState.NotRequested
    private var rankingFence: Pair<OwnerLease, Long>? = null
    private var rankingServerContext: Triple<String, Int, String>? = null
    private var rankingRetryQuery: RankingQuery? = null
    private var rankingNextQuery: RankingQuery? = null
    private var rankingRetryExpiry: java.time.Instant? = null
    private var nemesisMutationOperation: String? = null
    private var nemesisMutationState: NemesisMutationState = NemesisMutationState.Idle
    private var nemesisMutationFence: Pair<OwnerLease,Long>? = null
    private var nemesisMutationContext: Triple<String,Int,String>? = null
    private var nemesisDecisionSource: NemesisDecisionSource? = null
    private var nemesisState: NemesisState = NemesisState.NotRequested
    private var nemesisFence: Pair<OwnerLease, Long>? = null
    private var nemesisServerContext: Triple<String, Int, String>? = null
    private var nemesisVersion: Pair<String, Pair<Long, java.time.Instant>>? = null
    private var nemesisRetryQuery: NemesisQuery? = null
    private var nemesisNextQuery: NemesisQuery.Listing? = null
    private var mealPushOperation:String?=null
    private var mealPushFence:Pair<OwnerLease,AccountBindingEntity>?=null
    private var mealPushMessage:String?=null
    private var conflictState=ConflictListView()
    private var conflictBusy=false
    private var conflictFence:Pair<OwnerLease,AccountBindingEntity>?=null
    private val conflictKeys=mutableMapOf<String,String>()
    private var conflictTicket:Pair<String,ConflictTicket>?=null
    private fun clearConflicts() {
        conflictState=ConflictListView();conflictKeys.clear();conflictTicket=null;conflictFence=null;conflictBusy=false
        mutable.value=mutable.value.copy(conflictBusy=false,conflicts=conflictState)
    }
    private fun clearMealPush() { mealPushOperation=null;mealPushFence=null;mealPushMessage=null
        clearConflicts()
        mutable.value=mutable.value.copy(mealPushBusy=false,mealPush=null,mealPushMessage=null,mealPushRetryAt=0) }
    private var snapshotOperation: String? = null
    private var diaryApplying = false
    private val snapshots = snapshotProtocol?.let { ServerSnapshotStore(db, it) }
    private val snapshotProtocol = snapshotProtocol
    private var serverProfile: ProfileRead? = null
    private var profileFence: Pair<OwnerLease, Long>? = null
    private var profileServerContext: Pair<Int, String>? = null
    private var sessionRevision = 0L
    private val bootstraps = AccountBootstrapStore(db)
    private val mutable = MutableStateFlow(SessionView(configured = issuer.isNotEmpty()))
    val view = mutable.asStateFlow()
    /** In-memory confirmation is invalidated also by an external Room context update. */
    suspend fun observeMotivationContext() {
        try {
            db.invalidationTracker.createFlow("account_bindings", "local_active_owner", "local_owners", "photo_analysis_requests", "sync_push_batches", "outbox", "server_snapshot_access", "server_diary_applications").collect {
                mutex.withLock {
                    if (mutable.value.binding != null) publish(mutable.value.message)
                }
            }
        } catch (error: CancellationException) { throw error }
        catch (_: Exception) { mutex.withLock {
            clearPhotoUpload()
            clearMotivation()
            clearRanking(); clearNemesis()
            nemesisMutationOperation = null
            mutable.value = mutable.value.copy(motivation = MotivationState.NotRequested, rankingConsent = RankingConsentState.NotRequested,
                ranking = RankingState.NotRequested, nemesis = NemesisState.NotRequested,
                nemesisDecision = null, nemesisMutationBusy = false, nemesisMutation = NemesisMutationState.Idle)
        } }
    }
    private fun copyRecord() = JSONObject(record.toString())
    private suspend fun persist(value: JSONObject) {
        withContext(Dispatchers.IO) { vault.write(value) }; record = value; sessionRevision++
    }
    private suspend fun forget() {
        // A failed Keystore/storage cleanup never re-enables a session or blocks the diary.
        withContext(Dispatchers.IO) { try { vault.clear() } catch (_: Exception) { } }
        record = JSONObject()
        sessionRevision++
    }
    private suspend fun binding(): SessionBinding {
        val lease = owners.currentLease()
        return SessionBinding(checkNotNull(db.ownerDao().byScope(lease.storageScope)), lease)
    }
    private fun sessionFor(value: SessionBinding): JSONObject? = record.optJSONObject("session")?.takeIf {
        it.optString("ownerId") == value.owner.id && it.optString("issuer") == value.owner.issuer && it.optString("subject") == value.owner.subject
    }
    private fun clearPhotoCapabilities() {
        photoCapabilitiesState = PhotoCapabilitiesState.NotRequested
        photoCapabilitiesFence = null
        photoCapabilitiesContext = null
        mutable.value = mutable.value.copy(photoCapabilitiesBusy = false, photoCapabilities = PhotoCapabilitiesState.NotRequested)
    }
    private fun clearMotivation() {
        clearPhotoCapabilities()
        motivationState = MotivationState.NotRequested
        motivationFence = null
        consentState = RankingConsentState.NotRequested
        consentFence = null
        consentServerContext = null
    }
    private fun clearRanking() {
        rankingState = RankingState.NotRequested; rankingFence = null; rankingServerContext = null
        rankingRetryQuery = null; rankingNextQuery = null; rankingRetryExpiry = null
    }
    /** Leave/stop of the ranking view removes peers, cursors and the authority of a held read. */
    suspend fun clearRankingPreview() = mutex.withLock {
        if (privateReadKind == PrivateReadKind.RANKING) profileOperation = null
        clearRanking()
        try { publish() } catch (_: Exception) { mutable.value = mutable.value.copy(rankingBusy = false, ranking = RankingState.NotRequested) }
    }
    private fun clearNemesis() {
        nemesisState = NemesisState.NotRequested; nemesisFence = null; nemesisServerContext = null
        nemesisRetryQuery = null; nemesisNextQuery = null; nemesisVersion = null
        nemesisDecisionSource = null; nemesisMutationState = NemesisMutationState.Idle
        nemesisMutationFence = null; nemesisMutationContext = null
    }
    suspend fun clearNemesisPreview() = mutex.withLock {
        if (privateReadKind == PrivateReadKind.NEMESIS) profileOperation = null
        nemesisMutationOperation = null
        clearNemesis()
        try { publish() } catch (_: Exception) {
            mutable.value = mutable.value.copy(nemesisBusy = false, nemesis = NemesisState.NotRequested,
                nemesisDecision = null, nemesisMutationBusy = false, nemesisMutation = NemesisMutationState.Idle)
        }
    }
    private fun pendingConsent(current: SessionBinding, server: AccountBindingEntity?): RankingConsentAttempt? = try {
        record.optJSONObject("rankingConsentAttempt")?.let(RankingConsentAttempt::restore)?.takeIf {
            sessionFor(current) != null && current.owner.kind == "account" && server != null && !server.requiresRecovery &&
                it.ownerScope == current.lease.storageScope && it.leaseGeneration == current.lease.generation &&
                it.accountId == server.accountId && it.accountGeneration == server.accountGeneration &&
                it.syncEpoch == server.syncEpoch && it.contextRevision == server.contextRevision
        }
    } catch (_: Exception) { null }
    private suspend fun publish(message: String? = null) {
        val current = binding()
        val session = sessionFor(current)
        val fresh = session?.let { AuthState.jsonDeserialize(it.getString("authState")).accessTokenExpirationTime?.let { expiry -> expiry > now() + 30_000 } } == true
        val server = db.bootstrapDao().binding(current.lease.storageScope)
        if ((photoCapabilitiesState is PhotoCapabilitiesState.Ready || photoCapabilitiesFence != null) && (session == null || server == null || server.requiresRecovery ||
            photoCapabilitiesFence != (current.lease to server.contextRevision) ||
            photoCapabilitiesContext != Triple(server.accountId, server.accountGeneration, server.syncEpoch))) {
            if (privateReadKind == PrivateReadKind.PHOTO) profileOperation = null
            clearPhotoCapabilities()
        }
        serverProfile?.let { confirmed ->
            if (session == null || server == null || server.requiresRecovery || profileFence != (current.lease to server.contextRevision) ||
                profileServerContext != (server.accountGeneration to server.syncEpoch) || confirmed.accountId != server.accountId || confirmed.syncEpoch != server.syncEpoch) {
                serverProfile = null; profileFence = null; profileServerContext = null
            }
        }
        (motivationState as? MotivationState.Ready)?.let { confirmed ->
            if (session == null || server == null || server.requiresRecovery ||
                motivationFence != (current.lease to server.contextRevision) ||
                confirmed.read.accountGeneration != server.accountGeneration || confirmed.read.syncEpoch != server.syncEpoch) clearMotivation()
        }
        if (consentState is RankingConsentState.Ready || consentState is RankingConsentState.Confirmed) {
            if (session == null || server == null || server.requiresRecovery || consentFence != (current.lease to server.contextRevision) ||
                consentServerContext != (server.accountGeneration to server.syncEpoch)) {
                consentState = RankingConsentState.NotRequested; consentFence = null
            }
        }
        if (rankingFence != null && (session == null || server == null || server.requiresRecovery ||
            rankingFence != (current.lease to server.contextRevision) ||
            rankingServerContext != Triple(server.accountId, server.accountGeneration, server.syncEpoch))) {
            if (privateReadKind == PrivateReadKind.RANKING) profileOperation = null
            clearRanking(); clearNemesis()
        }
        if (nemesisFence != null && (session == null || server == null || server.requiresRecovery ||
            nemesisFence != (current.lease to server.contextRevision) ||
            nemesisServerContext != Triple(server.accountId, server.accountGeneration, server.syncEpoch))) {
            if (privateReadKind == PrivateReadKind.NEMESIS) profileOperation = null
            clearNemesis()
        }
        if (nemesisMutationFence != null && (session == null || server == null || server.requiresRecovery ||
            nemesisMutationFence != (current.lease to server.contextRevision) ||
            nemesisMutationContext != Triple(server.accountId,server.accountGeneration,server.syncEpoch))) {
            nemesisMutationOperation = null; clearNemesis()
        }
        // Only an obsolete, well-formed context is discarded. A malformed unknown attempt blocks a new key.
        if (restoredNemesisAttempt() != null && currentNemesisAttempt(current,server) == null) {
            nemesisMutationOperation = null
            persist(copyRecord().also { it.remove("nemesisAttempt") }); clearNemesis()
        }
        if(photoUploadFence!=null && (session==null || server==null || server.requiresRecovery ||
            photoUploadFence!=(current.lease to server.contextRevision) ||
            photoUploadContext!=Triple(server.accountId,server.accountGeneration,server.syncEpoch))) clearPhotoUpload()
        if(mealPushFence!=null && (session==null || server!=mealPushFence?.second ||
            current.lease!=mealPushFence?.first)) clearMealPush()
        if(conflictFence!=null && (server==null || server.requiresRecovery ||
            conflictFence!=(current.lease to server))) clearConflicts()
        val mealStatus=if(current.owner.kind=="account")mealPushStore?.status(current.lease) else null
        val photoRow=if(current.owner.kind=="account" && session!=null && photoAnalysisStores!=null)
            db.photoAnalysisDao().get(current.lease.storageScope) else null
        if(photoPreviewSource!=photoRow?.receiptJson || photoRow?.blockedCode!=null) {
            photoAnalysisPreview=null;photoCancellationStatus=null;photoConfirmationStatus=null;photoPreviewSource=null;photoMealDraft=null;photoCanEditProposal=false
        }
        owners.requireCurrent(current.lease)
        val photoStatus=photoRow?.let { row->PhotoUploadStatus(row.operationId,row.sourcePhotoId,row.provider,row.model,
            row.attempted,row.receiptJson!=null,maxOf(row.retryAtMillis,session?.optLong("apiRetryAt")?:0),
            row.blockedCode!=null || server==null || server.requiresRecovery || !photoMatches(row,server)) }
        val pendingNemesis = currentNemesisAttempt(current,server)
        val pendingConsent = pendingConsent(current, server)
        val consentBusy = consentOperation != null || (profileOperation != null && privateReadKind == PrivateReadKind.CONSENTS)
        mutable.value = SessionView(current, configured = issuer.isNotEmpty(), pendingLogin = record.has("pending"), hasSession = fresh,
            message = message, apiConfigured = bootstrapGateway != null, bootstrapBusy = bootstrapOperation != null,
            serverLinked = server != null, requiresRecovery = server?.requiresRecovery == true,
            profileBusy = profileOperation != null && privateReadKind == PrivateReadKind.PROFILE, serverProfile = serverProfile,
            snapshotBusy = snapshotOperation != null, snapshot = snapshots?.status(current.lease),
            diaryApplication=if(current.owner.kind=="account")diaryStore?.latest(current.lease) else null,
            diaryApplying=diaryApplying && snapshotOperation!=null,
            mealPushConfigured=mealPushGateway!=null && mealPushStore!=null && mealPushProtocol!=null && snapshots!=null,
            mealPushBusy=mealPushOperation!=null,mealPush=mealStatus,mealPushMessage=mealPushMessage,
            conflictBusy=conflictBusy,conflicts=conflictState,
            mealPushRetryAt=maxOf(session?.optLong("apiRetryAt")?:0,mealStatus?.retryAtMillis?:0).takeIf {it>now()}?:0,
            photoCapabilitiesConfigured = photoCapabilitiesGateway != null,
            photoCapabilitiesBusy = profileOperation != null && privateReadKind == PrivateReadKind.PHOTO,
            photoCapabilities = photoCapabilitiesState,
            photoUploadConfigured=photoAnalysisGateway!=null && photoAnalysisStores!=null,
            photoUploadBusy=photoUploadOperation!=null,photoUpload=photoStatus,photoUploadMessage=photoUploadMessage,
            photoReadBusy=photoUploadOperation!=null && photoReadMode && !photoEditMode,photoAnalysis=photoAnalysisPreview,
            photoCancelBusy=photoUploadOperation!=null && photoCancelMode,photoCancellation=photoCancellationStatus,
            photoConfirmBusy=photoUploadOperation!=null && photoConfirmMode,photoConfirmation=photoConfirmationStatus,
            photoDraftBusy=photoUploadOperation!=null && photoEditMode,photoCanEditProposal=photoCanEditProposal,photoMealDraft=photoMealDraft,
            motivationConfigured = motivationGateway != null,
            motivationBusy = profileOperation != null && privateReadKind == PrivateReadKind.MOTIVATION,
            motivation = if (profileOperation != null && privateReadKind == PrivateReadKind.MOTIVATION) MotivationState.Loading else motivationState,
            rankingConsentConfigured = rankingConsentGateway != null && profileGateway != null && motivationGateway != null,
            rankingConsentBusy = consentBusy,
            rankingConsent = if (consentBusy) RankingConsentState.Loading else pendingConsent?.let { RankingConsentState.Pending(it.ranking) } ?: consentState,
            rankingConfigured = rankingGateway != null && motivationGateway != null,
            rankingBusy = profileOperation != null && privateReadKind == PrivateReadKind.RANKING,
            ranking = if (profileOperation != null && privateReadKind == PrivateReadKind.RANKING) RankingState.Loading else rankingState,
            nemesisConfigured = nemesisGateway != null && motivationGateway != null,
            nemesisBusy = profileOperation != null && privateReadKind == PrivateReadKind.NEMESIS,
            nemesis = if (profileOperation != null && privateReadKind == PrivateReadKind.NEMESIS) NemesisState.Loading else nemesisState,
            nemesisDecision = nemesisDecisionSource,
            nemesisMutationConfigured = nemesisWriteGateway != null,
            nemesisMutationBusy = nemesisMutationOperation != null,
            nemesisMutation = if (nemesisMutationOperation != null) NemesisMutationState.Sending
                else pendingNemesis?.let { NemesisMutationState.Pending(it.command.action,message) }
                ?: if (record.has("nemesisAttempt")) NemesisMutationState.Blocked
                else nemesisMutationState)
    }
    suspend fun start() = mutex.withLock {
        if (mutable.value.binding != null) return@withLock
        try {
            var message: String? = null
            record = try { withContext(Dispatchers.IO) { vault.read() } } catch (_: Exception) {
                forget(); message = "Sesja wymaga ponownego logowania. Lokalny dziennik został zachowany."; JSONObject()
            }
            val current = binding()
            val pending = record.optJSONObject("pending")
            val validPending = pending != null && pending.optString("scope") == current.lease.storageScope &&
                pending.optLong("generation") == current.lease.generation && pending.optString("issuer") == issuer &&
                now() - pending.optLong("createdAt") in 0..600_000
            val next = copyRecord()
            if (!validPending) next.remove("pending")
            if (sessionFor(current)?.optString("issuer") != issuer) next.remove("session")
            if (next.has("session")) try {
                val state = AuthState.jsonDeserialize(next.getJSONObject("session").getString("authState"))
                validateDiscovery(checkNotNull(state.authorizationServiceConfiguration), issuer)
            } catch (_: Exception) {
                next.remove("session"); message = "Sesja wymaga ponownego logowania. Lokalny dziennik został zachowany."
            }
            // A session-storage failure must not prevent opening the existing offline diary.
            try { persist(next) } catch (_: Exception) { record = JSONObject(); message = "Pamięć sesji jest niedostępna. Dziennik działa offline." }
            publish(message)
        } catch (error: CancellationException) { throw error }
        catch (_: Exception) { mutable.value = mutable.value.copy(message = "Nie udało się otworzyć dziennika. Spróbuj ponownie.") }
    }
    private suspend fun fail(id: String, message: String) = mutex.withLock {
        if (operation != id) return@withLock
        operation = null
        publish(message)
    }
    suspend fun beginLogin(): Intent? {
        val id = UUID.randomUUID().toString()
        val captured = try { mutex.withLock {
            if (issuer.isEmpty() || mutable.value.busy || record.has("pending")) return null
            requireHttps(issuer)
            val lease = owners.currentLease()
            bootstrapOperation = null
            profileOperation = null
            snapshotOperation = null
            clearMealPush()
            consentOperation = null
            clearPhotoUpload()
            nemesisMutationOperation = null
            if (record.has("nemesisAttempt")) persist(copyRecord().also { it.remove("nemesisAttempt") })
            serverProfile = null
            clearMotivation()
            clearRanking(); clearNemesis()
            operation = id
            mutable.value = mutable.value.copy(busy = true, bootstrapBusy = false, profileBusy = false, snapshotBusy = false, snapshot = null, serverProfile = null,
                motivationBusy = false, motivation = MotivationState.NotRequested, rankingConsentBusy = false,
                rankingConsent = RankingConsentState.NotRequested, rankingBusy = false, ranking = RankingState.NotRequested,
                nemesisBusy = false, nemesis = NemesisState.NotRequested, nemesisDecision = null, nemesisMutationBusy = false, nemesisMutation = NemesisMutationState.Idle, message = null)
            lease
        } } catch (error: CancellationException) { throw error }
        catch (_: Exception) { mutable.value = mutable.value.copy(message = "Logowanie jest niedostępne. Dziennik działa offline."); return null }
        try {
            val config = withTimeout(30_000) { gateway.discover(issuer) }
            validateDiscovery(config, issuer)
            val request = AuthorizationRequest.Builder(config, SessionClaims.CLIENT_ID, ResponseTypeValues.CODE,
                Uri.parse(AuthReturn.redirect(applicationId))).setScope("openid profile").setPrompt("login").build()
            check(request.codeVerifierChallengeMethod == "S256" && !request.nonce.isNullOrEmpty() && !request.state.isNullOrEmpty())
            val intent = gateway.browser(request)
            return mutex.withLock {
                if (operation != id) return@withLock null
                owners.requireCurrent(captured)
                persist(copyRecord().put("pending", JSONObject().put("id", id).put("issuer", issuer)
                    .put("scope", captured.storageScope).put("generation", captured.generation).put("createdAt", now())
                    .put("request", request.jsonSerializeString())))
                operation = null
                publish()
                intent
            }
        } catch (error: CancellationException) { fail(id, "Logowanie przerwane. Dziennik działa offline."); throw error }
        catch (_: Exception) { fail(id, "Nie udało się rozpocząć logowania. Sprawdź połączenie i spróbuj ponownie."); return null }
    }
    suspend fun cancelLogin() = mutex.withLock {
        operation = null
        val next = copyRecord().also { it.remove("pending") }
        try { persist(next) } catch (_: Exception) {
            forget()
        }
        publish("Logowanie anulowane. Dane lokalne zachowane.")
    }
    suspend fun completeLogin(intent: Intent?) {
        // The Android intent is untrusted, including the request serialized inside it.
        val response = try { intent?.let(AuthorizationResponse::fromIntent) } catch (_: Exception) { null }
        if (response == null) { cancelLogin(); return }
        var id: String? = null
        try {
            val captured = mutex.withLock {
                val pending = checkNotNull(record.optJSONObject("pending"))
                val lease = owners.currentLease()
                require(pending.getString("scope") == lease.storageScope && pending.getLong("generation") == lease.generation)
                require(pending.getString("issuer") == issuer && now() - pending.getLong("createdAt") in 0..600_000)
                val saved = AuthorizationRequest.jsonDeserialize(pending.getString("request"))
                require(StrictJson.canonical(saved.jsonSerialize()) == StrictJson.canonical(response.request.jsonSerialize()))
                require(response.state == saved.state && !response.authorizationCode.isNullOrEmpty())
                require(saved.redirectUri.toString() == AuthReturn.redirect(applicationId) && saved.clientId == SessionClaims.CLIENT_ID)
                validateDiscovery(saved.configuration, issuer)
                id = pending.getString("id")
                // Consume BEFORE exchanging the one-use code. After a lost response, log in again.
                persist(copyRecord().also { it.remove("pending") })
                operation = id
                mutable.value = mutable.value.copy(busy = true, pendingLogin = false, message = null)
                lease
            }
            val tokens = withTimeout(30_000) { gateway.tokens(response.createTokenExchangeRequest()) }
            val identity = SessionClaims.identity(checkNotNull(tokens.idToken), issuer, response.request.nonce, now() / 1000)
            require(tokens.tokenType.equals("Bearer", ignoreCase = true) && !tokens.accessToken.isNullOrEmpty())
            require(checkNotNull(tokens.accessTokenExpirationTime) > now())
            val state = AuthState(response, null).apply { update(tokens, null) }
            mutex.withLock {
                if (operation != id) return@withLock
                owners.requireCurrent(captured)
                val owner = owners.registerIdentity(identity.issuer, identity.subject)
                val next = copyRecord().put("session", JSONObject().put("ownerId", owner.id)
                    .put("issuer", identity.issuer).put("subject", identity.subject).put("authState", state.jsonSerializeString()))
                // Persist first. A crash before Room selection cannot activate this identity.
                persist(next)
                // UI is removed before selecting the new lease; stale writes also fail in Room.
                mutable.value = mutable.value.copy(binding = null)
                owners.selectIfCurrent(captured, owner.id)
                operation = null
                publish("Zalogowano. To konto ma osobny dziennik; dane gościa pozostają zachowane.")
            }
        } catch (error: CancellationException) { id?.let { fail(it, "Logowanie przerwane. Dziennik działa offline.") }; throw error }
        catch (_: Exception) {
            if (id != null) fail(id!!, "Logowanie nie zostało potwierdzone. Dane lokalne zachowane.")
            else mutex.withLock { mutable.value = mutable.value.copy(message = "Odrzucono nieaktualny lub nieprawidłowy powrót z logowania.") }
        }
    }
    suspend fun logout() {
        var previous = mutable.value.binding
        try { mutex.withLock {
        previous = mutable.value.binding
        val captured = owners.currentLease()
        val guest = owners.ensureGuest()
        // Local logout removes all tokens and pending codes; it does not delete any diary.
        operation = null
        bootstrapOperation = null
        profileOperation = null
        snapshotOperation = null
        clearMealPush()
        consentOperation = null
        clearPhotoUpload()
        nemesisMutationOperation = null
        serverProfile = null
        clearMotivation()
        clearRanking(); clearNemesis()
        forget()
        mutable.value = mutable.value.copy(binding = null)
        owners.selectIfCurrent(captured, guest.id)
        publish("Wylogowano z aplikacji. Otwarty dziennik gościa.")
        } } catch (error: CancellationException) { throw error }
        catch (_: Exception) { mutex.withLock {
            operation = null
            try { publish("Nie udało się otworzyć gościa. Spróbuj ponownie; dziennik konta pozostaje lokalny.") }
            catch (_: Exception) { mutable.value = mutable.value.copy(binding = previous, busy = false, hasSession = false,
                motivationBusy = false, motivation = MotivationState.NotRequested,
                rankingBusy = false, ranking = RankingState.NotRequested,
                nemesisBusy = false, nemesis = NemesisState.NotRequested,
                nemesisDecision = null, nemesisMutationBusy = false, nemesisMutation = NemesisMutationState.Idle,
                message = "Pamięć dziennika jest niedostępna. Spróbuj ponownie.") }
        } }
    }
    suspend fun refresh() { refreshFor(null) }
    private suspend fun refreshFor(expected: OwnerLease?, contextFence: SyncContextFence? = null): Boolean {
        val id = UUID.randomUUID().toString()
        var registered = false
        try {
            val captured = mutex.withLock {
                expected?.let { owners.requireCurrent(it) }
                check(contextFence == null || contextFence.lease == expected)
                contextFence?.let { requireSyncContext(it) }
                check(!mutable.value.busy && !record.has("pending"))
                val current = binding()
                val session = checkNotNull(sessionFor(current))
                require(session.getString("issuer") == issuer)
                val state = AuthState.jsonDeserialize(session.getString("authState"))
                validateDiscovery(checkNotNull(state.authorizationServiceConfiguration), issuer)
                operation = id
                registered = true
                serverProfile = null
                clearMotivation()
                // Manual renewal invalidates a held private read. Automatic renewal belongs to it.
                if (expected == null) { clearMealPush(); clearPhotoUpload(); profileOperation = null; consentOperation = null; nemesisMutationOperation = null; clearRanking(); clearNemesis() }
                mutable.value = mutable.value.copy(busy = true, profileBusy = profileOperation != null && privateReadKind == PrivateReadKind.PROFILE,
                    motivationBusy = profileOperation != null && privateReadKind == PrivateReadKind.MOTIVATION,
                    serverProfile = null, motivation = MotivationState.NotRequested, rankingConsent = RankingConsentState.NotRequested,
                    rankingConsentBusy = expected != null && (consentOperation != null || (profileOperation != null && privateReadKind == PrivateReadKind.CONSENTS)),
                    rankingBusy = expected != null && profileOperation != null && privateReadKind == PrivateReadKind.RANKING,
                    ranking = if (expected != null && privateReadKind == PrivateReadKind.RANKING) RankingState.Loading else RankingState.NotRequested,
                    nemesisBusy = expected != null && profileOperation != null && privateReadKind == PrivateReadKind.NEMESIS,
                    nemesis = if (expected != null && privateReadKind == PrivateReadKind.NEMESIS) NemesisState.Loading else NemesisState.NotRequested,
                    nemesisDecision = null, nemesisMutationBusy = expected != null && nemesisMutationOperation != null,
                    nemesisMutation = if (expected != null && nemesisMutationOperation != null) NemesisMutationState.Sending else NemesisMutationState.Idle, message = null)
                Triple(current, state, SessionIdentity(session.getString("issuer"), session.getString("subject")))
            }
            val tokens = withTimeout(30_000) { gateway.tokens(captured.second.createTokenRefreshRequest()) }
            tokens.idToken?.let { SessionClaims.identity(it, issuer, null, now() / 1000, captured.third) }
            require(tokens.tokenType.equals("Bearer", ignoreCase = true) && !tokens.accessToken.isNullOrEmpty())
            require(checkNotNull(tokens.accessTokenExpirationTime) > now())
            return mutex.withLock {
                if (operation != id) return@withLock false
                suspend fun applyRefreshed(): Boolean {
                    owners.requireCurrent(captured.first.lease)
                    contextFence?.let { requireSyncContext(it) }
                    captured.second.update(tokens, null)
                    val session = checkNotNull(sessionFor(captured.first))
                    persist(copyRecord().put("session", JSONObject(session.toString()).put("authState", captured.second.jsonSerializeString())))
                    operation = null
                    publish("Sesja odnowiona. Dziennik zachowany.")
                    return true
                }
                // Keep the context check and token write indivisible with respect to Room owner/context changes.
                if (contextFence == null) applyRefreshed() else db.withTransaction { applyRefreshed() }
            }
        } catch (error: CancellationException) {
            withContext(NonCancellable) { fail(id, "Odnowienie przerwane. Dziennik działa offline.") }; throw error
        }
        catch (_: Exception) {
            mutex.withLock {
                if (registered && operation != id) return@withLock
                if (operation != null && operation != id) return@withLock
                if (contextFence != null) {
                    // A queued command for A must not publish a login failure in a new context.
                    if (!registered) return@withLock
                    val current = try { requireSyncContext(contextFence); true }
                        catch (error: CancellationException) { throw error }
                        catch (_: Exception) { false }
                    if (!current) {
                        if (operation == id) { operation = null; publish() }
                        return@withLock
                    }
                }
                if (operation == id) operation = null
                publish("Sesji nie udało się odnowić. Dziennik działa offline; spróbuj zalogować się ponownie.")
            }
            contextFence?.let { mutex.withLock { requireSyncContext(it) } }
            return false
        }
    }

    /** Must be called under mutex. A refresh, pending login, logout or ABA invalidates the ticket. */
    private suspend fun captureApi(lease: OwnerLease): ApiSession {
        owners.requireCurrent(lease)
        check(operation == null && !record.has("pending"))
        val current = binding()
        val session = checkNotNull(sessionFor(current))
        val identity = SessionIdentity(session.getString("issuer"), session.getString("subject"))
        require(identity.issuer == issuer && identity.issuer == current.owner.issuer && identity.subject == current.owner.subject)
        val serialized = session.getString("authState")
        val state = AuthState.jsonDeserialize(serialized)
        require(checkNotNull(state.accessTokenExpirationTime) > now() + 30_000)
        val token = checkNotNull(state.accessToken)
        require(token.isNotBlank())
        return ApiSession(identity, lease, token, serialized, sessionRevision)
    }
    private suspend fun requireApi(ticket: ApiSession) {
        val current = captureApi(ticket.lease)
        check(current.identity == ticket.identity && current.authState == ticket.authState && current.revision == ticket.revision)
    }
    internal suspend fun apiSession(lease: OwnerLease): ApiSession = mutex.withLock { captureApi(lease) }
    private suspend fun apiSession(fence: SyncContextFence): ApiSession = mutex.withLock {
        db.withTransaction { requireSyncContext(fence); captureApi(fence.lease) }
    }
    internal suspend fun <T> withApiSession(ticket: ApiSession, proof: ApiReadProof? = null, block: suspend () -> T): T = mutex.withLock {
        db.withTransaction {
            try { requireApi(ticket) }
            catch (error: StaleOwnerException) { proof?.staleOwnerRejected(); throw error }
            block()
        }
    }

    /** Explicit E3 connection, never a diary sync or an implicit guest import. */
    suspend fun bootstrap() { bootstrapFor(null, null) }

    /** A worker/reconciliation command cannot follow a later account selection or context update. */
    suspend fun bootstrap(expectedLease: OwnerLease, expectedContext: AccountBindingEntity?) {
        bootstrapFor(expectedLease, expectedContext)
    }
    internal suspend fun executeBootstrapStep(expectedLease: OwnerLease, expectedContext: AccountBindingEntity?): SyncCommandOutcome =
        bootstrapFor(expectedLease, expectedContext)
    internal suspend fun executePullStep(expectedLease: OwnerLease, expectedContext: AccountBindingEntity): SyncCommandOutcome =
        pullFor(expectedLease, expectedContext, allowRecovery = false)
    internal suspend fun executePushStep(expectedLease: OwnerLease, expectedContext: AccountBindingEntity): SyncCommandOutcome =
        pushFor(expectedLease, expectedContext, followWithPull = false)

    private suspend fun bootstrapFor(expectedLease: OwnerLease?, expectedContext: AccountBindingEntity?): SyncCommandOutcome {
        val gateway = bootstrapGateway ?: return SyncCommandOutcome.NotConfigured
        val id = UUID.randomUUID().toString()
        val fence = try { mutex.withLock {
            expectedLease?.let { owners.requireCurrent(it) }
            if (bootstrapOperation != null || operation != null || record.has("pending")) return SyncCommandOutcome.Busy
            if (mealPushOperation != null || profileOperation != null || snapshotOperation != null || consentOperation != null || photoUploadOperation != null || nemesisMutationOperation != null) return SyncCommandOutcome.Busy
            val current = binding()
            expectedLease?.let { if (current.lease != it) throw StaleOwnerException() }
            val capturedContext = db.bootstrapDao().binding(current.lease.storageScope)
            if (expectedLease != null && expectedContext != capturedContext) throw SyncContextChangedException()
            if (current.owner.kind != "account" || sessionFor(current) == null) {
                publish("Zaloguj się, aby połączyć konto z serwerem. Dziennik działa offline."); return SyncCommandOutcome.LoginRequired
            }
            val retryAt = sessionFor(current)!!.optLong("apiRetryAt")
            if (retryAt > now()) {
                publish("Serwer jest zajęty. Ponów za co najmniej ${(retryAt - now() + 999) / 1000} s. Dziennik działa offline."); return SyncCommandOutcome.RetryAt(retryAt)
            }
            bootstrapOperation = id
            serverProfile = null
            clearMotivation()
            mutable.value = mutable.value.copy(bootstrapBusy = true, serverProfile = null, motivation = MotivationState.NotRequested, message = null)
            SyncContextFence(current.lease, capturedContext)
        } } catch (error: CancellationException) { throw error }
        catch (_: StaleOwnerException) { return SyncCommandOutcome.StaleContext }
        catch (_: SyncContextChangedException) { return SyncCommandOutcome.StaleContext }
        catch (_: Exception) {
            mutable.value = mutable.value.copy(bootstrapBusy = false, message = "Połączenie jest niedostępne. Dziennik pozostaje lokalny.")
            return SyncCommandOutcome.TransientFailure
        }
        val lease = fence.lease
        suspend fun ready() {
            check(bootstrapOperation == id)
            requireSyncContext(fence)
        }
        try {
            // Renew an expiring token only for the originally captured owner.
            val fresh = mutex.withLock {
                ready()
                val state = AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime ?: 0) > now() + 30_000
            }
            if (!fresh) check(refreshFor(lease, fence))
            var ticket = apiSession(fence)
            var request = withApiSession(ticket) { ready(); bootstraps.begin(lease) }
            var renewedKey = false
            var refreshed = false
            while (true) {
                val captured = ticket
                val result = gateway.post(captured, request.operationId) {
                    withApiSession(captured) { ready() }
                }
                if (result.status == 200) {
                    val response = BootstrapProtocol.parse(result.body)
                    val linked = withApiSession(captured) {
                        ready()
                        val server = bootstraps.apply(request, response)
                        bootstrapOperation = null
                        publish(if (server.requiresRecovery) "Konto połączone. Zmiana stanu serwera wymaga uzgodnienia danych; lokalny dziennik zachowany."
                            else "Konto połączone z serwerem. Posiłki i kolejka nadal pozostają lokalne.")
                        server
                    }
                    return SyncCommandOutcome.Bootstrapped(linked)
                }
                val code = if (result.status in setOf(429, 503)) "" else BootstrapHttpProtocol.errorCode(result.body)
                withApiSession(captured) { ready() }
                if (result.status == 401 && code == "unauthorized" && !refreshed) {
                    refreshed = true
                    check(refreshFor(lease, fence))
                    ticket = apiSession(fence)
                    withApiSession(ticket) { ready() }
                    continue // Same durable key, at most one renewal.
                }
                if (result.status == 409 && code in setOf("sync_epoch_changed", "account_generation_changed") && !renewedKey) {
                    request = withApiSession(captured) { ready(); bootstraps.renew(request) }
                    renewedKey = true
                    continue // At most one new key; old mapping and diary are preserved.
                }
                var outcome: SyncCommandOutcome = when (result.status) {
                    401 -> SyncCommandOutcome.LoginRequired
                    403, 409 -> SyncCommandOutcome.ReconciliationRequired(code)
                    else -> SyncCommandOutcome.TransientFailure
                }
                val message = when (result.status) {
                    401 -> "Sesja wymaga ponownego logowania. Dziennik działa offline."
                    403 -> "Serwer nie pozwala połączyć tego konta. Dziennik działa offline."
                    409 -> "Serwer zwrócił konflikt połączenia. Zachowano lokalne dane i klucz próby."
                    429, 503 -> {
                        val seconds = BootstrapHttpProtocol.retrySeconds(result.retryAfter, now())
                        val retryAt = Math.addExact(now(), Math.multiplyExact(seconds, 1000))
                        withApiSession(captured) {
                            ready()
                            val session = checkNotNull(sessionFor(binding()))
                            persist(copyRecord().put("session", JSONObject(session.toString()).put("apiRetryAt", retryAt)))
                        }
                        outcome = SyncCommandOutcome.RetryAt(retryAt)
                        "Serwer jest zajęty. Ponów za co najmniej $seconds s. Dziennik działa offline."
                    }
                    else -> "Nie udało się połączyć konta. Dziennik działa offline."
                }
                mutex.withLock {
                    if (bootstrapOperation == id) { ready(); bootstrapOperation = null; publish(message) }
                }
                return outcome
            }
        } catch (error: CancellationException) {
            withContext(NonCancellable) { finishBootstrap(id, fence) }; throw error
        } catch (_: StaleOwnerException) {
            finishBootstrap(id, fence); return SyncCommandOutcome.StaleContext
        } catch (_: SyncContextChangedException) {
            finishBootstrap(id, fence); return SyncCommandOutcome.StaleContext
        } catch (_: Exception) {
            finishBootstrap(id, fence); return SyncCommandOutcome.TransientFailure
        }
    }
    private suspend fun finishBootstrap(id: String, fence: SyncContextFence) = mutex.withLock {
        if (bootstrapOperation != id) return@withLock
        bootstrapOperation = null
        try {
            if (owners.currentLease() == fence.lease && db.bootstrapDao().binding(fence.lease.storageScope) == fence.server)
                publish("Połączenie nie zostało potwierdzone. Dane i klucz próby zachowane; możesz ponowić.")
            else publish()
        } catch (_: Exception) {
            mutable.value = mutable.value.copy(bootstrapBusy = false, message = "Połączenie nie zostało potwierdzone. Dziennik pozostaje lokalny.")
        }
    }

    /** Explicit online preview. Never upserts a local profile, recalculates goals or ACKs outbox. */
    suspend fun readPhotoCapabilities() = readPrivate(PrivateReadKind.PHOTO)
    suspend fun readProfile() = readPrivate(PrivateReadKind.PROFILE)
    suspend fun readMotivation() = readPrivate(PrivateReadKind.MOTIVATION)
    suspend fun readRankingConsents() = readPrivate(PrivateReadKind.CONSENTS)
    suspend fun readRanking() = readPrivate(PrivateReadKind.RANKING, RankingStep.FIRST)
    suspend fun nextRankingPage() = readPrivate(PrivateReadKind.RANKING, RankingStep.NEXT)
    suspend fun retryRankingPage() = readPrivate(PrivateReadKind.RANKING, RankingStep.RETRY)
    suspend fun readNemesis() = readPrivate(PrivateReadKind.NEMESIS, nemesisRequest = NemesisQuery.Listing())
    suspend fun readNemesisChallenge(id: String) {
        val query = try { NemesisQuery.Detail(id) } catch (_: Exception) { return }
        readPrivate(PrivateReadKind.NEMESIS, nemesisRequest = query)
    }
    suspend fun nextNemesisPage() {
        val query = mutex.withLock { if (nemesisState is NemesisState.ListReady) nemesisNextQuery else null } ?: return
        readPrivate(PrivateReadKind.NEMESIS, nemesisRequest = query, nemesisContinuation = true)
    }
    suspend fun retryNemesis() {
        val query = mutex.withLock { if ((nemesisState as? NemesisState.Failed)?.canRetry == true) nemesisRetryQuery else null } ?: return
        readPrivate(PrivateReadKind.NEMESIS, nemesisRequest = query, nemesisContinuation = true)
    }
    private suspend fun readPrivate(kind: PrivateReadKind, rankingStep: RankingStep? = null,
        nemesisRequest: NemesisQuery? = null, nemesisContinuation: Boolean = false) {
        val firstGateway: ProfileGateway = (when (kind) {
            PrivateReadKind.PHOTO -> photoCapabilitiesGateway
            PrivateReadKind.MOTIVATION, PrivateReadKind.RANKING, PrivateReadKind.NEMESIS -> motivationGateway
            else -> profileGateway
        }) ?: return
        if (kind == PrivateReadKind.CONSENTS && (motivationGateway == null || rankingConsentGateway == null)) return
        if (kind == PrivateReadKind.RANKING && rankingGateway == null) return
        if (kind == PrivateReadKind.NEMESIS && (nemesisGateway == null || nemesisRequest == null)) return
        val label = when (kind) { PrivateReadKind.PROFILE -> "profil"; PrivateReadKind.MOTIVATION -> "osiągnięcia"; PrivateReadKind.CONSENTS -> "zgody"; PrivateReadKind.RANKING -> "ranking"; PrivateReadKind.NEMESIS -> "Nemesis"; PrivateReadKind.PHOTO -> "dostępność analizy zdjęć" }
        val id = UUID.randomUUID().toString()
        var capturedLease: OwnerLease? = null
        var rankingQuery: RankingQuery? = null
        val capturedBinding = try { mutex.withLock {
            if (mealPushOperation != null || profileOperation != null || consentOperation != null || snapshotOperation != null || bootstrapOperation != null || operation != null || photoUploadOperation != null || nemesisMutationOperation != null || record.has("pending")) return
            val current = binding()
            capturedLease = current.lease
            if (current.owner.kind != "account" || sessionFor(current) == null) {
                publish("Zaloguj się, aby odczytać $label z serwera."); return
            }
            val server = db.bootstrapDao().binding(current.lease.storageScope)
            if (server == null || server.requiresRecovery) {
                publish("Najpierw połącz konto i uzgodnij stan serwera. Dziennik pozostaje lokalny."); return
            }
            if (kind == PrivateReadKind.CONSENTS && pendingConsent(current, server) != null) {
                publish("Poprzedni zapis zgody czeka na potwierdzenie. Ponów tę samą decyzję."); return
            }
            if (kind == PrivateReadKind.RANKING) {
                val continues = rankingStep != RankingStep.FIRST
                if (continues && (rankingFence != (current.lease to server.contextRevision) ||
                    rankingServerContext != Triple(server.accountId, server.accountGeneration, server.syncEpoch))) { clearRanking(); publish(); return }
                rankingQuery = when (rankingStep) {
                    RankingStep.FIRST -> RankingQuery()
                    RankingStep.NEXT -> if (rankingState is RankingState.Ready) rankingNextQuery else null
                    RankingStep.RETRY -> if ((rankingState as? RankingState.Failed)?.canRetry == true) rankingRetryQuery else null
                    null -> null
                } ?: return
                val expiry = if (rankingStep == RankingStep.NEXT) (rankingState as RankingState.Ready).page.expiresAt else rankingRetryExpiry
                if (continues && expiry != null && expiry.toEpochMilli() <= now()) {
                    clearRanking(); rankingState = RankingState.Failed("Strona rankingu wygasła. Pobierz listę od początku.", false); publish(); return
                }
                rankingRetryExpiry = if (rankingStep == RankingStep.FIRST) null else expiry
            }
            if (kind == PrivateReadKind.NEMESIS && nemesisContinuation &&
                (nemesisFence != (current.lease to server.contextRevision) ||
                    nemesisServerContext != Triple(server.accountId, server.accountGeneration, server.syncEpoch) ||
                    (nemesisRequest !== nemesisRetryQuery && nemesisRequest !== nemesisNextQuery))) {
                clearNemesis(); publish(); return
            }
            if (kind == PrivateReadKind.NEMESIS) {
                if (nemesisFence != (current.lease to server.contextRevision) ||
                    nemesisServerContext != Triple(server.accountId, server.accountGeneration, server.syncEpoch) ||
                    nemesisRequest !is NemesisQuery.Detail || nemesisVersion?.first != nemesisRequest.id) nemesisVersion = null
                nemesisFence = current.lease to server.contextRevision
                nemesisServerContext = Triple(server.accountId, server.accountGeneration, server.syncEpoch)
                nemesisRetryQuery = nemesisRequest; nemesisNextQuery = null
            }
            val retryAt = sessionFor(current)!!.optLong("apiRetryAt")
            if (retryAt > now()) {
                val message = "Serwer jest zajęty. Ponów za co najmniej ${(retryAt - now() + 999) / 1000} s."
                if (kind == PrivateReadKind.PHOTO) photoCapabilitiesState = PhotoCapabilitiesState.Failed(message)
                if (kind == PrivateReadKind.MOTIVATION) motivationState = MotivationState.Failed(message)
                if (kind == PrivateReadKind.CONSENTS) consentState = RankingConsentState.Failed(message)
                if (kind == PrivateReadKind.NEMESIS) nemesisState = NemesisState.Failed(message, true)
                if (kind == PrivateReadKind.RANKING) {
                    rankingRetryQuery = rankingQuery; rankingNextQuery = null
                    rankingFence = current.lease to server.contextRevision
                    rankingServerContext = Triple(server.accountId, server.accountGeneration, server.syncEpoch)
                    rankingState = RankingState.Failed(message, rankingQuery != null)
                }
                publish(message); return
            }
            profileOperation = id
            privateReadKind = kind
            serverProfile = null
            clearMotivation()
            if (kind != PrivateReadKind.NEMESIS) clearNemesis() else nemesisState = NemesisState.Loading
            if (kind != PrivateReadKind.RANKING) clearRanking()
            else {
                rankingState = RankingState.Loading; rankingRetryQuery = rankingQuery; rankingNextQuery = null
                rankingFence = current.lease to server.contextRevision
                rankingServerContext = Triple(server.accountId, server.accountGeneration, server.syncEpoch)
            }
            if (kind == PrivateReadKind.PHOTO) {
                photoCapabilitiesState = PhotoCapabilitiesState.Loading
                photoCapabilitiesFence = current.lease to server.contextRevision
                photoCapabilitiesContext = Triple(server.accountId, server.accountGeneration, server.syncEpoch)
            }
            if (kind == PrivateReadKind.MOTIVATION) motivationState = MotivationState.Loading
            publish()
            current.lease to server
        } } catch (error: CancellationException) {
            capturedLease?.let { withContext(NonCancellable) { finishPrivate(id, it, kind) } }
            throw error
        }
        catch (_: Exception) {
            capturedLease?.let { finishPrivate(id, it, kind) }
            return
        }
        val lease = capturedBinding.first
        val server = capturedBinding.second
        try {
            val fresh = mutex.withLock {
                owners.requireCurrent(lease)
                val state = AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime ?: 0) > now() + 30_000
            }
            if (!fresh) check(refreshFor(lease))
            var ticket = apiSession(lease)
            var refreshed = false
            var stagedProfile: ProfileRead? = null
            var stagedMotivation: MotivationRead? = null
            var stagedNemesis: NemesisChallenge? = null
            var readGateway = firstGateway
            while (true) {
                val captured = ticket
                suspend fun ready() {
                    check(profileOperation == id)
                    val active = bootstraps.requireReady(lease, server.contextRevision)
                    require(active.accountId == server.accountId && active.accountGeneration == server.accountGeneration && active.syncEpoch == server.syncEpoch)
                }
                val readProof = if (ApiReadObservation.ENABLED && kind == PrivateReadKind.PROFILE)
                    ApiReadObservation.proof("/api/v1/me") else null
                val result = readGateway.get(captured) { withApiSession(captured) { ready() } }
                if (result.status == 200) {
                    if (kind == PrivateReadKind.PHOTO) {
                        val capabilities = PhotoCapabilitiesProtocol.parse(result.body)
                        withApiSession(captured) {
                            ready()
                            photoCapabilitiesState = PhotoCapabilitiesState.Ready(capabilities)
                            photoCapabilitiesFence = lease to server.contextRevision
                            photoCapabilitiesContext = Triple(server.accountId, server.accountGeneration, server.syncEpoch)
                            profileOperation = null
                            publish("Sprawdzono dostępność analizy. Żadne zdjęcie nie zostało wysłane.")
                        }
                        return
                    }
                    val profileStage = kind == PrivateReadKind.PROFILE || (kind == PrivateReadKind.CONSENTS && stagedProfile == null)
                    val response = if (profileStage) ProfileReadProtocol.parse(result.body) else null
                    if (kind == PrivateReadKind.PROFILE && response != null) readProof?.dtoParsed()
                    val rankingStage = kind == PrivateReadKind.RANKING && stagedMotivation != null
                    val nemesisStage = kind == PrivateReadKind.NEMESIS && stagedMotivation != null
                    val motivation = if (!profileStage && !rankingStage && !nemesisStage) MotivationReadProtocol.parse(result.body) else null
                    val page = if (rankingStage) RankingReadProtocol.parse(result.body, checkNotNull(rankingQuery)) else null
                    val (nemesisPage, nemesisDetail, statistics) = if (nemesisStage) withContext(Dispatchers.Default) {
                        Triple(if (nemesisRequest is NemesisQuery.Listing) NemesisReadProtocol.page(result.body, nemesisRequest) else null,
                            if (nemesisRequest is NemesisQuery.Detail && stagedNemesis == null) NemesisReadProtocol.detail(result.body, nemesisRequest.id) else null,
                            stagedNemesis?.let { NemesisReadProtocol.statistics(result.body, it) })
                    } else Triple(null, null, null)
                    var continueRead = false
                    withApiSession(captured, readProof) {
                        ready()
                        // GET me has no account_generation; it cannot replace the bootstrap mapping.
                        require(response == null || response.accountId == server.accountId)
                        if ((response?.syncEpoch ?: motivation?.syncEpoch ?: checkNotNull(stagedMotivation).syncEpoch) != server.syncEpoch ||
                            (motivation != null && motivation.accountGeneration != server.accountGeneration)) {
                            db.bootstrapDao().update(server.copy(requiresRecovery = true,
                                contextRevision = Math.addExact(server.contextRevision, 1)))
                            profileOperation = null
                            clearMotivation()
                            clearRanking(); clearNemesis()
                            val message = "Stan serwera się zmienił. Lokalny dziennik zachowany; wymagane uzgodnienie danych."
                            if (kind == PrivateReadKind.PHOTO) photoCapabilitiesState = PhotoCapabilitiesState.Failed(message)
                            if (kind == PrivateReadKind.MOTIVATION) motivationState = MotivationState.Failed(message)
                            if (kind == PrivateReadKind.CONSENTS) consentState = RankingConsentState.Failed(message)
                            if (kind == PrivateReadKind.RANKING) rankingState = RankingState.Failed(message, false)
                            if (kind == PrivateReadKind.NEMESIS) nemesisState = NemesisState.Failed(message, false)
                            publish(message)
                        } else if (kind == PrivateReadKind.CONSENTS && response != null) {
                            stagedProfile = response
                            readGateway = checkNotNull(motivationGateway)
                            continueRead = true
                        } else if (kind == PrivateReadKind.NEMESIS && motivation != null) {
                            stagedMotivation = motivation
                            readGateway = object : ProfileGateway {
                                override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit) =
                                    checkNotNull(nemesisGateway).get(session, server.syncEpoch, checkNotNull(nemesisRequest), beforeSend)
                            }
                            continueRead = true
                        } else if (nemesisDetail != null && nemesisDetail.status in setOf("active", "finished")) {
                            stagedNemesis = nemesisDetail
                            readGateway = object : ProfileGateway {
                                override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit) =
                                    checkNotNull(nemesisGateway).get(session, server.syncEpoch, NemesisQuery.Statistics(nemesisDetail.id), beforeSend)
                            }
                            continueRead = true
                        } else if (kind == PrivateReadKind.RANKING && motivation != null) {
                            // Preflight each live page; no GET reaffirms ranking consent.
                            stagedMotivation = motivation
                            readGateway = object : ProfileGateway {
                                override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit) =
                                    checkNotNull(rankingGateway).get(session, checkNotNull(rankingQuery), beforeSend)
                            }
                            continueRead = true
                        } else {
                            serverProfile = response
                            if (response != null) {
                                profileFence = lease to server.contextRevision
                                profileServerContext = server.accountGeneration to server.syncEpoch
                            }
                            if (motivation != null) {
                                motivationState = MotivationState.Ready(motivation)
                                motivationFence = lease to server.contextRevision
                            }
                            if (kind == PrivateReadKind.CONSENTS) {
                                val source = checkNotNull(stagedProfile)
                                val ranking = checkNotNull(motivation).ranking
                                require(source.consents.ranking == ranking.requested && ranking.consentEpoch == server.syncEpoch)
                                consentState = RankingConsentState.Ready(RankingConsentSource(UUID.randomUUID().toString(), source.consents, ranking, now()))
                                consentFence = lease to server.contextRevision
                                consentServerContext = server.accountGeneration to server.syncEpoch
                            }
                            if (kind == PrivateReadKind.RANKING) {
                                rankingState = RankingState.Ready(checkNotNull(page))
                                rankingNextQuery = page.nextPageToken?.let(::RankingQuery)
                                motivationState = MotivationState.Ready(checkNotNull(stagedMotivation))
                                motivationFence = lease to server.contextRevision
                            }
                            if (kind == PrivateReadKind.NEMESIS) {
                                if (statistics != null) {
                                    val previous = nemesisVersion?.takeIf { it.first == checkNotNull(stagedNemesis).id }?.second
                                    require(previous == null || (statistics.revision >= previous.first && statistics.asOf >= previous.second))
                                    nemesisVersion = checkNotNull(stagedNemesis).id to (statistics.revision to statistics.asOf)
                                } else nemesisVersion = null
                                nemesisState = if (nemesisPage != null) NemesisState.ListReady(nemesisPage)
                                    else NemesisState.DetailReady(checkNotNull(nemesisDetail ?: stagedNemesis), statistics)
                                nemesisDecisionSource = (nemesisState as? NemesisState.DetailReady)?.challenge?.takeIf { it.status != "cancelled" }
                                    ?.let { NemesisDecisionSource(UUID.randomUUID().toString(),it,now()) }
                                nemesisNextQuery = nemesisPage?.nextCursor?.let { NemesisQuery.Listing(it) }
                                motivationState = MotivationState.Ready(checkNotNull(stagedMotivation)); motivationFence = lease to server.contextRevision
                            }
                            profileOperation = null
                            publish(if (kind == PrivateReadKind.PROFILE) "Odczytano profil serwerowy. Lokalny profil i cel kalorii zachowane."
                                else if (kind == PrivateReadKind.MOTIVATION) "Odczytano potwierdzenie serwerowe. Lokalny dziennik i zgoda rankingu zachowane."
                                else if (kind == PrivateReadKind.RANKING) "Odczytano bieżącą stronę rankingu. Kolejne strony mogą się zmieniać."
                                else if (kind == PrivateReadKind.NEMESIS) "Odczytano aktualne Nemesis. Lokalny dziennik i zgody zachowane."
                                else "Odczytano aktualne zgody. Udział w rankingu wymaga osobnej decyzji.")
                        }
                    }
                    if (continueRead) continue
                    return
                }
                val code = if (result.status in setOf(429, 503)) "" else BootstrapHttpProtocol.errorCode(result.body)
                withApiSession(captured) { ready() }
                if (result.status == 401 && code == "unauthorized" && !refreshed) {
                    refreshed = true
                    check(refreshFor(lease))
                    ticket = apiSession(lease)
                    withApiSession(ticket) { ready() }
                    continue
                }
                val message = when (result.status) {
                    401 -> "Sesja wymaga ponownego logowania. Dziennik działa offline."
                    403 -> if (code == "account_bootstrap_required") "Serwer wymaga ponownego połączenia konta."
                        else "Serwer nie pozwala odczytać danych tego konta."
                    409 -> if (kind == PrivateReadKind.NEMESIS && code == "nemesis_cursor_unavailable") "Strona Nemesis wygasła. Pobierz listę od początku."
                        else "Stan serwera wymaga ponownego sprawdzenia połączenia. Dane lokalne zachowane."
                    404 -> if (kind == PrivateReadKind.PHOTO) "Analiza zdjęć nie jest dostępna na tym serwerze. Dodaj posiłek ręcznie."
                        else "Rywalizacja lub udostępnianie nie są już dostępne. Pobierz świeżą listę."
                    410 -> if (kind == PrivateReadKind.PHOTO) "Analiza zdjęć jest niedostępna. Dodaj posiłek ręcznie."
                        else "Strona rankingu wygasła lub jest już niedostępna. Pobierz listę od początku."
                    429, 503 -> {
                        val seconds = BootstrapHttpProtocol.retrySeconds(result.retryAfter, now())
                        val retryAt = Math.addExact(now(), Math.multiplyExact(seconds, 1000))
                        withApiSession(captured) {
                            ready()
                            val session = checkNotNull(sessionFor(binding()))
                            persist(copyRecord().put("session", JSONObject(session.toString()).put("apiRetryAt", retryAt)))
                        }
                        "Serwer jest zajęty. Ponów za co najmniej $seconds s. Dziennik działa offline."
                    }
                    else -> "Nie udało się odczytać danych serwerowych. Dziennik działa offline."
                }
                mutex.withLock {
                    if (profileOperation == id) {
                        owners.requireCurrent(lease); profileOperation = null
                        if (kind == PrivateReadKind.PHOTO) photoCapabilitiesState = PhotoCapabilitiesState.Failed(message)
                        if (kind == PrivateReadKind.MOTIVATION) motivationState = MotivationState.Failed(message)
                        if (kind == PrivateReadKind.CONSENTS) consentState = RankingConsentState.Failed(message)
                        if (kind == PrivateReadKind.NEMESIS) {
                            val retry = result.status !in setOf(400, 403, 404, 409, 410, 422)
                            if (!retry) clearNemesis()
                            nemesisState = NemesisState.Failed(message, retry)
                        }
                        if (kind == PrivateReadKind.RANKING) {
                            val retry = result.status !in setOf(400, 403, 404, 409, 410, 422)
                            if (!retry) clearRanking()
                            rankingState = RankingState.Failed(message, retry)
                        }
                        publish(message)
                    }
                }
                return
            }
        } catch (error: CancellationException) {
            withContext(NonCancellable) { finishPrivate(id, lease, kind) }; throw error
        } catch (_: Exception) { finishPrivate(id, lease, kind) }
    }
    private suspend fun finishPrivate(id: String, lease: OwnerLease, kind: PrivateReadKind) = mutex.withLock {
        if (profileOperation != id) return@withLock
        profileOperation = null
        serverProfile = null
        clearMotivation()
        val message = "Odczyt nie został potwierdzony. Możesz ponowić; dziennik zachowany."
        try {
            if (owners.currentLease() == lease) {
                if (kind == PrivateReadKind.PHOTO) photoCapabilitiesState = PhotoCapabilitiesState.Failed(message)
                if (kind == PrivateReadKind.MOTIVATION) motivationState = MotivationState.Failed(message)
                if (kind == PrivateReadKind.CONSENTS) consentState = RankingConsentState.Failed(message)
                if (kind == PrivateReadKind.RANKING) rankingState = RankingState.Failed(message, rankingRetryQuery != null)
                if (kind == PrivateReadKind.NEMESIS) nemesisState = NemesisState.Failed(message, nemesisRetryQuery != null)
                publish(message)
            }
            else publish()
        } catch (_: Exception) {
            mutable.value = mutable.value.copy(profileBusy = false, serverProfile = null, motivationBusy = false, motivation = MotivationState.NotRequested,
                rankingConsentBusy = false, rankingConsent = RankingConsentState.NotRequested, rankingBusy = false, ranking = RankingState.NotRequested,
                nemesisBusy = false, nemesis = NemesisState.NotRequested,
                message = "Odczyt nie został potwierdzony. Dziennik pozostaje lokalny.")
        }
    }

    suspend fun confirmRankingConsent(sourceId: String, enabled: Boolean) = writeRankingConsent(sourceId, enabled)
    suspend fun retryRankingConsent() = writeRankingConsent(null, null)
    private suspend fun writeRankingConsent(sourceId: String?, enabled: Boolean?) {
        val transport = rankingConsentGateway ?: return
        val id = UUID.randomUUID().toString()
        var lease: OwnerLease? = null
        val request = try { mutex.withLock {
            if (mealPushOperation != null || consentOperation != null || profileOperation != null || snapshotOperation != null || bootstrapOperation != null || operation != null || photoUploadOperation != null || nemesisMutationOperation != null || record.has("pending")) return
            val current = binding()
            lease = current.lease
            check(current.owner.kind == "account" && sessionFor(current) != null)
            val server = checkNotNull(db.bootstrapDao().binding(current.lease.storageScope))
            check(!server.requiresRecovery)
            val retryAt = checkNotNull(sessionFor(current)).optLong("apiRetryAt")
            if (retryAt > now()) { publish("Serwer jest zajęty. Ponów za co najmniej ${(retryAt - now() + 999) / 1000} s."); return }
            val previous = pendingConsent(current, server)
            val attempt = if (sourceId == null) checkNotNull(previous) else {
                check(previous == null)
                val source = (consentState as? RankingConsentState.Ready)?.source ?: error("Fresh source required")
                check(source.id == sourceId && consentFence == (current.lease to server.contextRevision))
                check(consentServerContext == (server.accountGeneration to server.syncEpoch))
                require(Math.subtractExact(now(), source.readAtMillis) in 0..300_000)
                val desired = checkNotNull(enabled)
                RankingConsentAttempt(UUID.randomUUID().toString(), current.lease.storageScope, current.lease.generation,
                    server.accountId, server.accountGeneration, server.syncEpoch, server.contextRevision, source.consents.revision,
                    desired, source.consents.automaticEnergyAdjustment, if (desired) source.ranking.consentEpoch else null)
            }
            // Persist the exact decision BEFORE any PUT. Retry never creates a different key or body.
            persist(copyRecord().put("rankingConsentAttempt", attempt.journal()))
            // AtomicFile may report a failed rename only in system logs. Verify the durable record before sending.
            withContext(Dispatchers.IO) {
                val durable = checkNotNull(vault.read().optJSONObject("rankingConsentAttempt"))
                require(StrictJson.canonical(durable) == StrictJson.canonical(attempt.journal()))
            }
            consentOperation = id
            serverProfile = null
            clearMotivation()
            clearRanking(); clearNemesis()
            publish()
            attempt
        } } catch (error: CancellationException) { withContext(NonCancellable) { finishConsent(id) }; throw error }
        catch (_: Exception) {
            mutex.withLock {
                if (consentOperation == id) consentOperation = null
                if (lease == null || owners.currentLease() == lease) {
                    consentState = RankingConsentState.Failed("Zapis wymaga aktualnego odczytu zgód i decyzji. Dziennik zachowany.")
                    publish()
                }
            }
            return
        }
        val capturedLease = checkNotNull(lease)
        try {
            val fresh = mutex.withLock {
                owners.requireCurrent(capturedLease)
                val state = AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime ?: 0) > now() + 30_000
            }
            if (!fresh) check(refreshFor(capturedLease))
            var ticket = apiSession(capturedLease)
            var refreshed = false
            while (true) {
                val captured = ticket
                suspend fun ready() {
                    check(consentOperation == id)
                    val server = bootstraps.requireReady(capturedLease, request.contextRevision)
                    require(server.accountId == request.accountId && server.accountGeneration == request.accountGeneration && server.syncEpoch == request.syncEpoch)
                    val pending = checkNotNull(pendingConsent(binding(), server))
                    require(StrictJson.canonical(pending.journal()) == StrictJson.canonical(request.journal()))
                }
                val result = transport.put(captured, request) { withApiSession(captured) { ready() } }
                if (result.status == 200) {
                    val response = request.parseReceipt(result.body)
                    require(result.etag == "\"${response.revision}\"")
                    withApiSession(captured) {
                        ready()
                        persist(copyRecord().also { it.remove("rankingConsentAttempt") })
                        consentOperation = null
                        clearMotivation()
                        consentState = RankingConsentState.Confirmed(response)
                        consentFence = capturedLease to request.contextRevision
                        consentServerContext = request.accountGeneration to request.syncEpoch
                        publish("Serwer potwierdził decyzję o udziale w rankingu. Odśwież, aby sprawdzić bieżący stan.")
                    }
                    return
                }
                val code = if (result.status in setOf(429, 503)) "" else BootstrapHttpProtocol.errorCode(result.body)
                withApiSession(captured) { ready() }
                if (result.status == 401 && code == "unauthorized" && !refreshed) {
                    refreshed = true
                    check(refreshFor(capturedLease))
                    ticket = apiSession(capturedLease)
                    continue
                }
                if (result.status in setOf(409, 400, 422)) {
                    withApiSession(captured) {
                        ready()
                        persist(copyRecord().also { it.remove("rankingConsentAttempt") })
                        consentOperation = null
                        clearMotivation()
                        consentState = RankingConsentState.Failed("Stan zgód się zmienił lub poprzedni wynik jest niedostępny. Pobierz aktualne zgody i podejmij nową decyzję.")
                        publish()
                    }
                    return
                }
                if (result.status in setOf(429, 503)) {
                    val seconds = BootstrapHttpProtocol.retrySeconds(result.retryAfter, now())
                    val retryAt = Math.addExact(now(), Math.multiplyExact(seconds, 1000))
                    withApiSession(captured) {
                        ready()
                        val session = checkNotNull(sessionFor(binding()))
                        persist(copyRecord().put("session", JSONObject(session.toString()).put("apiRetryAt", retryAt)))
                    }
                }
                finishConsent(id)
                return
            }
        } catch (error: CancellationException) {
            withContext(NonCancellable) { finishConsent(id) }; throw error
        } catch (_: Exception) { finishConsent(id) }
    }
    private suspend fun finishConsent(id: String) = mutex.withLock {
        if (consentOperation != id) return@withLock
        consentOperation = null
        clearMotivation()
        try { publish("Zapis nie został potwierdzony. Możesz ponowić tę samą decyzję; nie zmieniamy jej klucza ani treści.") }
        catch (_: Exception) { mutable.value = mutable.value.copy(rankingConsentBusy = false, rankingConsent = RankingConsentState.NotRequested,
            message = "Potwierdzenie jest niedostępne. Dziennik pozostaje zapisany.") }
    }

    suspend fun issueNemesisCode() = writeNemesis { _, _ -> NemesisCommand.issue() }
    suspend fun revokeNemesisCode() = writeNemesis { _, _ -> NemesisCommand.revoke() }
    suspend fun createNemesis(code: String, days: Int, zone: String, weight: Boolean, deficit: Boolean, acknowledged: Boolean) {
        if (!acknowledged) return
        writeNemesis { _, _ -> NemesisCommand.create(code, NemesisTerms(days, java.time.ZoneId.of(zone), weight, deficit)) }
    }
    suspend fun acceptNemesis(sourceId: String, acknowledged: Boolean, weightAcknowledged: Boolean, deficitAcknowledged: Boolean) {
        if (!acknowledged) return
        writeNemesis { current, server ->
            val source = requireNemesisDecision(sourceId, current, server)
            require(!source.challenge.terms.weight || weightAcknowledged)
            require(!source.challenge.terms.deficit || deficitAcknowledged)
            NemesisCommand.accept(source.challenge)
        }
    }
    suspend fun cancelNemesis(sourceId: String) = writeNemesis { current, server -> NemesisCommand.cancel(requireNemesisDecision(sourceId, current, server).challenge) }
    suspend fun retryNemesisMutation() = writeNemesis(null)
    private fun requireNemesisDecision(sourceId: String, current: SessionBinding, server: AccountBindingEntity): NemesisDecisionSource {
        val source = checkNotNull(nemesisDecisionSource)
        require(source.id == sourceId && nemesisFence == (current.lease to server.contextRevision) &&
            nemesisServerContext == Triple(server.accountId, server.accountGeneration, server.syncEpoch))
        require(Math.subtractExact(now(), source.readAtMillis) in 0..300_000)
        return source
    }
    private fun restoredNemesisAttempt(): NemesisAttempt? = try { record.optJSONObject("nemesisAttempt")?.let(NemesisAttempt::restore) } catch (_: Exception) { null }
    private fun currentNemesisAttempt(current: SessionBinding, server: AccountBindingEntity?): NemesisAttempt? = restoredNemesisAttempt()?.takeIf {
        sessionFor(current) != null && current.owner.kind == "account" && server != null && !server.requiresRecovery &&
            it.ownerScope == current.lease.storageScope && it.leaseGeneration == current.lease.generation &&
            it.accountId == server.accountId && it.accountGeneration == server.accountGeneration && it.epoch == server.syncEpoch && it.contextRevision == server.contextRevision
    }
    private suspend fun writeNemesis(make: ((SessionBinding, AccountBindingEntity) -> NemesisCommand)?) {
        val transport = nemesisWriteGateway ?: return
        val id = UUID.randomUUID().toString()
        var lease: OwnerLease? = null
        val request = try { mutex.withLock {
            if (mealPushOperation != null || photoUploadOperation != null || nemesisMutationOperation != null || consentOperation != null || profileOperation != null || snapshotOperation != null || bootstrapOperation != null || operation != null || record.has("pending")) return
            val current = binding(); lease = current.lease
            check(current.owner.kind == "account" && sessionFor(current) != null)
            val server = checkNotNull(db.bootstrapDao().binding(current.lease.storageScope)); check(!server.requiresRecovery)
            val retryAt = checkNotNull(sessionFor(current)).optLong("apiRetryAt")
            if (retryAt > now()) { publish("Serwer jest zajęty. Ponów za co najmniej ${(retryAt - now() + 999) / 1000} s."); return }
            val previous = currentNemesisAttempt(current, server)
            val attempt = if (make == null) checkNotNull(previous) else {
                check(!record.has("nemesisAttempt"))
                val command = make(current, server)
                check(!command.grantsSharing || motivationGateway != null)
                NemesisAttempt(UUID.randomUUID().toString(), current.lease.storageScope, current.lease.generation, server.accountId,
                    server.accountGeneration, server.syncEpoch, server.contextRevision, command)
            }
            persist(copyRecord().put("nemesisAttempt", attempt.journal()))
            withContext(Dispatchers.IO) {
                val durable = checkNotNull(vault.read().optJSONObject("nemesisAttempt"))
                require(StrictJson.canonical(durable) == StrictJson.canonical(attempt.journal()))
            }
            nemesisMutationOperation = id
            serverProfile = null; clearMotivation(); clearRanking(); clearNemesis()
            nemesisMutationFence = current.lease to server.contextRevision
            nemesisMutationContext = Triple(server.accountId, server.accountGeneration, server.syncEpoch)
            nemesisMutationState = NemesisMutationState.Sending
            publish(); attempt
        } } catch (error: CancellationException) { withContext(NonCancellable) { finishNemesisMutation(id) }; throw error }
        catch (_: Exception) {
            mutex.withLock {
                if (nemesisMutationOperation == id) nemesisMutationOperation = null
                if (lease == null || owners.currentLease() == lease) {
                    nemesisMutationState = NemesisMutationState.Failed("Decyzja wymaga aktualnego stanu i potwierdzenia. Dziennik zachowany.")
                    publish()
                }
            }
            return
        }
        val capturedLease = checkNotNull(lease)
        try {
            val fresh = mutex.withLock {
                owners.requireCurrent(capturedLease)
                val state = AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime ?: 0) > now() + 30_000
            }
            if (!fresh) check(refreshFor(capturedLease))
            var ticket = apiSession(capturedLease); var refreshed = false
            var preflight = request.command.grantsSharing
            while (true) {
                val captured = ticket
                suspend fun ready() {
                    check(nemesisMutationOperation == id)
                    val server = bootstraps.requireReady(capturedLease, request.contextRevision)
                    require(server.accountId == request.accountId && server.accountGeneration == request.accountGeneration && server.syncEpoch == request.epoch)
                    val pending = checkNotNull(currentNemesisAttempt(binding(), server))
                    require(StrictJson.canonical(pending.journal()) == StrictJson.canonical(request.journal()))
                }
                val result = if (preflight) checkNotNull(motivationGateway).get(captured) { withApiSession(captured) { ready() } }
                    else transport.send(captured, request) { withApiSession(captured) { ready() } }
                if (preflight && result.status == 200) {
                    val state = MotivationReadProtocol.parse(result.body)
                    withApiSession(captured) {
                        ready()
                        if (state.accountGeneration != request.accountGeneration || state.syncEpoch != request.epoch) {
                            val server = checkNotNull(db.bootstrapDao().binding(capturedLease.storageScope))
                            db.bootstrapDao().update(server.copy(requiresRecovery = true, contextRevision = Math.addExact(server.contextRevision, 1)))
                            persist(copyRecord().also { it.remove("nemesisAttempt") }); nemesisMutationOperation = null
                            clearNemesis(); publish("Stan konta się zmienił. Wymagane uzgodnienie; dawnej decyzji nie wysyłamy.")
                        } else preflight = false
                    }
                    if (nemesisMutationOperation != id) return
                    continue
                }
                if (!preflight && result.status == request.command.successStatus) {
                    val code = withContext(Dispatchers.Default) { request.command.receipt(result.body) }
                    withApiSession(captured) {
                        ready(); persist(copyRecord().also { it.remove("nemesisAttempt") }); nemesisMutationOperation = null
                        clearMotivation(); clearRanking(); clearNemesis()
                        nemesisMutationFence = capturedLease to request.contextRevision
                        nemesisMutationContext = Triple(request.accountId, request.accountGeneration, request.epoch)
                        nemesisMutationState = code?.let(NemesisMutationState::Issued) ?: NemesisMutationState.Confirmed(request.command.action)
                        publish("Serwer potwierdził operację. Aktualne udostępnianie sprawdź przez świeży odczyt.")
                    }
                    return
                }
                val reason = if (result.status in setOf(429,503)) "" else BootstrapHttpProtocol.errorCode(result.body)
                withApiSession(captured) { ready() }
                if (result.status == 401 && reason == "unauthorized" && !refreshed) {
                    refreshed = true; check(refreshFor(capturedLease)); ticket = apiSession(capturedLease); continue
                }
                if (result.status in setOf(400,403,404,409,410,422)) {
                    withApiSession(captured) {
                        ready(); persist(copyRecord().also { it.remove("nemesisAttempt") }); nemesisMutationOperation = null
                        clearNemesis()
                        nemesisMutationState = NemesisMutationState.Failed("Poprzednia decyzja nie może zostać ponowiona. Pobierz świeżą listę i sprawdź aktualny stan przed nową decyzją.")
                        publish()
                    }
                    return
                }
                if (result.status in setOf(429,503)) {
                    val seconds = BootstrapHttpProtocol.retrySeconds(result.retryAfter, now())
                    val retryAt = Math.addExact(now(), Math.multiplyExact(seconds,1000))
                    withApiSession(captured) {
                        ready(); val session = checkNotNull(sessionFor(binding()))
                        persist(copyRecord().put("session", JSONObject(session.toString()).put("apiRetryAt", retryAt)))
                    }
                }
                finishNemesisMutation(id); return
            }
        } catch (error: CancellationException) { withContext(NonCancellable) { finishNemesisMutation(id) }; throw error }
        catch (_: Exception) { finishNemesisMutation(id) }
    }
    private suspend fun finishNemesisMutation(id: String) = mutex.withLock {
        if (nemesisMutationOperation != id) return@withLock
        nemesisMutationOperation = null
        try { publish("Odpowiedź nie została potwierdzona. Ponów dokładnie tę samą decyzję; bez zmiany klucza, warunków lub celu.") }
        catch (_: Exception) { mutable.value = mutable.value.copy(nemesisMutationBusy = false, nemesisMutation = NemesisMutationState.Idle,
            message = "Potwierdzenie jest niedostępne. Dziennik zachowany.") }
    }


    private fun photoMatches(row:PhotoAnalysisRequestEntity,server:AccountBindingEntity)=
        row.ownerScope==server.ownerScope && row.accountId==server.accountId && row.accountGeneration==server.accountGeneration &&
            row.syncEpoch==server.syncEpoch && row.contextRevision==server.contextRevision
    private class PhotoCapture(val lease:OwnerLease,val server:AccountBindingEntity,val store:PhotoAnalysisStore,
        val capabilities:PhotoCapabilitiesRead?)
    private suspend fun beginPhotoUpload(id:String,consent:PhotoUploadConsent?,expectedLease:OwnerLease,
        read:Boolean=false,local:Boolean=false,cancel:Boolean=false,editing:Boolean=false,confirm:Boolean=false):PhotoCapture?=mutex.withLock {
        owners.requireCurrent(expectedLease)
        if(mealPushOperation!=null || photoAnalysisGateway==null || photoAnalysisStores==null || photoUploadOperation!=null ||
            profileOperation!=null || bootstrapOperation!=null || snapshotOperation!=null || consentOperation!=null ||
            nemesisMutationOperation!=null || operation!=null || record.has("pending")) return@withLock null
        val current=binding()
        val session=sessionFor(current)
        if(current.owner.kind!="account" || session==null) {publish("Zaloguj się, aby wysłać zdjęcie. Ręczny dziennik działa offline.");return@withLock null}
        val known=db.bootstrapDao().binding(current.lease.storageScope)
        if(known==null || known.requiresRecovery){publish("Połącz konto lub uzgodnij stan serwera przed wysyłką zdjęcia.");return@withLock null}
        val server=bootstraps.requireReady(current.lease,known.contextRevision)
        if(!local && session.optLong("apiRetryAt")>now()) {photoUploadMessage="Serwer jest zajęty. Poczekaj przed ponowieniem.";publish();return@withLock null}
        photoUploadOperation=id;photoUploadMessage=null
        photoReadMode=read;photoCancelMode=cancel;photoEditMode=editing;photoConfirmMode=confirm
        photoUploadFence=current.lease to server.contextRevision
        photoUploadContext=Triple(server.accountId,server.accountGeneration,server.syncEpoch)
        val store=photoAnalysisStores.invoke(current.lease)
        val caps=if(consent!=null) {
            val value=(photoCapabilitiesState as? PhotoCapabilitiesState.Ready)?.read
                ?: throw IllegalStateException("Capabilities required")
            require(photoCapabilitiesFence==(current.lease to server.contextRevision) &&
                photoCapabilitiesContext==Triple(server.accountId,server.accountGeneration,server.syncEpoch))
            require(value.available && value.provider==consent.provider && value.model==consent.model && value.noticeVersion==consent.noticeVersion)
            check(store.pending()==null)
            value
        } else {
            val row=checkNotNull(store.pending())
            check(photoMatches(row,server) && (row.receiptJson!=null)==(read || cancel || confirm) && row.blockedCode==null && (local || row.retryAtMillis<=now()))
            null
        }
        publish();PhotoCapture(current.lease,server,store,caps)
    }
    /** One explicit consent persists the input before the first POST; no startup/background replay. */
    suspend fun uploadPhoto(expectedLease:OwnerLease,photoId:String,consent:PhotoUploadConsent,accepted:Boolean) {
        if(!accepted) return
        val id=UUID.randomUUID().toString()
        try {
            val captured=beginPhotoUpload(id,consent,expectedLease)?:return
            val row=captured.store.prepare(photoId,checkNotNull(captured.capabilities),true)
            sendPhotoUpload(id,captured,row)
        } catch(error:CancellationException){withContext(NonCancellable){finishPhotoUpload(id)};throw error}
        catch(_:Exception){finishPhotoUpload(id)}
    }
    suspend fun retryPhotoUpload(expectedLease:OwnerLease) {
        val id=UUID.randomUUID().toString()
        try {
            val captured=beginPhotoUpload(id,null,expectedLease)?:return
            sendPhotoUpload(id,captured,checkNotNull(captured.store.pending()))
        } catch(error:CancellationException){withContext(NonCancellable){finishPhotoUpload(id)};throw error}
        catch(_:Exception){finishPhotoUpload(id)}
    }
    private suspend fun sendPhotoUpload(id:String,captured:PhotoCapture,row:PhotoAnalysisRequestEntity) {
        val fresh=mutex.withLock {
            owners.requireCurrent(captured.lease);check(photoUploadOperation==id)
            val state=AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
            (state.accessTokenExpirationTime?:0)>now()+30_000
        }
        if(!fresh) check(refreshFor(captured.lease))
        var ticket=apiSession(captured.lease);var refreshed=false
        // Private image IO and wire encoding are outside withApiSession/Room/mutex.
        val request=captured.store.request(row.operationId)
        suspend fun ready() {
            check(photoUploadOperation==id)
            val current=bootstraps.requireReady(captured.lease,captured.server.contextRevision)
            check(photoMatches(row,current))
            check(checkNotNull(captured.store.pending()).operationId==row.operationId)
            check(checkNotNull(sessionFor(binding())).optLong("apiRetryAt")<=now())
        }
        while(true) {
            val current=ticket
            withApiSession(current){ready();captured.store.markAttempted(row.operationId,now())}
            val answer=withTimeout(45_000) {
                checkNotNull(photoAnalysisGateway).send(current,request){withApiSession(current){ready()}}
            }
            if(answer.status==202) {
                val receipt=captured.store.prepareReceipt(row.operationId,answer.body,request)
                withApiSession(current) {
                    ready();captured.store.acceptPrepared(receipt)
                    photoUploadOperation=null;photoUploadMessage="Serwer przyjął zdjęcie do analizy. Posiłek nie został jeszcze zapisany."
                    publish()
                }
                return
            }
            val code=if(answer.status in setOf(429,503)) "" else BootstrapHttpProtocol.errorCode(answer.body)
            withApiSession(current){ready()}
            if(answer.status==401 && code=="unauthorized" && !refreshed) {
                refreshed=true;check(refreshFor(captured.lease));ticket=apiSession(captured.lease);continue
            }
            if(answer.status in setOf(429,503) || (answer.status==409 && code=="ai_operation_busy")) {
                val seconds=BootstrapHttpProtocol.retrySeconds(answer.retryAfter,now())
                val retryAt=Math.addExact(now(),Math.multiplyExact(seconds,1000))
                withApiSession(current) {
                    ready()
                    val session=checkNotNull(sessionFor(binding()))
                    val until=maxOf(retryAt,session.optLong("apiRetryAt"),checkNotNull(captured.store.pending()).retryAtMillis)
                    captured.store.defer(row.operationId,until)
                    persist(copyRecord().put("session",JSONObject(session.toString()).put("apiRetryAt",until)))
                    photoUploadOperation=null;photoUploadMessage="Serwer jest zajęty. Zlecenie zachowano; ponów po przerwie."
                    publish()
                }
                return
            }
            if(answer.status in setOf(400,403,404,409,410,413,415,422)) {
                withApiSession(current) {
                    ready();captured.store.block(row.operationId,"photo_request_rejected")
                    if(answer.status==409 && code in setOf("sync_epoch_changed","account_generation_changed","analysis_context_changed")) {
                        val mapping=checkNotNull(db.bootstrapDao().binding(captured.lease.storageScope))
                        db.bootstrapDao().update(mapping.copy(requiresRecovery=true,contextRevision=Math.addExact(mapping.contextRevision,1)))
                    }
                    photoUploadOperation=null;photoUploadMessage="Serwer odrzucił zlecenie. Zdjęcie zachowano; możesz dodać posiłek ręcznie."
                    publish()
                }
                return
            }
            finishPhotoUpload(id);return
        }
    }
    private suspend fun finishPhotoUpload(id:String)=mutex.withLock {
        if(photoUploadOperation!=id) return@withLock
        photoUploadOperation=null
        try {
            val lease=owners.currentLease()
            if(photoUploadFence?.first!=lease){clearPhotoUpload();publish();return@withLock}
            photoUploadMessage=if(db.photoAnalysisDao().get(lease.storageScope)==null)
                "Nie utworzono zlecenia. Sprawdź dostępność i potwierdź zgodę dla tego zdjęcia."
                else "Nie potwierdzono przyjęcia zdjęcia. Ponów zachowane zlecenie bez zmiany zdjęcia lub klucza."
            publish()
        } catch(_:Exception){clearPhotoUpload()}
    }

    /** Local restore only; entering the screen must never start HTTP or replay POST. */
    suspend fun loadPhotoAnalysis(expectedLease:OwnerLease) {
        val id=UUID.randomUUID().toString()
        try {
            val captured=beginPhotoUpload(id,null,expectedLease,read=true,local=true)?:return
            val row=checkNotNull(captured.store.pending())
            val saved=withContext(Dispatchers.Default){captured.store.stored(row.operationId)}
            val preview=withContext(Dispatchers.Default){if(saved.cancelled)null else saved.latest?.let(PhotoAnalysisPreview::from)}
            val cancellation=PhotoCancellationStatus.from(row.operationId,saved)
            val confirmation=PhotoConfirmationStatus.from(row.operationId,saved,captured.store.canReopenConfirmation(row.operationId,saved))
            val draftPreview=withContext(Dispatchers.Default){PhotoMealDraftPreview.from(row.operationId,saved)}
            mutex.withLock {
                db.withTransaction {
                    readyPhotoRead(id,captured,row)
                    check(captured.store.pending()!!.receiptJson==saved.serialized)
                    photoAnalysisPreview=preview;photoCancellationStatus=cancellation;photoConfirmationStatus=confirmation;photoMealDraft=draftPreview;photoCanEditProposal=saved.canEditProposal;photoPreviewSource=saved.serialized
                    photoUploadOperation=null;photoReadMode=false;publish()
                }
            }
        } catch(error:CancellationException){withContext(NonCancellable){finishPhotoRead(id)};throw error}
        catch(_:Exception){finishPhotoRead(id,"Nie udało się odczytać zapisanego wyniku. Dziennik jest zachowany.")}
    }

    /** Requires the caller's mutex/Room guard; no parsing, image access or network. */
    private suspend fun readyPhotoRead(id:String,captured:PhotoCapture,row:PhotoAnalysisRequestEntity) {
        check(photoUploadOperation==id && (photoReadMode || photoCancelMode || photoConfirmMode))
        val current=bootstraps.requireReady(captured.lease,captured.server.contextRevision)
        check(photoMatches(row,current) && sessionFor(binding())!=null)
        val actual=checkNotNull(captured.store.pending())
        check(actual.operationId==row.operationId && actual.receiptJson!=null && actual.blockedCode==null && photoMatches(actual,current))
    }

    /** Explicit foreground GET only. Each HTTP attempt (also401) consumes the same bounded budget. */
    suspend fun readPhotoAnalysis(expectedLease:OwnerLease) {
        val id=UUID.randomUUID().toString()
        try {
            val captured=beginPhotoUpload(id,null,expectedLease,read=true)?:return
            val row=checkNotNull(captured.store.pending())
            withTimeout(120_000) { pollPhotoAnalysis(id,captured,row) }
        } catch(error:CancellationException){withContext(NonCancellable){finishPhotoRead(id)};throw error}
        catch(_:Exception){finishPhotoRead(id)}
    }

    private suspend fun pollPhotoAnalysis(id:String,captured:PhotoCapture,row:PhotoAnalysisRequestEntity) {
        var budget=PhotoPollBudget.start(System.nanoTime())
        val fresh=mutex.withLock {
            readyPhotoRead(id,captured,row)
            val auth=AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
            (auth.accessTokenExpirationTime?:0)>now()+30_000
        }
        if(!fresh) check(refreshFor(captured.lease))
        var ticket=apiSession(captured.lease);var refreshed=false
        val saved=withContext(Dispatchers.Default){captured.store.stored(row.operationId)}
        val cached=withContext(Dispatchers.Default){if(saved.cancelled)null else saved.latest?.let(PhotoAnalysisPreview::from)}
        val cancellation=PhotoCancellationStatus.from(row.operationId,saved)
            val confirmation=PhotoConfirmationStatus.from(row.operationId,saved,captured.store.canReopenConfirmation(row.operationId,saved))
            val draftPreview=withContext(Dispatchers.Default){PhotoMealDraftPreview.from(row.operationId,saved)}
        withApiSession(ticket) {
            readyPhotoRead(id,captured,row)
            check(captured.store.pending()!!.receiptJson==saved.serialized)
            photoAnalysisPreview=cached;photoCancellationStatus=cancellation;photoConfirmationStatus=confirmation;photoMealDraft=draftPreview;photoCanEditProposal=saved.canEditProposal;photoPreviewSource=saved.serialized;publish()
        }
        val request=PhotoHttpRequest.Read(saved.receipt.analysisId)
        // A cached terminal state still permits this explicit GET to reconcile a later decision.
        // Only a valid response from this invocation supplies automatic polling's server deadline.
        var currentRead:PhotoAnalysisRead?=null
        while(true) {
            val current=ticket
            val retryAt=withApiSession(current) {
                readyPhotoRead(id,captured,row)
                maxOf(checkNotNull(sessionFor(binding())).optLong("apiRetryAt"),captured.store.pending()!!.retryAtMillis)
            }
            val instant=java.time.Instant.ofEpochMilli(now())
            val step=currentRead?.let {budget.reserve(it,instant,System.nanoTime(),retryAt)}
                ?:budget.reserveInitial(instant,System.nanoTime(),retryAt)
            when(step) {
                is PhotoPollStep.Wait->{delay(minOf(step.delayMillis,1000));continue}
                is PhotoPollStep.Stop->{finishPhotoRead(id,"Sprawdzanie zakończone. Zapisany stan zachowano; możesz sprawdzić ponownie.");return}
                is PhotoPollStep.Ready->{
                    budget=step.reserved
                    var sentSource:PhotoAnalysisRequestEntity?=null
                    val answer=withTimeout(step.timeoutMillis) {
                        checkNotNull(photoAnalysisGateway).send(current,request) {
                            withApiSession(current) {
                                readyPhotoRead(id,captured,row)
                                check(checkNotNull(sessionFor(binding())).optLong("apiRetryAt")<=now() && captured.store.pending()!!.retryAtMillis<=now())
                                sentSource=checkNotNull(captured.store.pending())
                            }
                        }
                    }
                    if(answer.status==200) {
                        val prepared=withContext(Dispatchers.Default){captured.store.prepareRead(row.operationId,answer.body,checkNotNull(sentSource))}
                        val snapshot=prepared.snapshot
                        val read=checkNotNull(snapshot.latest)
                        val preview=withContext(Dispatchers.Default){if(snapshot.cancelled)null else PhotoAnalysisPreview.from(read)}
                        val cancellation=PhotoCancellationStatus.from(row.operationId,snapshot)
            val confirmation=PhotoConfirmationStatus.from(row.operationId,snapshot,prepared.canReopenConfirmation)
                        val draftPreview=withContext(Dispatchers.Default){PhotoMealDraftPreview.from(row.operationId,snapshot)}
                        withApiSession(current) {
                            readyPhotoRead(id,captured,row);captured.store.acceptReadPrepared(prepared)
                            photoAnalysisPreview=preview;photoCancellationStatus=cancellation;photoConfirmationStatus=confirmation;photoMealDraft=draftPreview;photoCanEditProposal=snapshot.canEditProposal;photoPreviewSource=snapshot.serialized;publish()
                        }
                        currentRead=read
                        if(snapshot.cancelled || read.state in setOf("succeeded","failed") || read.decision!="pending") {
                            finishPhotoRead(id,if(snapshot.cancelled) "Anulowanie potwierdzone. Możesz zamknąć zlecenie i wybrać kolejne zdjęcie."
                                else if(read.state=="succeeded") "Wynik zapisany na telefonie. Sam odczyt nie dodaje posiłku."
                                else "Analiza zakończona bez propozycji. Możesz dodać posiłek ręcznie.")
                            return
                        }
                        continue
                    }
                    val code=if(answer.status in setOf(429,503)) "" else BootstrapHttpProtocol.errorCode(answer.body)
                    withApiSession(current){readyPhotoRead(id,captured,row)}
                    if(answer.status==401 && code=="unauthorized" && !refreshed) {
                        refreshed=true;check(refreshFor(captured.lease));ticket=apiSession(captured.lease);continue
                    }
                    if(answer.status in setOf(429,503)) {
                        val retry=Math.addExact(now(),Math.multiplyExact(BootstrapHttpProtocol.retrySeconds(answer.retryAfter,now()),1000))
                        withApiSession(current) {
                            readyPhotoRead(id,captured,row)
                            val session=checkNotNull(sessionFor(binding()))
                            val until=maxOf(retry,session.optLong("apiRetryAt"),captured.store.pending()!!.retryAtMillis)
                            captured.store.deferRead(row.operationId,until)
                            persist(copyRecord().put("session",JSONObject(session.toString()).put("apiRetryAt",until)))
                            photoUploadOperation=null;photoReadMode=false
                            photoUploadMessage="Serwer jest zajęty. Zapisany wynik zachowano; sprawdź ponownie po przerwie."
                            publish()
                        }
                        return
                    }
                    if(answer.status in setOf(403,404,410) || (answer.status==409 &&
                        code in setOf("sync_epoch_changed","account_generation_changed","analysis_context_changed"))) {
                        withApiSession(current) {
                            readyPhotoRead(id,captured,row);captured.store.blockRead(row.operationId)
                            if(answer.status==409) {
                                val mapping=checkNotNull(db.bootstrapDao().binding(captured.lease.storageScope))
                                db.bootstrapDao().update(mapping.copy(requiresRecovery=true,contextRevision=Math.addExact(mapping.contextRevision,1)))
                            }
                            photoAnalysisPreview=null;photoPreviewSource=null;photoUploadOperation=null;photoReadMode=false
                            photoUploadMessage="Wynik jest niedostępny lub wymaga uzgodnienia konta. Lokalny dziennik zachowano."
                            publish()
                        }
                        return
                    }
                    finishPhotoRead(id);return
                }
            }
        }
    }

    private suspend fun finishPhotoRead(id:String,message:String="Nie potwierdzono odczytu. Zapisany stan zachowano; możesz sprawdzić ponownie.")=mutex.withLock {
        if(photoUploadOperation!=id || !photoReadMode) return@withLock
        photoUploadOperation=null;photoReadMode=false;photoEditMode=false
        try {
            if(photoUploadFence?.first!=owners.currentLease()){clearPhotoUpload();publish();return@withLock}
            photoUploadMessage=message;publish()
        } catch(_:Exception){clearPhotoUpload()}
    }

    suspend fun startPhotoMealDraft(lease:OwnerLease,id:String,revision:Long,date:java.time.LocalDate) {
        val zone=java.time.ZoneId.systemDefault()
        val moment=date.atTime(java.time.Instant.ofEpochMilli(now()).atZone(zone).toLocalTime()).atZone(zone).toInstant()
        updatePhotoMealDraft(lease,id) {it.prepareMealDraft(id,revision,moment,zone)}
    }
    suspend fun replacePhotoMealDraftItem(lease:OwnerLease,id:String,revision:Long,item:String,input:PhotoDraftInput) =
        updatePhotoMealDraft(lease,id){it.prepareMealDraftEdit(id,revision){draft->draft.replace(item,input)}}
    suspend fun addPhotoMealDraftItem(lease:OwnerLease,id:String,revision:Long,input:PhotoDraftInput) =
        updatePhotoMealDraft(lease,id){it.prepareMealDraftEdit(id,revision){draft->draft.add(UUID.randomUUID().toString(),input)}}
    suspend fun removePhotoMealDraftItem(lease:OwnerLease,id:String,revision:Long,item:String) =
        updatePhotoMealDraft(lease,id){it.prepareMealDraftEdit(id,revision){draft->draft.remove(item)}}
    suspend fun renamePhotoMealDraft(lease:OwnerLease,id:String,revision:Long,title:String) =
        updatePhotoMealDraft(lease,id){it.prepareMealDraftEdit(id,revision){draft->draft.rename(title)}}
    suspend fun discardPhotoMealDraft(lease:OwnerLease,id:String,revision:Long) =
        updatePhotoMealDraft(lease,id){it.prepareMealDraftDiscard(id,revision)}

    /** Local correction commits serialize with all account operations, but never need a fresh access token. */
    private suspend fun updatePhotoMealDraft(expectedLease:OwnerLease,operationId:String,
        prepare:suspend(PhotoAnalysisStore)->PreparedPhotoMealDraft) {
        val id=UUID.randomUUID().toString()
        try {
            val captured=beginPhotoUpload(id,null,expectedLease,read=true,local=true,editing=true)?:return
            val row=checkNotNull(captured.store.pending());check(row.operationId==operationId)
            val prepared=withContext(Dispatchers.Default){prepare(captured.store)}
            val snapshot=prepared.snapshot
            val draft=withContext(Dispatchers.Default){PhotoMealDraftPreview.from(row.operationId,snapshot)}
            val preview=withContext(Dispatchers.Default){snapshot.latest?.let(PhotoAnalysisPreview::from)}
            val cancellation=PhotoCancellationStatus.from(row.operationId,snapshot)
            val confirmation=PhotoConfirmationStatus.from(row.operationId,snapshot)
            mutex.withLock {db.withTransaction {
                readyPhotoRead(id,captured,row);check(photoEditMode)
                captured.store.acceptMealDraftPrepared(prepared)
                photoMealDraft=draft;photoCanEditProposal=snapshot.canEditProposal
                photoAnalysisPreview=preview;photoCancellationStatus=cancellation;photoConfirmationStatus=confirmation;photoPreviewSource=snapshot.serialized
                photoUploadOperation=null;photoReadMode=false;photoEditMode=false
                photoUploadMessage=if(draft==null) "Poprawki odrzucone. Oryginalne rozpoznanie zachowano."
                    else "Poprawki zapisane na telefonie. Posiłek nie został jeszcze dodany do dziennika."
                publish()
            }}
        } catch(error:CancellationException){withContext(NonCancellable){finishPhotoRead(id,"Zapis poprawek przerwany. Odtwórz zapisany szkic.")};throw error}
        catch(_:Exception){finishPhotoRead(id,"Nie zapisano poprawek. Sprawdź nazwę, ilość i wartości lub odtwórz aktualny szkic.")}
    }

    /** Explicit local review after a persisted post-rejection GET; never sends a replacement decision. */
    suspend fun reopenPhotoConfirmation(expectedLease:OwnerLease,operationId:String,revision:Long,editRevision:Long) {
        val id=UUID.randomUUID().toString()
        try {
            val captured=beginPhotoUpload(id,null,expectedLease,read=true,local=true,editing=true)?:return
            val row=checkNotNull(captured.store.pending());check(row.operationId==operationId)
            val prepared=withContext(Dispatchers.Default){captured.store.prepareConfirmationReopen(operationId,revision,editRevision)}
            val snapshot=prepared.snapshot
            val draft=withContext(Dispatchers.Default){PhotoMealDraftPreview.from(operationId,snapshot)}
            val preview=withContext(Dispatchers.Default){snapshot.latest?.let(PhotoAnalysisPreview::from)}
            val cancellation=PhotoCancellationStatus.from(operationId,snapshot)
            val confirmation=PhotoConfirmationStatus.from(operationId,snapshot)
            mutex.withLock {db.withTransaction {
                readyPhotoRead(id,captured,row);check(photoEditMode)
                captured.store.acceptConfirmationReopenPrepared(prepared)
                photoMealDraft=draft;photoCanEditProposal=snapshot.canEditProposal
                photoAnalysisPreview=preview;photoCancellationStatus=cancellation;photoConfirmationStatus=confirmation
                photoPreviewSource=snapshot.serialized;photoUploadOperation=null;photoReadMode=false;photoEditMode=false
                photoUploadMessage="Możesz ponownie poprawić posiłek. Dodanie go do dziennika wymaga nowego zatwierdzenia.";publish()
            }}
        } catch(error:CancellationException){withContext(NonCancellable){finishPhotoRead(id,"Powrót do poprawek przerwany. Zapisane dane zachowano.")};throw error}
        catch(_:Exception){finishPhotoRead(id,"Nie odblokowano poprawek. Sprawdź bieżący wynik analizy przed nową decyzją.")}
    }

    /** Freeze the exact revision reviewed by the user before any token refresh or HTTP. */
    suspend fun confirmPhotoMeal(lease:OwnerLease,operationId:String,revision:Long,editRevision:Long) =
        changePhotoConfirmation(lease,operationId,revision to editRevision)

    /** Only explicit replay of the durable decision can retry a possibly accepted POST. */
    suspend fun retryPhotoConfirmation(lease:OwnerLease,operationId:String) =
        changePhotoConfirmation(lease,operationId,null)

    private suspend fun changePhotoConfirmation(expectedLease:OwnerLease,operationId:String,revisions:Pair<Long,Long>?) {
        val id=UUID.randomUUID().toString()
        try {
            val captured=beginPhotoUpload(id,null,expectedLease,confirm=true)?:return
            val row=checkNotNull(captured.store.pending());check(row.operationId==operationId)
            if(revisions!=null) {
                val prepared=withContext(Dispatchers.Default) {
                    captured.store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),revisions.first,revisions.second)
                }
                val status=PhotoConfirmationStatus.from(row.operationId,prepared.snapshot)
                mutex.withLock {db.withTransaction {
                    readyPhotoConfirmation(id,captured,row)
                    captured.store.acceptConfirmationPrepared(prepared)
                    photoConfirmationStatus=status;photoCancellationStatus=null;photoCanEditProposal=false
                    photoPreviewSource=prepared.snapshot.serialized;publish()
                }}
            } else {
                val initial=withContext(Dispatchers.Default){captured.store.stored(row.operationId)}
                check(PhotoConfirmationStatus.from(row.operationId,initial)?.canRetry==true)
            }
            val fresh=mutex.withLock {
                readyPhotoConfirmation(id,captured,row)
                val state=AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime?:0)>now()+30_000
            }
            if(!fresh)check(refreshFor(captured.lease))
            var ticket=apiSession(captured.lease);var refreshed=false
            val attempted=withContext(Dispatchers.Default){captured.store.prepareConfirmationAttempted(row.operationId,now())}
            val snapshot=attempted.snapshot
            val request=checkNotNull(snapshot.confirmation).request(row.syncEpoch)
            val status=PhotoConfirmationStatus.from(row.operationId,snapshot)
            withApiSession(ticket) {
                readyPhotoConfirmation(id,captured,row)
                captured.store.acceptConfirmationPrepared(attempted)
                photoConfirmationStatus=status;photoCancellationStatus=null;photoCanEditProposal=false
                photoPreviewSource=snapshot.serialized;publish()
            }
            suspend fun ready() {
                readyPhotoConfirmation(id,captured,row)
                val actual=checkNotNull(captured.store.pending())
                check(actual.receiptJson==snapshot.serialized && actual.retryAtMillis<=now())
                check(checkNotNull(sessionFor(binding())).optLong("apiRetryAt")<=now())
            }
            while(true) {
                val current=ticket
                val answer=withTimeout(45_000) {
                    checkNotNull(photoAnalysisGateway).send(current,request){withApiSession(current){ready()}}
                }
                if(answer.status==200) {
                    // Parsing/planning happens outside the guard; only the complete DB commit is fenced.
                    val prepared=withContext(Dispatchers.Default){captured.store.prepareConfirmationReceipt(row.operationId,answer.body,request)}
                    withApiSession(current) {
                        ready();captured.store.materializeConfirmationPrepared(prepared)
                        photoUploadOperation=null;photoConfirmMode=false
                        photoAnalysisPreview=null;photoCancellationStatus=null;photoConfirmationStatus=null
                        photoPreviewSource=null;photoMealDraft=null;photoCanEditProposal=false
                        photoUploadMessage="Posiłek dodany do dziennika. Synchronizacja wpisu oczekuje na potwierdzenie serwera."
                        publish()
                    }
                    // A cleanup failure never rolls back the diary, ledger or canonical outbox.
                    try {captured.store.cleanupReleasedInput(row.operationId)}catch(_:Exception){/* Retain orphan for later cleanup. */}
                    return
                }
                val code=if(answer.status in setOf(429,503)) "" else BootstrapHttpProtocol.errorCode(answer.body)
                withApiSession(current){ready()}
                if(answer.status==401 && code=="unauthorized" && !refreshed) {
                    refreshed=true;check(refreshFor(captured.lease));ticket=apiSession(captured.lease);continue
                }
                if(answer.status in setOf(429,503) || (answer.status==409 && code=="ai_operation_busy")) {
                    val retry=Math.addExact(now(),Math.multiplyExact(BootstrapHttpProtocol.retrySeconds(answer.retryAfter,now()),1000))
                    withApiSession(current) {
                        ready()
                        val session=checkNotNull(sessionFor(binding()))
                        val until=maxOf(retry,session.optLong("apiRetryAt"),captured.store.pending()!!.retryAtMillis)
                        captured.store.deferRead(row.operationId,until)
                        persist(copyRecord().put("session",JSONObject(session.toString()).put("apiRetryAt",until)))
                        photoUploadOperation=null;photoConfirmMode=false
                        photoUploadMessage="Serwer jest zajęty. Decyzja dodania posiłku jest zapisana; ponów po przerwie.";publish()
                    }
                    return
                }
                if(answer.status==409 && code in setOf("proposal_revision_conflict","photo_catalog_choice_changed",
                    "idempotency_key_reused","analysis_already_confirmed","photo_confirm_rejected")) {
                    val prepared=withContext(Dispatchers.Default){captured.store.prepareConfirmationRejection(row.operationId,code,request)}
                    val rejected=PhotoConfirmationStatus.from(row.operationId,prepared.snapshot)
                    withApiSession(current) {
                        ready();captured.store.acceptConfirmationPrepared(prepared)
                        photoConfirmationStatus=rejected;photoPreviewSource=prepared.snapshot.serialized
                        photoUploadOperation=null;photoConfirmMode=false
                        photoUploadMessage="Serwer odrzucił tę decyzję. Sprawdź stan analizy; poprawki i dziennik zachowano.";publish()
                    }
                    return
                }
                if(answer.status in setOf(403,404,410) || (answer.status==409 && code in
                    setOf("sync_epoch_changed","account_generation_changed","analysis_context_changed"))) {
                    withApiSession(current) {
                        ready();captured.store.blockRead(row.operationId)
                        if(answer.status==409) {
                            val mapping=checkNotNull(db.bootstrapDao().binding(captured.lease.storageScope))
                            db.bootstrapDao().update(mapping.copy(requiresRecovery=true,contextRevision=Math.addExact(mapping.contextRevision,1)))
                        }
                        photoUploadOperation=null;photoConfirmMode=false
                        photoUploadMessage="Nie można potwierdzić posiłku. Uzgodnij stan konta; dziennik i poprawki zachowano.";publish()
                    }
                    return
                }
                finishPhotoConfirmation(id);return
            }
        } catch(error:CancellationException){withContext(NonCancellable){finishPhotoConfirmation(id)};throw error}
        catch(_:Exception){finishPhotoConfirmation(id)}
    }

    private suspend fun readyPhotoConfirmation(id:String,captured:PhotoCapture,row:PhotoAnalysisRequestEntity) {
        check(photoConfirmMode);readyPhotoRead(id,captured,row)
    }
    private suspend fun finishPhotoConfirmation(id:String)=mutex.withLock {
        if(photoUploadOperation!=id || !photoConfirmMode)return@withLock
        photoUploadOperation=null;photoConfirmMode=false
        try {
            if(photoUploadFence?.first!=owners.currentLease()){clearPhotoUpload();publish();return@withLock}
            photoUploadMessage="Nie potwierdzono dodania posiłku. Odtwórz zapisany stan i ponów tę samą decyzję.";publish()
        } catch(_:Exception){clearPhotoUpload()}
    }

    /** Captured operation/revision are the exact decision shown in the confirmation dialog. */
    suspend fun cancelPhotoAnalysis(expectedLease:OwnerLease,operationId:String,revision:Long) =
        changePhotoCancellation(expectedLease,operationId,revision)

    /** Explicit replay of the durable decision, never an implicit new mutation key. */
    suspend fun retryPhotoCancellation(expectedLease:OwnerLease,operationId:String) =
        changePhotoCancellation(expectedLease,operationId,null)

    private suspend fun changePhotoCancellation(expectedLease:OwnerLease,operationId:String,revision:Long?) {
        val id=UUID.randomUUID().toString()
        try {
            val captured=beginPhotoUpload(id,null,expectedLease,cancel=true)?:return
            val row=checkNotNull(captured.store.pending());check(row.operationId==operationId)
            val initial=withContext(Dispatchers.Default){captured.store.stored(row.operationId)}
            if(revision!=null) {
                // Persist approval before token refresh or any attempt at network IO.
                val prepared=withContext(Dispatchers.Default){captured.store.prepareCancellation(row.operationId,UUID.randomUUID().toString(),revision)}
                val status=PhotoCancellationStatus.from(row.operationId,prepared.snapshot)
                mutex.withLock {db.withTransaction {
                    readyPhotoCancellation(id,captured,row)
                    captured.store.acceptCancellationPrepared(prepared)
                    photoCancellationStatus=status;photoCanEditProposal=false;photoPreviewSource=prepared.snapshot.serialized;publish()
                }}
            } else check(!initial.cancelled && initial.latest?.decision=="pending" && initial.cancellation?.pending==true)
            val fresh=mutex.withLock {
                readyPhotoCancellation(id,captured,row)
                val state=AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime?:0)>now()+30_000
            }
            if(!fresh) check(refreshFor(captured.lease))
            var ticket=apiSession(captured.lease);var refreshed=false
            val attempted=withContext(Dispatchers.Default){captured.store.prepareCancellationAttempted(row.operationId,now())}
            val snapshot=attempted.snapshot
            val request=checkNotNull(snapshot.cancellation).request(row.syncEpoch,snapshot.receipt.analysisId)
            val status=PhotoCancellationStatus.from(row.operationId,snapshot)
            val preview=withContext(Dispatchers.Default){snapshot.latest?.let(PhotoAnalysisPreview::from)}
            withApiSession(ticket) {
                readyPhotoCancellation(id,captured,row)
                captured.store.acceptCancellationPrepared(attempted)
                photoCancellationStatus=status;photoCanEditProposal=false;photoAnalysisPreview=preview;photoPreviewSource=snapshot.serialized;publish()
            }
            suspend fun ready() {
                readyPhotoCancellation(id,captured,row)
                val actual=checkNotNull(captured.store.pending())
                check(actual.receiptJson==snapshot.serialized && actual.retryAtMillis<=now())
                check(checkNotNull(sessionFor(binding())).optLong("apiRetryAt")<=now())
            }
            while(true) {
                val current=ticket
                val answer=withTimeout(45_000) {
                    checkNotNull(photoAnalysisGateway).send(current,request){withApiSession(current){ready()}}
                }
                if(answer.status==200) {
                    val prepared=withContext(Dispatchers.Default){captured.store.prepareCancellationReceipt(row.operationId,answer.body,request)}
                    val accepted=PhotoCancellationStatus.from(row.operationId,prepared.snapshot)
                    withApiSession(current) {
                        ready();captured.store.acceptCancellationPrepared(prepared)
                        photoCancellationStatus=accepted;photoCanEditProposal=false;photoAnalysisPreview=null;photoPreviewSource=prepared.snapshot.serialized
                        photoUploadOperation=null;photoCancelMode=false
                        photoUploadMessage="Anulowanie potwierdzone. Zamknij zlecenie, aby wybrać kolejne zdjęcie."
                        publish()
                    }
                    return
                }
                val code=if(answer.status in setOf(429,503)) "" else BootstrapHttpProtocol.errorCode(answer.body)
                withApiSession(current){ready()}
                if(answer.status==401 && code=="unauthorized" && !refreshed) {
                    refreshed=true;check(refreshFor(captured.lease));ticket=apiSession(captured.lease);continue
                }
                if(answer.status in setOf(429,503)) {
                    val retry=Math.addExact(now(),Math.multiplyExact(BootstrapHttpProtocol.retrySeconds(answer.retryAfter,now()),1000))
                    withApiSession(current) {
                        ready()
                        val session=checkNotNull(sessionFor(binding()))
                        val until=maxOf(retry,session.optLong("apiRetryAt"),captured.store.pending()!!.retryAtMillis)
                        captured.store.deferRead(row.operationId,until)
                        persist(copyRecord().put("session",JSONObject(session.toString()).put("apiRetryAt",until)))
                        photoUploadOperation=null;photoCancelMode=false
                        photoUploadMessage="Serwer jest zajęty. Decyzja anulowania jest zapisana; ponów po przerwie."
                        publish()
                    }
                    return
                }
                if(answer.status==409 && code in setOf("proposal_revision_conflict","idempotency_key_reused","analysis_already_confirmed","photo_cancel_rejected")) {
                    val prepared=withContext(Dispatchers.Default){captured.store.prepareCancellationRejection(row.operationId,code,request)}
                    val rejected=PhotoCancellationStatus.from(row.operationId,prepared.snapshot)
                    withApiSession(current) {
                        ready();captured.store.acceptCancellationPrepared(prepared)
                        photoCancellationStatus=rejected;photoPreviewSource=prepared.snapshot.serialized
                        photoUploadOperation=null;photoCancelMode=false
                        photoUploadMessage="Stan analizy zmienił się. Sprawdź wynik przed kolejną decyzją."
                        publish()
                    }
                    return
                }
                if(answer.status in setOf(403,404,410) || (answer.status==409 && code in
                    setOf("sync_epoch_changed","account_generation_changed","analysis_context_changed"))) {
                    withApiSession(current) {
                        ready();captured.store.blockRead(row.operationId)
                        if(answer.status==409) {
                            val mapping=checkNotNull(db.bootstrapDao().binding(captured.lease.storageScope))
                            db.bootstrapDao().update(mapping.copy(requiresRecovery=true,contextRevision=Math.addExact(mapping.contextRevision,1)))
                        }
                        photoAnalysisPreview=null;photoCancellationStatus=null;photoConfirmationStatus=null;photoPreviewSource=null
                        photoUploadOperation=null;photoCancelMode=false
                        photoUploadMessage="Nie można potwierdzić anulowania. Uzgodnij stan konta; dziennik zachowano."
                        publish()
                    }
                    return
                }
                finishPhotoCancellation(id);return
            }
        } catch(error:CancellationException){withContext(NonCancellable){finishPhotoCancellation(id)};throw error}
        catch(_:Exception){finishPhotoCancellation(id)}
    }

    private suspend fun readyPhotoCancellation(id:String,captured:PhotoCapture,row:PhotoAnalysisRequestEntity) {
        check(photoCancelMode)
        readyPhotoRead(id,captured,row)
    }
    private suspend fun finishPhotoCancellation(id:String)=mutex.withLock {
        if(photoUploadOperation!=id || !photoCancelMode)return@withLock
        photoUploadOperation=null;photoCancelMode=false
        try {
            if(photoUploadFence?.first!=owners.currentLease()){clearPhotoUpload();publish();return@withLock}
            photoUploadMessage="Anulowanie nie zostało potwierdzone. Sprawdź wynik lub ponów zapisaną decyzję."
            publish()
        } catch(_:Exception){clearPhotoUpload()}
    }

    /** Local explicit release only after server proof; no HTTP, no deletion of the source photo. */
    suspend fun releaseCancelledPhoto(expectedLease:OwnerLease,operationId:String) {
        val id=UUID.randomUUID().toString()
        try {
            val captured=beginPhotoUpload(id,null,expectedLease,local=true,cancel=true)?:return
            val row=checkNotNull(captured.store.pending());check(row.operationId==operationId)
            val prepared=withContext(Dispatchers.Default){captured.store.prepareCancelledRelease(row.operationId)}
            mutex.withLock {db.withTransaction {
                readyPhotoCancellation(id,captured,row);captured.store.releaseCancelledPrepared(prepared)
                photoUploadOperation=null;photoCancelMode=false;photoAnalysisPreview=null;photoCancellationStatus=null;photoConfirmationStatus=null;photoPreviewSource=null;photoMealDraft=null;photoCanEditProposal=false
                photoUploadMessage="Anulowane zlecenie zamknięte. Zdjęcie źródłowe i dziennik zachowano.";publish()
            }}
            // Failed cleanup leaves an unreferenced private file; it cannot undo the durable release.
            try {captured.store.cleanupReleasedInput(row.operationId)}catch(_:Exception){/* Later orphan retention. */}
        } catch(error:CancellationException){withContext(NonCancellable){finishPhotoCancellation(id)};throw error}
        catch(_:Exception){finishPhotoCancellation(id)}
    }

    /** Invalidates subsequent requests and any held response; never cancels the server analysis. */
    suspend fun stopPhotoAnalysis(expectedLease:OwnerLease,clearPreview:Boolean=false)=mutex.withLock {
        try {
            owners.requireCurrent(expectedLease)
            if(photoUploadFence?.first!=expectedLease) return@withLock
            if(photoReadMode || (clearPreview && (photoCancelMode || photoConfirmMode))){photoUploadOperation=null;photoReadMode=false;photoCancelMode=false;photoConfirmMode=false;photoEditMode=false;photoUploadMessage="Sprawdzanie zatrzymane. Zapisany stan zachowano."}
            if(clearPreview){photoAnalysisPreview=null;photoCancellationStatus=null;photoConfirmationStatus=null;photoPreviewSource=null;photoMealDraft=null;photoCanEditProposal=false;photoUploadMessage=null}
            publish()
        } catch(error:CancellationException){throw error}
        catch(_:Exception){/* A stale UI callback must not clear a newer owner's preview. */}
    }
    /** Explicit local discard only if no network attempt could have happened; never deletes a journal entry. */
    suspend fun discardUnsentPhotoUpload(expectedLease:OwnerLease) {
        var lease:OwnerLease?=null
        try {
            val saved=mutex.withLock {
                owners.requireCurrent(expectedLease)
                if(photoUploadOperation!=null) return
                val current=binding();if(current.owner.kind!="account") return
                lease=current.lease
                val store=photoAnalysisStores?.invoke(current.lease)?:return
                val row=store.pending()?:return
                check(!row.attempted)
                store to row.operationId
            }
            saved.first.dropNeverAttempted(saved.second)
            mutex.withLock {owners.requireCurrent(checkNotNull(lease));photoUploadMessage="Niewysłane zlecenie usunięte. Zdjęcie źródłowe zachowane.";publish()}
        } catch(error:CancellationException){throw error}
        catch(_:Exception){/* Keep an attempted/changed-owner operation intact. */}
    }

    /** Offline comparison uses the active account lease, independently of token expiry. */
    private suspend fun reloadConflictList(lease:OwnerLease,message:String?=null,offset:Int=0) {
        owners.requireCurrent(lease)
        val server=checkNotNull(db.bootstrapDao().binding(lease.storageScope))
        check(!server.requiresRecovery)
        val rows=checkNotNull(conflictStore).candidates(lease,offset)
        val entries=rows.take(20).map { row->
            val key=UUID.randomUUID().toString()
            conflictKeys[key]=row.operationId
            val date=when(row.entityType) {
                "meal"->db.dao().meal(row.entityId,lease.storageScope)?.meal?.localDate
                "weight"->db.dao().weight(row.entityId,lease.storageScope)?.localDate
                else->null
            }
            ConflictListEntry(key,(if(row.entityType=="weight")"Pomiar wagi" else "Posiłek")+(date?.let {" · $it"}?:""))
        }
        owners.requireCurrent(lease)
        check(db.bootstrapDao().binding(lease.storageScope)==server)
        conflictFence=lease to server
        conflictState=ConflictListView(entries,rows.size>20,loaded=true,message=message,page=offset/20)
    }

    suspend fun loadConflicts(lease:OwnerLease)=mutex.withLock {
        if(conflictStore==null || mutable.value.binding?.lease!=lease)return@withLock
        conflictBusy=true;conflictKeys.clear();conflictTicket=null
        try {
            publish()
            reloadConflictList(lease)
        } catch(error:CancellationException){throw error}
        catch(_:Exception){conflictState=ConflictListView(message="Nie udało się odczytać wpisów. Sprawdź połączenie konta; dziennik pozostaje zachowany.")}
        finally {conflictBusy=false;publish()}
    }

    suspend fun moveConflicts(lease:OwnerLease,direction:Int)=mutex.withLock {
        if(conflictStore==null || mutable.value.binding?.lease!=lease || direction !in setOf(-1,1))return@withLock
        if(direction==1 && !conflictState.hasMore || direction==-1 && conflictState.page==0)return@withLock
        val offset=Math.multiplyExact(Math.addExact(conflictState.page,direction),20)
        conflictBusy=true;conflictKeys.clear();conflictTicket=null
        try {publish();reloadConflictList(lease,offset=offset)}
        catch(error:CancellationException){throw error}
        catch(_:Exception){conflictState=ConflictListView(message="Nie udało się odczytać kolejnej strony. Odśwież listę.")}
        finally {conflictBusy=false;publish()}
    }

    suspend fun openConflict(lease:OwnerLease,key:String)=mutex.withLock {
        if(conflictStore==null || mutable.value.binding?.lease!=lease)return@withLock
        val operationId=conflictKeys[key]?:return@withLock
        conflictBusy=true;conflictTicket=null
        try {
            publish()
            val ticket=conflictStore.open(lease,operationId)
            owners.requireCurrent(lease)
            check(db.bootstrapDao().binding(lease.storageScope)==conflictFence?.second)
            val previewKey=UUID.randomUUID().toString()
            conflictTicket=previewKey to ticket
            conflictState=conflictState.copy(preview=conflictPreview(previewKey,ticket),message=null)
        } catch(error:CancellationException){throw error}
        catch(_:Exception){conflictState=conflictState.copy(preview=null,message="Nie można jeszcze porównać tego wpisu. Pobierz świeżą kopię danych serwera i spróbuj ponownie.")}
        finally {conflictBusy=false;publish()}
    }

    suspend fun closeConflict(lease:OwnerLease)=mutex.withLock {
        if(mutable.value.binding?.lease!=lease)return@withLock
        conflictTicket=null;conflictState=conflictState.copy(preview=null);publish()
    }

    suspend fun resolveConflict(lease:OwnerLease,key:String,choice:ConflictChoice)=mutex.withLock {
        if(conflictStore==null || mutable.value.binding?.lease!=lease)return@withLock
        val held=conflictTicket?.takeIf {it.first==key}?.second?:return@withLock
        conflictBusy=true
        try {
            publish()
            val queuedOperation=conflictStore.choose(held,choice)
            conflictTicket=null;conflictKeys.clear()
            val message=when {
                choice==ConflictChoice.SERVER->"Przyjęto wersję serwera. Porównane wersje zachowano w historii decyzji."
                queuedOperation!=null->"Wybór zapisany. Wynik trafi do kolejnej synchronizacji."
                else->"Potwierdzono usunięcie. Porównane wersje zachowano w historii decyzji."
            }
            reloadConflictList(lease,message)
        } catch(error:CancellationException){throw error}
        catch(_:ConflictChangedException){
            conflictTicket=null;conflictState=conflictState.copy(preview=null,message="Wpis zmienił się podczas porównywania. Otwórz aktualne wersje i potwierdź wybór ponownie.")
        }
        catch(_:Exception){
            conflictTicket=null;conflictState=conflictState.copy(preview=null,message="Nie udało się zakończyć obsługi widoku. Odśwież listę, aby sprawdzić zapisany stan.")
        }
        finally {conflictBusy=false;publish()}
    }

    /** Explicit canonical Meal push. Legacy rows remain local and are reported separately. */
    suspend fun synchronizeMeals(expectedLease:OwnerLease) {
        pushFor(expectedLease, null, followWithPull = true)
    }
    /** The worker orchestrator owns its final PULL; manual sync keeps its existing follow-up. */
    private suspend fun pushFor(expectedLease:OwnerLease,expectedContext:AccountBindingEntity?,
        followWithPull:Boolean):SyncCommandOutcome {
        val transport=mealPushGateway?:return SyncCommandOutcome.NotConfigured
        val store=mealPushStore?:return SyncCommandOutcome.NotConfigured
        val protocol=mealPushProtocol?:return SyncCommandOutcome.NotConfigured
        if(snapshotGateway==null || snapshots==null)return SyncCommandOutcome.NotConfigured
        val id=UUID.randomUUID().toString()
        val server=try {mutex.withLock {
            owners.requireCurrent(expectedLease)
            if(mealPushOperation!=null || operation!=null || bootstrapOperation!=null || snapshotOperation!=null ||
                profileOperation!=null || consentOperation!=null || nemesisMutationOperation!=null || photoUploadOperation!=null || record.has("pending"))return SyncCommandOutcome.Busy
            val current=binding();val session=sessionFor(current)
            if(current.lease!=expectedLease)throw StaleOwnerException()
            if(current.owner.kind!="account" || session==null){publish("Zaloguj się, aby wysłać dziennik. Dane lokalne zachowane.");return SyncCommandOutcome.LoginRequired}
            val known=db.bootstrapDao().binding(expectedLease.storageScope)
            if(expectedContext!=null && known!=expectedContext)return SyncCommandOutcome.StaleContext
            if(known==null || known.requiresRecovery){publish("Najpierw połącz konto lub uzgodnij stan serwera. Kolejka zachowana.");return SyncCommandOutcome.ReconciliationRequired("account_context_not_ready")}
            val pushStatus=store.status(expectedLease)
            val retryAt=maxOf(session.optLong("apiRetryAt"),pushStatus.retryAtMillis)
            if(retryAt>now()){publish("Serwer jest zajęty. Poczekaj do zakończenia zapisanej przerwy.");return SyncCommandOutcome.RetryAt(retryAt)}
            if(!pushStatus.ready){publish("Najpierw pobierz pełną kopię danych serwera. Kolejka zachowana.");return SyncCommandOutcome.ReconciliationRequired("snapshot_required")}
            mealPushOperation=id;mealPushFence=expectedLease to known;mealPushMessage=null
            publish();known
        }}catch(error:CancellationException){throw error}
        catch(_:StaleOwnerException){return SyncCommandOutcome.StaleContext}
        catch(_:SyncContextChangedException){return SyncCommandOutcome.StaleContext}
        catch(_:Exception){return SyncCommandOutcome.TransientFailure}
        val fence=SyncContextFence(expectedLease,server)
        var acknowledged=0;var refused=0
        try {
            var refreshed=false
            val fresh=mutex.withLock {
                checkMealPush(id,expectedLease,server)
                val state=AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime?:0)>now()+30_000
            }
            if(!fresh){check(refreshFor(expectedLease,fence));refreshed=true}
            var ticket=apiSession(fence)
            repeat(10) {
                withApiSession(ticket){checkMealPush(id,expectedLease,server)}
                // Includes serialization and schema checks; never execute under the session guard.
                val request=store.prepare(expectedLease)
                if(request==null){
                    finishMealPush(id,expectedLease,server,mealPushSummary(acknowledged,refused))
                    if(followWithPull && acknowledged+refused>0)downloadSnapshot(expectedLease,server)
                    return completeSyncCommand(fence,SyncCommandOutcome.Pushed(acknowledged,refused,more=false))
                }
                while(true) {
                    val captured=ticket
                    suspend fun ready(){checkMealPush(id,expectedLease,server);store.requireCurrent(request)}
                    val result=transport.post(captured,request.batch){withApiSession(captured){ready();store.markAttempted(request,now())}}
                    if(result.status==200){
                        val prepared=store.prepareAck(request,result.status,result.body)
                        withApiSession(captured){ready();val ack=store.applyAck(prepared)
                            acknowledged+=ack.acknowledged;refused+=ack.refused}
                        break
                    }
                    val code=if(result.status in setOf(429,503))"" else withContext(Dispatchers.Default){protocol.errorCode(result.body)}
                    withApiSession(captured){ready()}
                    if(result.status==401 && code=="unauthorized" && !refreshed){
                        refreshed=true;check(refreshFor(expectedLease,fence));ticket=apiSession(fence)
                        withApiSession(ticket){ready()};continue
                    }
                    if(result.status in setOf(429,503)) {
                        val seconds=BootstrapHttpProtocol.retrySeconds(result.retryAfter,now())
                        val retryAt=Math.addExact(now(),Math.multiplyExact(seconds,1000))
                        // Commit the batch deadline before the separate credential-vault write.
                        // A vault failure or logout cannot roll it back or shorten it.
                        withApiSession(captured){ready();store.defer(request,retryAt)}
                        withApiSession(captured){
                            checkMealPush(id,expectedLease,server)
                            val session=checkNotNull(sessionFor(binding()))
                            persist(copyRecord().put("session",JSONObject(session.toString()).put("apiRetryAt",retryAt)))
                            mealPushOperation=null;mealPushMessage="Serwer jest zajęty. Ponów za co najmniej $seconds s; zapisana partia zachowana."
                            publish()
                        }
                        return SyncCommandOutcome.RetryAt(retryAt)
                    }
                    var outcome:SyncCommandOutcome=SyncCommandOutcome.TransientFailure
                    withApiSession(captured){
                        ready()
                        val message=when {
                            result.status==403 && code=="account_deleting"->{
                                store.requireReconciliation(request,deleting=true)
                                outcome=SyncCommandOutcome.ReconciliationRequired(code)
                                "Konto jest usuwane. Wysyłanie zablokowane; dane i zapisana partia zachowane."
                            }
                            (result.status in setOf(403,409,410,422,413) && code in setOf("sync_epoch_changed",
                                "account_generation_changed","sync_reconciliation_required","sync_cursor_expired",
                                "account_bootstrap_required","invalid_sync_token","invalid_request","request_too_large"))->{
                                store.requireReconciliation(request)
                                outcome=SyncCommandOutcome.ReconciliationRequired(code)
                                "Wymagane uzgodnienie danych. Sprawdź połączenie i pobierz pełną kopię serwera; pierwotna partia zachowana."
                            }
                            result.status==401->{outcome=SyncCommandOutcome.LoginRequired;"Sesja wymaga ponownego logowania. Zapisana partia i dziennik zachowane."}
                            else->"Wysyłka nie została potwierdzona. Ponów zapisaną partię; dziennik zachowany."
                        }
                        mealPushOperation=null
                        mealPushFence=expectedLease to checkNotNull(db.bootstrapDao().binding(expectedLease.storageScope))
                        mealPushMessage=message;publish()
                    }
                    return outcome
                }
            }
            finishMealPush(id,expectedLease,server,mealPushSummary(acknowledged,refused)+" Pozostałe wpisy wyślesz kolejną próbą.")
            if(followWithPull)downloadSnapshot(expectedLease,server)
            return completeSyncCommand(fence,SyncCommandOutcome.Pushed(acknowledged,refused,more=true))
        }catch(error:CancellationException){withContext(NonCancellable){finishMealPush(id,expectedLease,server)};throw error}
        catch(_:StaleOwnerException){finishMealPush(id,expectedLease,server);return SyncCommandOutcome.StaleContext}
        catch(_:SyncContextChangedException){finishMealPush(id,expectedLease,server);return SyncCommandOutcome.StaleContext}
        catch(_:Exception){
            val current=mutex.withLock {
                try {requireSyncContext(fence);true}
                catch(error:CancellationException){throw error}
                catch(_:Exception){false}
            }
            finishMealPush(id,expectedLease,server)
            return if(current)SyncCommandOutcome.TransientFailure else SyncCommandOutcome.StaleContext
        }
    }
    /** DB-only check, called under the mutex (and, for network/apply, its Room transaction). */
    private suspend fun checkMealPush(id:String,lease:OwnerLease,server:AccountBindingEntity) {
        check(mealPushOperation==id && mealPushFence==(lease to server))
        owners.requireCurrent(lease)
        check(db.bootstrapDao().binding(lease.storageScope)==server && !server.requiresRecovery)
        check(!record.has("pending") && operation==null)
        check(checkNotNull(sessionFor(binding())).optLong("apiRetryAt")<=now())
    }
    private fun mealPushSummary(acknowledged:Int,refused:Int)=if(acknowledged+refused==0)
        "Brak gotowych wpisów do wysłania. Starsze wpisy i pozostałe typy danych pozostają w kolejce."
        else "Serwer potwierdził: $acknowledged. Wymagają uzgodnienia: $refused. Kopia serwera jest odświeżana osobno."
    private suspend fun finishMealPush(id:String,lease:OwnerLease,expectedContext:AccountBindingEntity,message:String=
        "Odpowiedź nie została potwierdzona. Ponów tę samą zapisaną partię; dziennik zachowany.")=mutex.withLock {
        if(mealPushOperation!=id)return@withLock
        mealPushOperation=null
        try {
            if(owners.currentLease()!=lease || db.bootstrapDao().binding(lease.storageScope)!=expectedContext){clearMealPush();publish();return@withLock}
            mealPushMessage=message;publish()
        }catch(_:Exception){clearMealPush()}
    }


    /** Full server archive. The local diary remains editable, and no queue entry is acknowledged. */
    /** Reuse a completed local archive after a restart, without HTTP or a fresh access token. */
    suspend fun applyDiaryCopy(lease:OwnerLease) {
        val store=diaryStore?:return
        val id=UUID.randomUUID().toString()
        mutex.withLock {
            if(mutable.value.binding?.lease!=lease || snapshotOperation!=null || mealPushOperation!=null ||
                bootstrapOperation!=null || profileOperation!=null || consentOperation!=null || operation!=null ||
                photoUploadOperation!=null || nemesisMutationOperation!=null || conflictBusy || record.has("pending"))return
            owners.requireCurrent(lease)
            snapshotOperation=id;diaryApplying=true;publish()
        }
        try {
            val result=store.apply(lease)
            finishSnapshot(id,lease,"Dziennik uzupełniony z kopii. Uwzględniono: ${result.included}; lokalne zmiany zachowane do uzgodnienia: ${result.held}.")
        } catch(error:CancellationException) {
            withContext(NonCancellable){finishSnapshot(id,lease)};throw error
        } catch(_:Exception) {
            finishSnapshot(id,lease,"Nie udało się uzupełnić dziennika z tej kopii. Dane i kolejka zachowane; pobierz świeżą pełną kopię.")
        }
    }

    suspend fun downloadSnapshot(expectedLease:OwnerLease?=null,expectedContext:AccountBindingEntity?=null) {
        pullFor(expectedLease, expectedContext, allowRecovery = true)
    }
    private suspend fun pullFor(expectedLease:OwnerLease?,expectedContext:AccountBindingEntity?,
        allowRecovery:Boolean):SyncCommandOutcome {
        val transport = snapshotGateway ?: return SyncCommandOutcome.NotConfigured
        val store = snapshots ?: return SyncCommandOutcome.NotConfigured
        val protocol = snapshotProtocol ?: return SyncCommandOutcome.NotConfigured
        if (!allowRecovery && diaryStore == null) return SyncCommandOutcome.NotConfigured
        val id = UUID.randomUUID().toString()
        val fence = try { mutex.withLock {
            expectedLease?.let { owners.requireCurrent(it) }
            if (mealPushOperation != null || snapshotOperation != null || profileOperation != null || consentOperation != null || bootstrapOperation != null || operation != null || photoUploadOperation != null || nemesisMutationOperation != null || record.has("pending")) return SyncCommandOutcome.Busy
            val current = binding()
            expectedLease?.let { if (current.lease != it) throw StaleOwnerException() }
            val server = db.bootstrapDao().binding(current.lease.storageScope)
            expectedContext?.let { if (server != it) throw SyncContextChangedException() }
            if (current.owner.kind != "account" || sessionFor(current) == null || !mutable.value.serverLinked) {
                publish("Zaloguj się i połącz konto, aby pobrać kopię serwera."); return SyncCommandOutcome.LoginRequired
            }
            if (server == null) return SyncCommandOutcome.ReconciliationRequired("account_bootstrap_required")
            if (!allowRecovery && server.requiresRecovery) return SyncCommandOutcome.ReconciliationRequired("account_context_not_ready")
            val retryAt = sessionFor(current)!!.optLong("apiRetryAt")
            if (retryAt > now()) { publish("Serwer jest zajęty. Ponów za co najmniej ${(retryAt - now() + 999) / 1000} s."); return SyncCommandOutcome.RetryAt(retryAt) }
            snapshotOperation = id
            diaryApplying = false
            mutable.value = mutable.value.copy(snapshotBusy = true, message = null)
            SyncContextFence(current.lease, server)
        } } catch (error: CancellationException) { throw error }
        catch (_: StaleOwnerException) { return SyncCommandOutcome.StaleContext }
        catch (_: SyncContextChangedException) { return SyncCommandOutcome.StaleContext }
        catch (_: Exception) { mutable.value = mutable.value.copy(message = "Pobieranie jest niedostępne. Dziennik zachowany."); return SyncCommandOutcome.TransientFailure }
        val lease = fence.lease
        try {
            val fresh = mutex.withLock {
                check(snapshotOperation == id); requireSyncContext(fence)
                val state = AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime ?: 0) > now() + 30_000
            }
            if (!fresh) check(refreshFor(lease, fence))
            var ticket = apiSession(fence)
            var request = withApiSession(ticket) { check(snapshotOperation == id); requireSyncContext(fence); store.begin(lease) }
            var refreshed = false
            while (true) {
                val captured = ticket
                val sent = request
                suspend fun ready() { check(snapshotOperation == id); requireSyncContext(fence); store.requireCurrent(sent) }
                val result = transport.get(captured, sent.query) { withApiSession(captured) { ready() } }
                if (result.status == 200) {
                    val next = withApiSession(captured) {
                        ready()
                        store.apply(sent, result.body)
                    }
                    var completedMessage="Kopia serwera pobrana. Lokalny dziennik i kolejka zachowane."
                    var appliedToDiary=false
                    if(next==null && diaryStore!=null) {
                        val mayApply=mutex.withLock {
                            requireApi(captured);requireSyncContext(fence);check(snapshotOperation==id)
                            if(db.bootstrapDao().binding(lease.storageScope)?.requiresRecovery==true)false
                            else {diaryApplying=true;publish();true}
                        }
                        if(mayApply) completedMessage=try {
                            val applied=diaryStore.apply(lease,sent.runId)
                            appliedToDiary=true
                            "Kopia pobrana, dziennik uzupełniony. Uwzględniono: ${applied.included}; lokalne zmiany zachowane do uzgodnienia: ${applied.held}."
                        } catch(error:CancellationException){throw error}
                        catch(_:Exception){"Kopia pobrana. Uzupełnienie dziennika wymaga ponowienia lub świeżej kopii; dane i kolejka zachowane."}
                    }
                    mutex.withLock {
                        if (snapshotOperation != id) return SyncCommandOutcome.StaleContext
                        requireApi(captured)
                        requireSyncContext(fence)
                        if (next == null) {snapshotOperation = null;diaryApplying=false}
                        publish(if (next == null) completedMessage else null)
                    }
                    if (next == null) return SyncCommandOutcome.Pulled(sent.runId,appliedToDiary)
                    request = next
                    continue
                }
                val code = if (result.status in setOf(429, 503)) "" else protocol.errorCode(result.body)
                withApiSession(captured) { ready() }
                if (result.status == 401 && code == "unauthorized" && !refreshed) {
                    refreshed = true
                    check(refreshFor(lease, fence))
                    ticket = apiSession(fence)
                    withApiSession(ticket) { ready() }
                    continue
                }
                var outcome:SyncCommandOutcome=SyncCommandOutcome.TransientFailure
                val message = withApiSession(captured) {
                    ready()
                    when {
                        result.status in setOf(429, 503) -> {
                            val seconds = BootstrapHttpProtocol.retrySeconds(result.retryAfter, now())
                            val retryAt = Math.addExact(now(), Math.multiplyExact(seconds, 1000))
                            val session = checkNotNull(sessionFor(binding()))
                            persist(copyRecord().put("session", JSONObject(session.toString()).put("apiRetryAt", retryAt)))
                            outcome=SyncCommandOutcome.RetryAt(retryAt)
                            "Serwer jest zajęty. Ponów za co najmniej $seconds s; pobrane strony zachowane."
                        }
                        result.status == 403 && code == "account_deleting" -> {
                            store.block(sent)
                            outcome=SyncCommandOutcome.ReconciliationRequired(code)
                            "Konto jest usuwane. Pobieranie zostało zablokowane; dane lokalne zachowane."
                        }
                        result.status == 410 && code in setOf("snapshot_expired", "sync_cursor_expired") -> {
                            store.expire(sent)
                            "Próba pobrania wygasła. Ponów od początku; poprzednia kopia i dziennik zachowane."
                        }
                        result.status == 409 && code in setOf("sync_epoch_changed", "account_generation_changed", "sync_reconciliation_required") -> {
                            store.invalidate(sent)
                            outcome=SyncCommandOutcome.ReconciliationRequired(code)
                            "Stan serwera się zmienił. Połącz konto ponownie; wymagane uzgodnienie, dane zachowane."
                        }
                        result.status == 401 -> {outcome=SyncCommandOutcome.LoginRequired;"Sesja wymaga ponownego logowania. Pobrane strony i dziennik zachowane."}
                        else -> "Pobieranie przerwane. Możesz je wznowić; dziennik zachowany."
                    }
                }
                mutex.withLock {
                    if (snapshotOperation == id) { owners.requireCurrent(lease); snapshotOperation = null; publish(message) }
                }
                return outcome
            }
        } catch (error: CancellationException) {
            withContext(NonCancellable) { finishSnapshot(id, lease, expectedContext = fence.server) }; throw error
        } catch (error: SnapshotCapacityException) {
            finishSnapshot(id, lease, "Pamięć kopii serwera jest pełna. Dziennik zachowany; potrzebne uporządkowanie kopii.",fence.server)
            return SyncCommandOutcome.ReconciliationRequired("snapshot_capacity")
        } catch (_: StaleOwnerException) {
            finishSnapshot(id, lease, expectedContext = fence.server);return SyncCommandOutcome.StaleContext
        } catch (_: SyncContextChangedException) {
            finishSnapshot(id, lease, expectedContext = fence.server);return SyncCommandOutcome.StaleContext
        } catch (_: Exception) {
            finishSnapshot(id, lease, expectedContext = fence.server);return SyncCommandOutcome.TransientFailure
        }
    }
    private suspend fun finishSnapshot(id: String, lease: OwnerLease,
        message: String = "Pobieranie przerwane. Ponów, aby wznowić; pobrane strony i dziennik zachowane.",
        expectedContext:AccountBindingEntity?=null) = mutex.withLock {
        if (snapshotOperation != id) return@withLock
        snapshotOperation = null
        diaryApplying = false
        try { publish(if (owners.currentLease() == lease && (expectedContext==null || db.bootstrapDao().binding(lease.storageScope)==expectedContext)) message else null) }
        catch (_: Exception) { mutable.value = mutable.value.copy(snapshotBusy = false, message = message) }
    }
}
