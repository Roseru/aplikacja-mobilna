package pl.roseru.kalorie

import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.data.LocalOwnerStore
import pl.roseru.kalorie.energy.*
import pl.roseru.kalorie.session.ApiSession
import java.util.UUID

/** Real Room/store/repository; only HTTPS and the authenticated session are synthetic. */
class EnergyConsentReceiptTest {
    @Test fun missingEtagStaysUnknownAcrossReopenAndExplicitRetryKeepsExactRequest()=invalidReceipt(null)
    @Test fun wrongRevisionEtagStaysUnknownAcrossReopenAndExplicitRetryKeepsExactRequest()=invalidReceipt("\"4\"")
    @Test fun weakEtagStaysUnknownAcrossReopenAndExplicitRetryKeepsExactRequest()=invalidReceipt("W/\"3\"")
    @Test fun unquotedEtagStaysUnknownAcrossReopenAndExplicitRetryKeepsExactRequest()=invalidReceipt("3")
    @Test fun nonCanonicalNumberEtagStaysUnknownAcrossReopenAndExplicitRetryKeepsExactRequest()=invalidReceipt("\"03\"")
    @Test fun paddedEtagStaysUnknownAcrossReopenAndExplicitRetryKeepsExactRequest()=invalidReceipt(" \"3\"")
    @Test fun multipleEtagsStayUnknownAcrossReopenAndExplicitRetryKeepsExactRequest()=invalidReceipt("\"3\", \"3\"")
    @Test fun matchingEtagDoesNotBypassRequestedBooleans()=invalidReceipt("\"3\"",wrongBoolean=true)
    @Test fun matchingEtagDoesNotBypassIfMatchPlusOne()=invalidReceipt("\"4\"",revision=4)
    @Test fun matchingEtagDoesNotBypassExact200Status()=invalidReceipt("\"3\"",status=201)

    private fun invalidReceipt(etag:String?,revision:Int=3,wrongBoolean:Boolean=false,status:Int=200)=runBlocking<Unit> {
        val name="energy-consent-receipt-${UUID.randomUUID()}";var db=EnergyFixture.database(name)
        try {
            val scope=EnergyFixture.account(db);val server=ConsentServer(etag,revision,wrongBoolean,status)
            val first=repository(db,scope,server)
            first.refresh(scope.lease)
            val token=checkNotNull(first.local(scope.lease).reviewToken)
            // This must fail at receipt validation after beforeSend persisted the unknown state.
            assertTrue(runCatching {first.automatic(scope.lease,token,false)}.exceptionOrNull() is IllegalArgumentException)
            val unknown=EnergyStore(db).attempts(scope).single()
            assertEquals("unknown",unknown.state);assertTrue(unknown.attempted)
            assertNull(unknown.responseJson);assertNull(unknown.errorCode)
            assertEquals("consent",unknown.kind);assertEquals("PUT",unknown.method);assertEquals("/me/consents",unknown.path)
            assertEquals("\"2\"",unknown.ifMatch)
            assertEquals("{\"automatic_energy_adjustment\":false,\"ranking\":false}",unknown.body)
            assertEquals(unknown.id,UUID.fromString(unknown.id).toString());assertEquals(64,unknown.fingerprint.length)
            assertEquals(Send(unknown.id,unknown.body,unknown.ifMatch,scope.binding.syncEpoch),server.sends.single())
            assertTrue(first.local(scope.lease).consentUncertain);assertNull(first.local(scope.lease).reviewToken)
            val callsBeforeReopen=server.paths.toList()
            db.close();db=EnergyFixture.database(name)
            val restored=checkNotNull(EnergyStore(db).scope(LocalOwnerStore(db).currentLease()))
            assertEquals(unknown,EnergyStore(db).attempts(restored).single())
            val second=repository(db,restored,server)
            repeat(2) {
                val local=second.local(restored.lease)
                assertTrue(local.consentUncertain);assertNull(local.reviewToken)
                assertEquals(unknown,local.attempts.single())
            }
            assertEquals(callsBeforeReopen,server.paths);assertEquals(1,server.sends.size)
            // No refresh, new operation or background affirmation is needed for a known key replay.
            server.etag="\"3\"";server.revision=3;server.wrongBoolean=false;server.status=200
            val settled=second.retry(restored.lease,unknown.id)
            assertEquals("succeeded",settled.state);assertTrue(settled.attempted)
            assertEquals(unknown.copy(state="succeeded",responseJson=server.validWire),settled)
            assertEquals(listOf(server.sends.first(),server.sends.first()),server.sends)
            assertEquals(1,server.admissions)
            assertEquals(settled,EnergyStore(db).attempts(restored).single())
            assertFalse(second.local(restored.lease).consentUncertain)
            assertTrue(server.paths.filter {it.first!="GET"}.all {it==("PUT" to "/me/consents")})
            assertEquals(2,server.paths.count {it.first!="GET"})
            assertTrue(EnergyStore(db).cached(restored).none {it.kind in setOf("analysis","unavailable")})
        }finally {db.close();EnergyFixture.context.deleteDatabase(name)}
    }

