package pl.roseru.kalorie

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.catalogupdate.*
import pl.roseru.kalorie.core.catalog.CatalogPackageReader
import pl.roseru.kalorie.core.network.*
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.net.URL
import java.security.cert.Certificate
import java.util.Collections
import java.util.UUID
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import javax.net.ssl.HttpsURLConnection

/** Real public HTTP adapter and shared policy wrapper; only the underlying socket is synthetic. */
class CatalogDownloadTransportTest {
    private val context=ApplicationProvider.getApplicationContext<Context>()
    private data class ReplySpec(val status:Int=200,val bytes:ByteArray=byteArrayOf(),val media:String="application/json",
        val headers:Map<String,String> = emptyMap(),val length:Long=bytes.size.toLong(),val holdAtEnd:Boolean=false)
    private class Reply(url:URL,val spec:ReplySpec):HttpsURLConnection(url) {
        val entered=CountDownLatch(1);val released=CountDownLatch(1)
        val reads=AtomicInteger();val closes=AtomicInteger();val disconnects=AtomicInteger()
        override fun connect(){}
        override fun disconnect(){disconnects.incrementAndGet();released.countDown()}
        override fun usingProxy()=false
        override fun getResponseCode()=spec.status
        override fun getContentType()=spec.media
        override fun getContentLengthLong()=spec.length
        override fun getHeaderField(name:String?):String?=spec.headers.entries.firstOrNull{it.key.equals(name,ignoreCase=true)}?.value
        override fun getCipherSuite()="SYNTHETIC"
        override fun getLocalCertificates():Array<Certificate>?=null
        override fun getServerCertificates():Array<Certificate> = emptyArray()
        override fun getInputStream():InputStream {
            val bytes=ByteArrayInputStream(spec.bytes)
            return object:InputStream() {
                override fun read():Int {
                    val buffer=ByteArray(1)
                    return if(read(buffer,0,1)<0)-1 else buffer[0].toInt() and 255
                }
                override fun read(buffer:ByteArray,offset:Int,length:Int):Int {
                    reads.incrementAndGet()
                    val count=bytes.read(buffer,offset,length)
                    if(count>=0 || !spec.holdAtEnd)return count
                    entered.countDown()
                    check(released.await(10,TimeUnit.SECONDS)){"Synthetic socket was never disconnected"}
                    throw IOException("Synthetic disconnected socket")
                }
                override fun close(){closes.incrementAndGet();bytes.close()}
            }
        }
    }
    private class Fixture {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
        val gate=CatalogUpdateFixtures.Gate().apply{allow()}
        val responses=ConcurrentLinkedQueue<ReplySpec>()
        val calls=Collections.synchronizedList(mutableListOf<Reply>())
        val opened=Channel<Reply>(Channel.UNLIMITED)
        val connections=PolicyConnectionFactory(scope,gate){url->Reply(url,checkNotNull(responses.poll())).also{
            calls+=it;check(opened.trySend(it).isSuccess)
        }}
        fun client(manifestTimeout:Long=30_000)=HttpsCatalogDownloadGateway("https://fixture.invalid/api/v1",gate,
            connections::open,manifestTimeoutMillis=manifestTimeout)
        suspend fun close(){scope.coroutineContext.job.cancelAndJoin();opened.cancel()}
    }
    private suspend fun rejected(code:String,action:suspend()->Unit) {
        try{action();fail("Expected rejected public response: $code")}
        catch(error:CatalogTransferRejected){assertEquals(code,error.code)}
    }

