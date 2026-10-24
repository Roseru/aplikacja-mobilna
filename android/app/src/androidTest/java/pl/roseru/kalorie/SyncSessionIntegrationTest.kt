package pl.roseru.kalorie

import android.content.Intent
import android.net.Uri
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.*
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import net.openid.appauth.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.sync.*
import java.time.LocalDate
import java.util.UUID

/** Restored synthetic vault, REAL O1 controller/engine/Room/worker. Transport interfaces only; no HTTP/OIDC service. */
class SyncSessionIntegrationTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val issuer="https://fixture.example/realms/runtime"
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun seed(vault:SessionVault,owner:LocalOwnerEntity,clock:Long) {
        val config=AuthorizationServiceConfiguration(AuthorizationServiceDiscovery(JSONObject().put("issuer",issuer)
            .put("authorization_endpoint","$issuer/auth").put("token_endpoint","$issuer/token").put("jwks_uri","$issuer/certs")
            .put("response_types_supported",JSONArray(listOf("code"))).put("subject_types_supported",JSONArray(listOf("public")))
            .put("id_token_signing_alg_values_supported",JSONArray(listOf("RS256")))))
        val redirect=Uri.parse(context.packageName+":/oauthredirect")
        val request=AuthorizationRequest.Builder(config,SessionClaims.CLIENT_ID,ResponseTypeValues.CODE,redirect).build()
        val response=AuthorizationResponse.Builder(request).setAuthorizationCode("synthetic-restored-code").build()
        val tokens=TokenResponse.Builder(response.createTokenExchangeRequest()).setTokenType("Bearer")
            .setAccessToken("synthetic-runtime-access").setRefreshToken("synthetic-runtime-refresh").setAccessTokenExpirationTime(clock+300_000).build()
        val state=AuthState(response,null).apply {update(tokens,null)}
        vault.write(JSONObject().put("session",JSONObject().put("ownerId",owner.id).put("issuer",issuer)
            .put("subject",owner.subject).put("authState",state.jsonSerializeString())))
    }
    @Test fun actualSessionExecutesPullPushPullThroughBothManualRuntimeAndRealWorker()=runBlocking<Unit> {
        for(worker in listOf(false,true)) {
            val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
            val vault=SessionVault(context,"runtime-integration-"+UUID.randomUUID());var work:WorkManager?=null
            try {
                val clock=System.currentTimeMillis();val schema=CanonicalMealRows.schema(context);val owners=LocalOwnerStore(db)
                owners.ensureGuest();val owner=owners.registerIdentity(issuer,"synthetic-runtime-subject");val lease=owners.select(owner.id)
                val bootstrap=AccountBootstrapStore(db);val binding=bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),epoch,1,"2026-10-23T12:00:00Z"))
                seed(vault,owner,clock)
                val events=mutableListOf<SyncStep>();val remote=linkedMapOf<String,JSONObject>();var authCalls=0
                val auth=object:OidcGateway {
                    override suspend fun discover(issuer:String):AuthorizationServiceConfiguration {authCalls++;error("No live discovery")}
                    override fun browser(request:AuthorizationRequest):Intent {authCalls++;error("No browser")}
                    override suspend fun tokens(request:TokenRequest):TokenResponse {authCalls++;error("Restored token must not refresh")}
                }
                val snapshots=object:SnapshotGateway {
                    override suspend fun get(session:ApiSession,query:SnapshotQuery,beforeSend:suspend()->Unit):BootstrapHttpResult {
                        assertFalse(db.inTransaction());beforeSend();events+=SyncStep.PULL
                        return BootstrapHttpResult(200,JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-runtime-${events.size}")
                            .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-checkpoint-${events.size}").put("server_time","2026-10-23T12:00:00Z")
                            .put("goal_timeline_revision",0).put("entities",JSONArray(remote.values.toList()))
                            .put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray()).toString().toByteArray())
                    }
                }
                val pushes=object:MealPushGateway {
                    override suspend fun post(session:ApiSession,batch:PushBatch,beforeSend:suspend()->Unit):BootstrapHttpResult {
                        assertFalse(db.inTransaction());beforeSend();events+=SyncStep.PUSH
                        assertTrue(db.pushDao().pending(lease.storageScope).single().attempted)
                        val operations=batch.json().getJSONArray("operations");val results=JSONArray()
                        for(index in 0 until operations.length()) {
                            val op=operations.getJSONObject(index);val id=op.getString("entity_id")
                            remote[id]=JSONObject().put("entity_type",op.getString("entity_type")).put("entity_id",id).put("revision",1).put("deleted",false).put("payload",op.get("payload"))
                            results.put(JSONObject().put("operation_id",op.getString("operation_id")).put("entity_id",id).put("status","accepted").put("revision",1).put("recovery_mapping",JSONObject.NULL))
                        }
                        return BootstrapHttpResult(200,JSONObject().put("sync_epoch",epoch).put("server_time","2026-10-23T12:00:00Z").put("results",results).toString().toByteArray())
                    }
                }
                val controller=SessionController(db,vault,auth,issuer,context.packageName,now={clock},snapshotGateway=snapshots,
                    snapshotProtocol=SnapshotProtocol(schema),mealPushGateway=pushes,mealPushStore=MealPushStore(db,schema),
                    mealPushProtocol=PushProtocol(schema),diaryStore=ServerDiaryStore(db,schema),reconciliationStore=ReconciliationStore(db,schema))
                controller.start();assertTrue(controller.view.value.hasSession)
                val id=UUID.randomUUID().toString();DiaryRepository(db,context,lease).addWeight(82.125,LocalDate.of(2001,1,2),id)
                val operation=db.serverDiaryDao().unsettled(lease.storageScope).single();val exact=operation.wireJson
                lateinit var runtime:SyncWorkRuntime
                val factory=object:WorkerFactory() {
                    override fun createWorker(appContext:android.content.Context,workerClassName:String,parameters:WorkerParameters):ListenableWorker?=
                        if(workerClassName==DiarySyncWorker::class.java.name)DiarySyncWorker(appContext,parameters,runtime) else null
                }
                WorkManagerTestInitHelper.initializeTestWorkManager(context,Configuration.Builder().setExecutor(SynchronousExecutor()).setTaskExecutor(SynchronousExecutor()).setWorkerFactory(factory).build())
                work=WorkManager.getInstance(context)
                val coordinator=SyncCoordinator(db,schema,controller,networkGate=RuntimeAllowedNetwork){clock};val scheduler=SyncWorkScheduler(work){clock}
                runtime=SyncWorkRuntime(db,coordinator,scheduler)
                if(!worker)assertEquals(SyncCoordinator.Outcome.Complete,runtime.manual(lease)) else {
                    coordinator.request(lease,binding)
                    val request=scheduler.enqueue(SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding),policyRevision=1))
                    WorkManagerTestInitHelper.getTestDriver(context)!!.setAllConstraintsMet(request.id)
                    assertEquals(WorkInfo.State.SUCCEEDED,withTimeout(15_000){work.getWorkInfoByIdFlow(request.id).filterNotNull().first {it.state.isFinished}}.state)
                }
                assertEquals(listOf(SyncStep.PULL,SyncStep.PUSH,SyncStep.PULL),events)
                assertEquals("idle",coordinator.state(lease)!!.status);assertEquals(1,coordinator.state(lease)!!.acknowledged)
                assertEquals("acked",db.dao().operation(operation.operationId)!!.status);assertEquals(exact,db.dao().operation(operation.operationId)!!.wireJson)
                assertEquals(82.125,db.dao().weight(id,lease.storageScope)!!.kg,0.0);assertEquals(1,db.weightSyncDao().state(lease.storageScope,id)!!.serverRevision)
                val active=db.snapshotDao().access(lease.storageScope)!!.activeRunId!!
                assertEquals(active,db.serverDiaryDao().latest(lease.storageScope)!!.runId);assertEquals(0,authCalls)
                assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
            }finally{work?.cancelAllWork()?.result?.get();vault.clear();db.close()}
        }
    }
}