    @Test fun correctQuotedEtagSettlesOnceAndSuccessIsDurable()=runBlocking<Unit> {
        val name="energy-consent-valid-${UUID.randomUUID()}";var db=EnergyFixture.database(name)
        try {
            val scope=EnergyFixture.account(db);val server=ConsentServer("\"3\"")
            val repo=repository(db,scope,server);repo.refresh(scope.lease)
            val settled=repo.automatic(scope.lease,checkNotNull(repo.local(scope.lease).reviewToken),false)
            assertEquals("succeeded",settled.state);assertEquals(server.validWire,settled.responseJson)
            assertEquals(1,server.sends.size);assertEquals(1,server.admissions)
            assertFalse(repo.local(scope.lease).consentUncertain)
            db.close();db=EnergyFixture.database(name)
            val restored=checkNotNull(EnergyStore(db).scope(LocalOwnerStore(db).currentLease()))
            assertEquals(settled,EnergyStore(db).attempts(restored).single())
            assertTrue(runCatching {repository(db,restored,server).retry(restored.lease,settled.id)}.isFailure)
            assertEquals(1,server.sends.size)
        }finally {db.close();EnergyFixture.context.deleteDatabase(name)}
    }

    private fun repository(db:pl.roseru.kalorie.data.CalorieDatabase,scope:EnergyScope,server:ConsentServer)=
        EnergyRepository(EnergyStore(db),EnergyFixture.protocol(),EnergyFixture.Sessions(db,scope),EnergyFixture.Gate(),server){EnergyFixture.instant.toEpochMilli()}

    private data class Send(val key:String,val body:String,val ifMatch:String?,val epoch:String)
    private class ConsentServer(var etag:String?,var revision:Int=3,var wrongBoolean:Boolean=false,var status:Int=200):EnergyGateway {
        private val reads=EnergyFixture.Server()
        val sends=mutableListOf<Send>();val paths=mutableListOf<Pair<String,String>>()
        private val accepted=mutableMapOf<String,Send>()
        val admissions get()=accepted.size
        val validWire:String get()=wire(3,false)
        private fun wire(revision:Int,wrong:Boolean):String {
            val consent=JSONObject(EnergyFixture.sample("profile").getJSONObject("consents").toString())
                .put("revision",revision).put("automatic_energy_adjustment",wrong)
            return StrictJson.canonical(consent)
        }
        override suspend fun request(session:ApiSession,epoch:String,method:String,path:String,body:String?,key:String?,ifMatch:String?,beforeSend:suspend ()->Unit):EnergyHttpResult {
            paths+=method to path
            if(method=="GET")return reads.request(session,epoch,method,path,body,key,ifMatch,beforeSend)
            check(method=="PUT" && path=="/me/consents")
            beforeSend()
            val sent=Send(checkNotNull(key),checkNotNull(body),ifMatch,epoch)
            accepted[sent.key]?.let {check(it==sent)}?:run {accepted[sent.key]=sent}
            sends+=sent
            return EnergyHttpResult(status,wire(revision,wrongBoolean).toByteArray(Charsets.UTF_8),null,etag)
        }
    }
}
