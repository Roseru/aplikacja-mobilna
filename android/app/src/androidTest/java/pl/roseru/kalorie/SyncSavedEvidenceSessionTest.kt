package pl.roseru.kalorie

import android.content.Intent
import android.net.Uri
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.Configuration
import androidx.work.WorkManager
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import net.openid.appauth.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.SessionClaims
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.sync.*
import java.io.File
import java.time.LocalDate
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/** Actual saved-session controller, Room stores and runtime. No external service or socket. */
class SyncSavedEvidenceSessionTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val issuer="https://fixture.example/realms/saved-evidence"
    private val oldEpoch="55555555-5555-4555-8555-555555555555"
    private val nextEpoch="66666666-6666-4666-8666-666666666666"
    private fun uuid()=UUID.randomUUID().toString()
    private class UnreadStore:DataStore<Preferences> {
        override val data:Flow<Preferences> = flow {awaitCancellation()}
        override suspend fun updateData(transform:suspend (Preferences)->Preferences):Preferences=error("Unread fixture")
    }
    private inner class Policy(val unavailable:Boolean) {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
        val folder=File(context.cacheDir,"saved-policy-${uuid()}").apply {mkdirs()}
        val store:DataStore<Preferences> = if(unavailable)UnreadStore() else PreferenceDataStoreFactory.create(scope=scope,produceFile={File(folder,"policy.preferences_pb")})
        val gate=DeviceNetworkPolicy(store,scope)
        suspend fun block() {if(!unavailable){withTimeout(10000){gate.state.first {it is NetworkAccessState.Allowed}};gate.setBlocked(true)}}
        suspend fun close(){scope.coroutineContext.job.cancelAndJoin();folder.deleteRecursively()}
    }
    private fun page(epoch:String,entities:List<JSONObject> = emptyList(),mappings:List<JSONObject> = emptyList())=
        JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-${uuid()}")
            .put("page_token",JSONObject.NULL).put("checkpoint","checkpoint-${uuid()}").put("server_time","2026-10-25T12:00:00Z")
            .put("goal_timeline_revision",0).put("entities",JSONArray(entities)).put("recovery_mappings",JSONArray(mappings))
            .put("operation_receipts",JSONArray()).toString().toByteArray()
    private fun entity(operation:OutboxEntity,revision:Int=1)=JSONObject().put("entity_type",operation.entityType)
        .put("entity_id",operation.entityId).put("revision",revision).put("deleted",false).put("payload",JSONObject(operation.payload))
    private fun reply(request:MealPushRequest)=JSONObject().put("sync_epoch",request.batch.json().getString("sync_epoch"))
        .put("server_time","2026-10-25T12:00:00Z").put("results",JSONArray().put(JSONObject()
            .put("operation_id",request.operations.single().operationId).put("entity_id",request.operations.single().entityId)
            .put("status","accepted").put("revision",1).put("recovery_mapping",JSONObject.NULL))).toString().toByteArray()
    private inner class Harness {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val vault=SessionVault(context,"saved-evidence-${uuid()}")
        val owners=LocalOwnerStore(db);val boot=AccountBootstrapStore(db)
        val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema));val push=MealPushStore(db,schema)
        val diary=ServerDiaryStore(db,schema);val recovery=ReconciliationStore(db,schema)
        val authCalls=AtomicInteger();val gets=AtomicInteger();val posts=AtomicInteger()
        val results=mutableListOf<SavedSyncEvidenceResult>()
        val clock=System.currentTimeMillis()
        lateinit var lease:OwnerLease;lateinit var owner:LocalOwnerEntity;lateinit var binding:AccountBindingEntity
        lateinit var controller:SessionController
        var work:WorkManager?=null
        var getAnswer:suspend (ApiSession,SnapshotQuery,suspend()->Unit)->BootstrapHttpResult={_,_,_->error("No HTTP GET permitted")}
        suspend fun account() {
            owners.ensureGuest();owner=owners.registerIdentity(issuer,uuid());lease=owners.select(owner.id)
            binding=boot.apply(boot.begin(lease),BootstrapResponse(uuid(),oldEpoch,1,"2026-10-25T12:00:00Z"))
            assertNull(snapshots.apply(snapshots.begin(lease),page(oldEpoch)))
        }
        fun seed(expired:Boolean=true,retryAt:Long=clock+90000) {
            val config=AuthorizationServiceConfiguration(AuthorizationServiceDiscovery(JSONObject().put("issuer",issuer)
                .put("authorization_endpoint","$issuer/auth").put("token_endpoint","$issuer/token").put("jwks_uri","$issuer/certs")
                .put("response_types_supported",JSONArray(listOf("code"))).put("subject_types_supported",JSONArray(listOf("public")))
                .put("id_token_signing_alg_values_supported",JSONArray(listOf("RS256")))))
            val request=AuthorizationRequest.Builder(config,SessionClaims.CLIENT_ID,ResponseTypeValues.CODE,Uri.parse(context.packageName+":/oauthredirect")).build()
            val response=AuthorizationResponse.Builder(request).setAuthorizationCode("synthetic-evidence-code").build()
            val tokens=TokenResponse.Builder(response.createTokenExchangeRequest()).setTokenType("Bearer")
                .setAccessToken("synthetic-evidence-access").setRefreshToken("synthetic-evidence-refresh")
                .setAccessTokenExpirationTime(if(expired)clock-1 else clock+300000).build()
            val auth=AuthState(response,null).apply {update(tokens,null)}
            vault.write(JSONObject().put("session",JSONObject().put("ownerId",owner.id).put("issuer",issuer)
                .put("subject",owner.subject).put("authState",auth.jsonSerializeString()).put("apiRetryAt",retryAt)))
        }
        suspend fun start(expired:Boolean=true,retryAt:Long=clock+90000) {
            seed(expired,retryAt)
            val auth=object:OidcGateway {
                override suspend fun discover(issuer:String):AuthorizationServiceConfiguration {authCalls.incrementAndGet();error("No discovery")}
                override fun browser(request:AuthorizationRequest):Intent {authCalls.incrementAndGet();error("No browser")}
                override suspend fun tokens(request:TokenRequest):TokenResponse {authCalls.incrementAndGet();error("No refresh")}
            }
            val read=object:SnapshotGateway {
                override suspend fun get(session:ApiSession,query:SnapshotQuery,beforeSend:suspend()->Unit):BootstrapHttpResult {
                    gets.incrementAndGet();return getAnswer(session,query,beforeSend)
                }
            }
            val write=object:MealPushGateway {
                override suspend fun post(session:ApiSession,batch:PushBatch,beforeSend:suspend()->Unit):BootstrapHttpResult {posts.incrementAndGet();error("No POST")}
            }
            controller=SessionController(db,vault,auth,issuer,context.packageName,now={clock},snapshotGateway=read,
                snapshotProtocol=SnapshotProtocol(schema),mealPushGateway=write,mealPushStore=push,mealPushProtocol=PushProtocol(schema),
                diaryStore=diary,reconciliationStore=recovery)
            controller.start();assertEquals(!expired,controller.view.value.hasSession)
        }
        suspend fun frozen():MealPushRequest {
            DiaryRepository(db,context,lease).addWeight(82.125,LocalDate.of(2001,1,2))
            val frozen=push.prepare(lease)!!;push.markAttempted(frozen);push.applyAck(push.prepareAck(frozen,200,reply(frozen)));return frozen
        }
        suspend fun runtime(gate:NetworkAccessGate):Pair<SyncCoordinator,SyncWorkRuntime> {
            WorkManagerTestInitHelper.initializeTestWorkManager(context,Configuration.Builder().setExecutor(SynchronousExecutor()).setTaskExecutor(SynchronousExecutor()).build())
            work=WorkManager.getInstance(context)
            val coordinator=SyncCoordinator(db,schema,controller,networkGate=gate,
                savedEvidence=SavedSyncEvidenceDrainer {l,b->controller.drainSavedSyncEvidence(l,b).also {results+=it}}) {clock}
            val initial=coordinator.request(lease,binding)
            db.syncWorkDao().save(initial.copy(status=if(binding.requiresRecovery)"reconciliation" else "ready",phase="push",
                activeVersion=initial.requestedVersion,retryAtMillis=clock+90000,consecutiveFailures=2))
            return coordinator to SyncWorkRuntime(db,coordinator,SyncWorkScheduler(checkNotNull(work)){clock})
        }
        fun noNetwork(){assertEquals(0,authCalls.get());assertEquals(0,gets.get());assertEquals(0,posts.get())}
        fun close(){work?.cancelAllWork()?.result?.get();vault.clear();db.close()}
    }

    @Test fun actualExpiredSessionDrainsCompleteRawWithSavedOrdinaryAckOfflineAndKeepsLaterEditAndCycle()=runBlocking<Unit> {
        for(unavailable in listOf(false,true)) {
            val p=Policy(unavailable);val h=Harness()
            try {
                p.block();h.account();val frozen=h.frozen();val saved=h.db.pushDao().batch(frozen.id)!!
                DiaryRepository(h.db,context,h.lease).editWeight(frozen.operations.single().entityId,87.5)
                val later=h.db.serverDiaryDao().unsettled(h.lease.storageScope).single()
                val remote=uuid();val remoteRow=JSONObject().put("entity_type","weight").put("entity_id",remote).put("revision",1).put("deleted",false)
                    .put("payload",WeightWire.create(83.125,"2001-01-04T12:00:00Z","UTC","2001-01-04",schema).json())
                val raw=h.snapshots.begin(h.lease);assertNull(h.snapshots.apply(raw,page(oldEpoch,listOf(entity(frozen.operations.single()),remoteRow))))
                assertNull(h.db.serverDiaryDao().application(raw.runId));h.start()
                val (coordinator,runtime)=h.runtime(p.gate)
                val reason=if(unavailable)"network_unavailable" else "network_blocked"
                assertEquals(SyncCoordinator.Outcome.Stopped(reason),runtime.manual(h.lease))
                assertEquals(SavedSyncEvidenceResult.APPLIED,h.results.last());h.noNetwork()
                assertEquals(saved,h.db.pushDao().batch(frozen.id));assertEquals(later,h.db.dao().operation(later.operationId))
                assertEquals(87.5,h.db.dao().weight(frozen.operations.single().entityId,h.lease.storageScope)!!.kg,0.0)
                assertEquals(83.125,h.db.dao().weight(remote,h.lease.storageScope)!!.kg,0.0)
                assertEquals(raw.runId,h.db.serverDiaryDao().latest(h.lease.storageScope)!!.runId)
                val work=coordinator.state(h.lease)!!;assertEquals("push",work.phase);assertEquals(0,work.acknowledged)
                assertEquals(h.clock+90000,work.retryAtMillis);assertEquals(2,work.consecutiveFailures);assertNotEquals("idle",work.status)
                assertEquals(SyncCoordinator.Outcome.Stopped(reason),runtime.manual(h.lease))
                assertEquals(SavedSyncEvidenceResult.NO_LOCAL_WORK,h.results.last());h.noNetwork()
            }finally{h.close();p.close()}
        }
    }

    @Test fun actualSessionAcceptsPersistedRecoveryRawThenRevalidatesSavedAckWithoutFinishingReconciliationOrSending()=runBlocking<Unit> {
        for(unavailable in listOf(false,true)) {
            val p=Policy(unavailable);val h=Harness()
            try {
                p.block();h.account();val original=h.frozen();val oldAck=h.db.pushDao().batch(original.id)!!
                h.binding=h.boot.apply(h.boot.begin(h.lease),BootstrapResponse(h.binding.accountId,nextEpoch,1,"2026-10-25T12:00:00Z"))
                assertTrue(h.binding.requiresRecovery)
                val plan=h.recovery.begin(h.lease,h.binding)
                h.recovery.approve(h.lease,h.binding,plan.planId,plan.account,plan.issuer,plan.subject)
                val before=h.recovery.nextSnapshot(h.lease,h.binding,plan.planId)!!
                assertNull(h.snapshots.apply(before,page(nextEpoch)));h.recovery.acceptCompletedSnapshot(h.lease,h.binding,plan.planId,before.runId)
                val source=h.db.importDao().sources(plan.planId).single()
                h.recovery.decide(h.lease,h.binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"recreate_missing\"}")
                val request=h.recovery.preparePush(h.lease,h.binding,plan.planId)!!;h.recovery.markAttempted(request)
                h.recovery.defer(request,h.clock+90000)
                val target=uuid();val mapping=JSONObject().put("source_epoch",source.sourceEpoch)
                    .put("source_entity_id",JSONObject(source.sourceJson).getString("wire_id")).put("target_entity_id",target).put("target_revision",7)
                val ack=JSONObject().put("sync_epoch",nextEpoch).put("server_time","2026-10-25T12:00:00Z")
                    .put("results",JSONArray().put(JSONObject().put("operation_id",request.operations.single().operationId)
                        .put("entity_id",request.operations.single().entityId).put("status","already_applied").put("revision",5).put("recovery_mapping",mapping))).toString().toByteArray()
                val prepared=h.recovery.prepareAck(request,200,ack);assertTrue(prepared.result.awaitingSnapshot);h.recovery.applyAck(prepared)
                val saved=h.db.importDao().batch(request.id)!!;assertEquals("awaiting_snapshot",saved.state)
                val after=h.recovery.nextSnapshot(h.lease,h.binding,plan.planId)!!
                assertNull(h.snapshots.apply(after,page(nextEpoch,listOf(entity(request.operations.single(),7).put("entity_id",target)),listOf(mapping))))
                assertNotNull(h.recovery.pendingSnapshotAcceptance(h.lease,h.binding,plan.planId))
                h.start();val (coordinator,runtime)=h.runtime(p.gate)
                assertEquals(SyncCoordinator.Outcome.Stopped("reconciliation"),runtime.manual(h.lease))
                assertEquals(SavedSyncEvidenceResult.APPLIED,h.results.last());h.noNetwork()
                val applied=h.db.importDao().batch(request.id)!!
                assertEquals("complete",applied.state);assertEquals(saved.requestJson,applied.requestJson);assertEquals(saved.requestHash,applied.requestHash)
                assertEquals(saved.retryAtMillis,applied.retryAtMillis);assertEquals("acked",h.db.dao().operation(request.operations.single().operationId)!!.status)
                assertEquals(target,h.db.importDao().sources(plan.planId).single().wireId)
                assertEquals(oldAck,h.db.pushDao().batch(original.id));assertTrue(h.db.bootstrapDao().binding(h.lease.storageScope)!!.requiresRecovery)
                assertNotEquals("complete",h.db.importDao().plan(plan.planId)!!.state)
                val work=coordinator.state(h.lease)!!;assertEquals("push",work.phase);assertEquals(0,work.acknowledged);assertEquals(h.clock+90000,work.retryAtMillis)
                assertEquals(SyncCoordinator.Outcome.Stopped("reconciliation"),runtime.manual(h.lease))
                assertEquals(SavedSyncEvidenceResult.NO_LOCAL_WORK,h.results.last());h.noNetwork()
            }finally{h.close();p.close()}
        }
    }

    @Test fun incompleteRawNoWorkStaleOwnerAndWrongContextCannotMutateOrRefresh()=runBlocking<Unit> {
        val h=Harness()
        try {
            h.account();h.diary.apply(h.lease);h.start()
            val before=h.db.serverDiaryDao().latest(h.lease.storageScope)
            val partial=h.snapshots.begin(h.lease) // No complete new evidence; must not fetch its next page.
            assertEquals(SavedSyncEvidenceResult.NO_LOCAL_WORK,h.controller.drainSavedSyncEvidence(h.lease,h.binding))
            assertEquals(before,h.db.serverDiaryDao().latest(h.lease.storageScope));assertEquals("pending",h.db.snapshotDao().run(partial.runId)!!.state)
            assertEquals(SavedSyncEvidenceResult.STALE_CONTEXT,h.controller.drainSavedSyncEvidence(h.lease,h.binding.copy(accountGeneration=2)))
            val old=h.lease;h.owners.select(h.owners.ensureGuest().id);h.lease=h.owners.select(h.owner.id)
            assertEquals(SavedSyncEvidenceResult.STALE_CONTEXT,h.controller.drainSavedSyncEvidence(old,h.binding));h.noNetwork()
            val cancelled=async(start=CoroutineStart.UNDISPATCHED) {currentCoroutineContext().cancel();h.controller.drainSavedSyncEvidence(h.lease,h.binding)}
            try{cancelled.await();fail("Cancellation must propagate")}catch(_:CancellationException){}
            assertEquals(before,h.db.serverDiaryDao().latest(h.lease.storageScope));h.noNetwork()
        }finally{h.close()}
    }

    @Test fun typedProjectionFailureLeavesPreviousDiaryAndCompleteRawUnchangedWithoutFallbackHttp()=runBlocking<Unit> {
        val h=Harness()
        try {
            h.account();val id=uuid()
            val weight=JSONObject().put("entity_type","weight").put("entity_id",id).put("revision",2).put("deleted",false)
                .put("payload",WeightWire.create(81.25,"2001-01-04T12:00:00Z","UTC","2001-01-04",schema).json())
            val first=h.snapshots.begin(h.lease);assertNull(h.snapshots.apply(first,page(oldEpoch,listOf(weight))))
            h.diary.apply(h.lease,first.runId)
            val previous=h.db.serverDiaryDao().latest(h.lease.storageScope);val local=h.db.dao().weight(id,h.lease.storageScope)
            val backwards=h.snapshots.begin(h.lease);assertNull(h.snapshots.apply(backwards,page(oldEpoch,listOf(JSONObject(weight.toString()).put("revision",1)))))
            val raw=h.db.snapshotDao().run(backwards.runId);val pages=h.db.snapshotDao().pages(backwards.runId)
            h.start()
            assertEquals(SavedSyncEvidenceResult.FAILURE,h.controller.drainSavedSyncEvidence(h.lease,h.binding))
            assertEquals(previous,h.db.serverDiaryDao().latest(h.lease.storageScope));assertEquals(local,h.db.dao().weight(id,h.lease.storageScope))
            assertEquals(raw,h.db.snapshotDao().run(backwards.runId));assertEquals(pages,h.db.snapshotDao().pages(backwards.runId))
            assertNull(h.db.serverDiaryDao().application(backwards.runId));h.noNetwork()
        }finally{h.close()}
    }

    @Test fun newerApprovedPlanPreventsAutomaticReactivationOfOlderUnacceptedRaw()=runBlocking<Unit> {
        val h=Harness()
        try {
            h.account();h.frozen()
            h.binding=h.boot.apply(h.boot.begin(h.lease),BootstrapResponse(h.binding.accountId,nextEpoch,1,"2026-10-25T12:00:00Z"))
            val old=h.recovery.begin(h.lease,h.binding)
            h.recovery.approve(h.lease,h.binding,old.planId,old.account,old.issuer,old.subject)
            val raw=h.recovery.nextSnapshot(h.lease,h.binding,old.planId)!!
            assertNull(h.snapshots.apply(raw,page(nextEpoch)))
            assertEquals(raw.runId,h.recovery.pendingSnapshotAcceptance(h.lease,h.binding,old.planId))
            DiaryRepository(h.db,context,h.lease).addWeight(86.5,LocalDate.of(2001,1,3))
            val latest=h.recovery.begin(h.lease,h.binding);assertNotEquals(old.planId,latest.planId)
            h.recovery.approve(h.lease,h.binding,latest.planId,latest.account,latest.issuer,latest.subject)
            val active=h.db.snapshotDao().access(h.lease.storageScope)
            h.start()
            assertEquals(SavedSyncEvidenceResult.NO_LOCAL_WORK,h.controller.drainSavedSyncEvidence(h.lease,h.binding))
            assertEquals(active,h.db.snapshotDao().access(h.lease.storageScope))
            assertEquals(raw.runId,h.recovery.pendingSnapshotAcceptance(h.lease,h.binding,old.planId))
            assertTrue(h.db.importDao().evidence(old.planId).isEmpty());h.noNetwork()
        }finally{h.close()}
    }

    @Test fun existingNetworkReservationReturnsBusyAndCancellationReleasesSessionForLocalDrain()=runBlocking<Unit> {
        val h=Harness();val entered=CompletableDeferred<Unit>();var active:Deferred<SyncStepResult>?=null
        try {
            h.account();h.diary.apply(h.lease);h.start(expired=false,retryAt=0)
            h.getAnswer={_,_,beforeSend->beforeSend();entered.complete(Unit);awaitCancellation()}
            active=async {h.controller.executeSyncStep(h.lease,h.binding,SyncStep.PULL)}
            withTimeout(10000){entered.await()}
            assertEquals(SavedSyncEvidenceResult.BUSY,h.controller.drainSavedSyncEvidence(h.lease,h.binding))
            active.cancelAndJoin();active=null
            assertEquals(SavedSyncEvidenceResult.NO_LOCAL_WORK,h.controller.drainSavedSyncEvidence(h.lease,h.binding))
            assertEquals(1,h.gets.get());assertEquals(0,h.authCalls.get());assertEquals(0,h.posts.get())
        }finally{active?.cancelAndJoin();h.close()}
    }
}