    @Test fun publicManifestAndPinnedGzipKeepExactBytesAndNeverCarryAccountCredentials()=runBlocking<Unit> {
        val fixture=Fixture();val data=CatalogUpdateFixtures.official(context)
        val target=File(context.cacheDir,"catalog-http-${UUID.randomUUID()}.download")
        try {
            val client=fixture.client();val permit=fixture.gate.captureAllowed()
            fixture.responses+=ReplySpec(bytes=data.manifest)
            val manifest=(client.manifest(permit) as CatalogHttpResult.Success).bytes!!
            assertArrayEquals(data.manifest,manifest)
            val reader=CatalogPackageReader(CatalogUpdateFixtures.schema(context),CatalogPackageReader.OFFICIAL_ID,"official")
            val selected=reader.inspect(manifest.inputStream())
            fixture.responses+=ReplySpec(bytes=data.gzip,media="application/gzip",headers=mapOf("ETag" to "\"${selected.sha256}\""))
            val progress=mutableListOf<Pair<Long,Long>>()
            assertTrue(client.download(selected,target,permit){received,total->progress+=received to total} is CatalogHttpResult.Success)
            assertArrayEquals(data.gzip,target.readBytes())
            assertEquals(selected.release,target.inputStream().use{reader.read(selected,it)}.release)
            assertEquals(0L to selected.compressedBytes.toLong(),progress.first())
            assertEquals(selected.compressedBytes.toLong() to selected.compressedBytes.toLong(),progress.last())
            assertEquals(listOf("/api/v1/offline-package/manifest","/api/v1/offline-package/base-pl.1.json.gz"),fixture.calls.map{it.url.path})
            fixture.calls.forEach { request->
                assertEquals("GET",request.requestMethod)
                assertFalse(request.instanceFollowRedirects);assertFalse(request.useCaches);assertFalse(request.doOutput)
                assertEquals("identity",request.getRequestProperty("Accept-Encoding"))
                assertEquals("",request.getRequestProperty("Cookie"));assertEquals("",request.getRequestProperty("Cookie2"))
                assertFalse(request.requestProperties.keys.any{it.equals("Authorization",ignoreCase=true)})
                assertEquals(1,request.disconnects.get())
            }
            assertEquals("application/json",fixture.calls[0].getRequestProperty("Accept"))
            assertEquals("application/gzip",fixture.calls[1].getRequestProperty("Accept"))

            fixture.responses+=ReplySpec(status=404)
            assertSame(CatalogHttpResult.Missing,client.manifest(permit))
            assertEquals(0,fixture.calls.last().reads.get())
            fixture.responses+=ReplySpec(status=503,headers=mapOf("Retry-After" to "120"))
            assertEquals("120",(client.manifest(permit) as CatalogHttpResult.Retry).value)
            assertEquals(0,fixture.calls.last().reads.get())
            fixture.responses+=ReplySpec(status=302,headers=mapOf("Location" to "https://other.invalid/"))
            rejected("catalog_http"){client.manifest(permit)}
            fixture.responses+=ReplySpec(bytes=data.gzip,media="application/gzip",headers=mapOf("Content-Encoding" to "gzip"))
            rejected("catalog_content_encoding"){client.download(selected,target,permit){_,_->}}
            fixture.responses+=ReplySpec(bytes=data.gzip,media="application/gzip",length=data.gzip.size.toLong()+1)
            rejected("catalog_size"){client.download(selected,target,permit){_,_->}}
            assertEquals(7,fixture.calls.size)
            assertTrue(fixture.calls.all{it.url.host=="fixture.invalid"})
        }finally{fixture.close();target.delete()}
    }

    @Test fun blockedThenReenabledTransferDisconnectsAndCannotDrainTheRevokedResponse()=runBlocking<Unit> {
        val fixture=Fixture();val data=CatalogUpdateFixtures.official(context)
        val target=File(context.cacheDir,"catalog-held-${UUID.randomUUID()}.download")
        try {
            val client=fixture.client();val permit=fixture.gate.captureAllowed()
            fixture.responses+=ReplySpec(bytes=data.gzip.copyOf(8),media="application/gzip",length=data.gzip.size.toLong(),holdAtEnd=true)
            val transfer=async(Dispatchers.IO){runCatching{client.download(data.descriptor,target,permit){_,_->}}}
            val response=withTimeout(10_000){fixture.opened.receive()}
            assertTrue(withContext(Dispatchers.IO){response.entered.await(10,TimeUnit.SECONDS)})
            fixture.gate.block();fixture.gate.allow(2)
            assertTrue(withTimeout(10_000){transfer.await()}.isFailure)
            assertArrayEquals(data.gzip.copyOf(8),target.readBytes())
            assertEquals(1,response.disconnects.get())
            assertEquals(0,response.closes.get())
            try{client.manifest(permit);fail("Old transfer permit must stay revoked")}
            catch(_:NetworkAccessDenied){}
            assertEquals(1,fixture.calls.size)
            fixture.responses+=ReplySpec(bytes=data.manifest)
            assertTrue(client.manifest(fixture.gate.captureAllowed()) is CatalogHttpResult.Success)
            assertEquals(2,fixture.calls.size)
        }finally{fixture.close();target.delete()}
    }

    @Test fun operationBudgetDisconnectsAResponseHeldBeyondIndividualReadsWithoutChangingThePolicy()=runBlocking<Unit> {
        val fixture=Fixture()
        try {
            fixture.responses+=ReplySpec(bytes="{".toByteArray(),length=-1,holdAtEnd=true)
            val client=fixture.client(manifestTimeout=1_500)
            val task=async(Dispatchers.IO){runCatching{client.manifest(fixture.gate.captureAllowed())}}
            val response=withTimeout(10_000){fixture.opened.receive()}
            assertTrue(withContext(Dispatchers.IO){response.entered.await(10,TimeUnit.SECONDS)})
            assertTrue(withTimeout(8_000){task.await()}.isFailure)
            assertEquals(NetworkAccessState.Allowed(1),fixture.gate.state.value)
            assertEquals(1,response.disconnects.get())
            assertEquals(0,response.closes.get())
        }finally{fixture.close()}
    }
}
