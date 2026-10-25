package pl.roseru.kalorie

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.energy.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.URL
import java.security.Principal
import java.security.cert.Certificate
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import javax.net.ssl.HttpsURLConnection

class EnergyTransportTest {
    @Test fun exactFrozenBytesAndHeadersAreSentAndCancellationDisconnectsBlockedIo()=runBlocking<Unit> {
        val name="energy-http-${UUID.randomUUID()}";val db=EnergyFixture.database(name)
        try {
            val scope=EnergyFixture.account(db);val session=EnergyFixture.Sessions(db,scope).session(scope)
            val body=EnergyFixture.protocol().analysisRequest(EnergyFixture.protocol().state(EnergyFixture.bytes("state")),"mock",true,true)
            val key=UUID.randomUUID().toString();val reply=EnergyFixture.bytes("analysis")
            val socket=Socket(URL("https://energy.fixture/api/v1/me/energy/analyses"),reply)
            val gateway=HttpsEnergyGateway("https://energy.fixture/api/v1"){socket}
            var checked=0
            val response=gateway.request(session,scope.binding.syncEpoch,"POST","/me/energy/analyses",body,key,null){checked++}
            assertEquals(1,checked);assertArrayEquals(reply,response.bytes)
            assertEquals(body,socket.sent.toString("UTF-8"));assertEquals(key,socket.getRequestProperty("Idempotency-Key"))
            assertEquals(scope.binding.syncEpoch,socket.getRequestProperty("X-Sync-Epoch"))
            assertEquals("Bearer synthetic-access",socket.getRequestProperty("Authorization"))
            assertEquals("identity",socket.getRequestProperty("Accept-Encoding"));assertEquals("no-store",socket.getRequestProperty("Cache-Control"))
            assertFalse(socket.instanceFollowRedirects);assertFalse(socket.useCaches)
            val held=Socket(URL("https://energy.fixture/api/v1/me/energy/state"),reply,true)
            val pending=async(Dispatchers.Default){HttpsEnergyGateway("https://energy.fixture/api/v1"){held}
                .request(session,scope.binding.syncEpoch,"GET","/me/energy/state",null,null,null){}}
            try {
                assertTrue(held.entered.await(5,TimeUnit.SECONDS))
                withTimeout(5_000){pending.cancelAndJoin()}
                assertTrue(pending.isCancelled);assertTrue(held.disconnected)
            }finally {held.disconnect();pending.cancelAndJoin()}
        }finally {db.close();EnergyFixture.context.deleteDatabase(name)}
    }
    private class Socket(url:URL,private val reply:ByteArray,private val blocked:Boolean=false):HttpsURLConnection(url) {
        val sent=ByteArrayOutputStream();val entered=CountDownLatch(1);private val released=CountDownLatch(1)
        @Volatile var disconnected=false
        override fun connect(){}
        override fun disconnect(){disconnected=true;released.countDown()}
        override fun usingProxy()=false
        override fun getResponseCode()=200
        override fun getOutputStream()=sent
        override fun getInputStream():InputStream=if(!blocked)ByteArrayInputStream(reply)else object:InputStream() {
            override fun read():Int {entered.countDown();check(released.await(35,TimeUnit.SECONDS));return -1}
        }
        override fun getHeaderField(name:String):String?=when(name.lowercase()){"content-type"->"application/json";"content-length"->reply.size.toString();"cache-control"->"no-store";else->null}
        override fun getContentType()="application/json"
        override fun getCipherSuite()="SYNTHETIC"
        override fun getLocalCertificates():Array<Certificate>?=null
        override fun getServerCertificates():Array<Certificate> = emptyArray()
        override fun getPeerPrincipal():Principal=Principal {"synthetic"}
        override fun getLocalPrincipal():Principal?=null
    }
}
