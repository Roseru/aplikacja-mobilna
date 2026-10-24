package pl.roseru.kalorie.community

import kotlinx.coroutines.*
import pl.roseru.kalorie.core.requireHttps
import pl.roseru.kalorie.session.ApiSession
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.net.ssl.HttpsURLConnection
import kotlin.coroutines.coroutineContext

internal class CommunityHttpResult(val status:Int,val bytes:ByteArray,val retryAfter:String?) {
    override fun toString()="CommunityHttpResult(status=$status)"
}
internal interface CommunityGateway {
    suspend fun request(session:ApiSession,epoch:String,method:String,path:String,body:String?=null,key:String?=null,
        ifMatch:String?=null,beforeSend:suspend ()->Unit):CommunityHttpResult
}

/** Shared PolicyConnectionFactory is mandatory. TLS, cancellation and device policy remain shared. */
internal class HttpsCommunityGateway(base:String,private val open:(URL)->HttpsURLConnection):CommunityGateway {
    private val base=base.trimEnd('/').also {
        val uri=requireHttps(it);require(uri.rawPath=="/api/v1" && uri.rawQuery==null && uri.rawFragment==null)
    }
    override suspend fun request(session:ApiSession,epoch:String,method:String,path:String,body:String?,key:String?,
        ifMatch:String?,beforeSend:suspend ()->Unit):CommunityHttpResult=withContext(Dispatchers.IO) {
        require(method in setOf("GET","POST","PUT","DELETE"))
        require(path.startsWith("/community/products") || path.startsWith("/products"))
        require(!path.contains('#') && !path.contains('\\') && !path.contains("..") && path.none {it.isISOControl()})
        require(session.accessToken.isNotBlank() && session.accessToken.length<=65_536 && session.accessToken.none {it.isISOControl()})
        CommunityProtocol.uuid(epoch);key?.let {CommunityProtocol.uuid(it)}
        ifMatch?.let {require(Regex("^\"(0|[1-9][0-9]{0,18})\"$").matches(it))}
        val payload=body?.toByteArray(Charsets.UTF_8)
        require(payload==null || (method in setOf("POST","PUT") && payload.size<=1_048_576))
        val connection=open(URL(base+path))
        val operationContext=coroutineContext
        val expired=AtomicBoolean(false)
        val timeout=watchdog.schedule({expired.set(true);connection.disconnect()},30,TimeUnit.SECONDS)
        fun checkAlive(){operationContext.ensureActive();if(expired.get())throw IOException("community_timeout")}
        try {
            connection.requestMethod=method;connection.instanceFollowRedirects=false;connection.useCaches=false
            connection.connectTimeout=15_000;connection.readTimeout=15_000
            connection.setRequestProperty("Authorization","Bearer ${session.accessToken}")
            connection.setRequestProperty("Accept","application/json");connection.setRequestProperty("Accept-Encoding","identity")
            connection.setRequestProperty("Cache-Control","no-store");connection.setRequestProperty("X-Sync-Epoch",epoch)
            connection.setRequestProperty("Cookie","");connection.setRequestProperty("Cookie2","")
            key?.let {connection.setRequestProperty("Idempotency-Key",it)}
            ifMatch?.let {connection.setRequestProperty("If-Match",it)}
            if(payload!=null) {
                connection.doOutput=true;connection.setFixedLengthStreamingMode(payload.size)
                connection.setRequestProperty("Content-Type","application/json; charset=utf-8")
            }
            checkAlive();beforeSend();checkAlive()
            if(payload!=null)connection.outputStream.use { output ->
                var offset=0
                while(offset<payload.size){checkAlive();val count=minOf(4096,payload.size-offset);output.write(payload,offset,count);offset+=count}
            }
            checkAlive();val status=connection.responseCode;checkAlive()
            require(status in 200..599 && status !in 300..399)
            require(connection.getHeaderField("Content-Encoding").let {it==null || it.equals("identity",true)})
            require(connection.contentType?.substringBefore(';')?.trim()?.equals("application/json",true)==true)
            require(connection.getHeaderField("Cache-Control")?.split(',')?.any {it.trim().equals("no-store",true)}==true)
            val max=if(status in 200..299)4*1024*1024 else 65_536
            val length=connection.getHeaderField("Content-Length")?.let {
                require(Regex("^[0-9]{1,10}$").matches(it));it.toLong().also {n->require(n<=max)}
            }
            val bytes=ByteArrayOutputStream().also { result ->
                val stream=if(status>=400)connection.errorStream else connection.inputStream
                requireNotNull(stream).use {input ->
                    val buffer=ByteArray(8192)
                    while(true){checkAlive();val count=input.read(buffer);checkAlive();if(count<0)break
                        require(result.size().toLong()+count<=max);result.write(buffer,0,count)}
                }
            }.toByteArray()
            checkAlive();require(bytes.isNotEmpty() && (length==null || length==bytes.size.toLong()))
            CommunityHttpResult(status,bytes,connection.getHeaderField("Retry-After"))
        } finally {timeout.cancel(false);connection.disconnect()}
    }
    companion object {
        private val watchdog=Executors.newSingleThreadScheduledExecutor {action->Thread(action,"community-http-timeout").apply {isDaemon=true}}
        fun encode(value:String)=URLEncoder.encode(value,Charsets.UTF_8.name())
    }
}
