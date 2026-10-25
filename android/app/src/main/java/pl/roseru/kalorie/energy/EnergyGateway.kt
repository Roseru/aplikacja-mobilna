package pl.roseru.kalorie.energy

import kotlinx.coroutines.*
import pl.roseru.kalorie.core.requireHttps
import pl.roseru.kalorie.session.ApiSession
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.net.ssl.HttpsURLConnection
import kotlin.coroutines.coroutineContext

internal class EnergyHttpResult(val status:Int,val bytes:ByteArray,val retryAfter:String?) {
    override fun toString()="EnergyHttpResult(status=$status)"
}
internal interface EnergyGateway {
    suspend fun request(session:ApiSession,epoch:String,method:String,path:String,body:String?=null,key:String?=null,
        ifMatch:String?=null,beforeSend:suspend ()->Unit):EnergyHttpResult
}
internal class HttpsEnergyGateway(base:String,private val open:(URL)->HttpsURLConnection):EnergyGateway {
    private val base=base.trimEnd('/').also {
        val uri=requireHttps(it);require(uri.rawPath=="/api/v1" && uri.rawQuery==null && uri.rawFragment==null)
    }
    override suspend fun request(session:ApiSession,epoch:String,method:String,path:String,body:String?,key:String?,
        ifMatch:String?,beforeSend:suspend ()->Unit):EnergyHttpResult=withContext(Dispatchers.IO) {coroutineScope {
        require(method in setOf("GET","POST","PUT") && allowedPath(method,path))
        require(session.accessToken.isNotBlank() && session.accessToken.length<=65_536 && session.accessToken.none {it.isISOControl()})
        require(java.util.UUID.fromString(epoch).toString()==epoch)
        key?.let {require(java.util.UUID.fromString(it).toString()==it)}
        ifMatch?.let {require(Regex("^\"[1-9][0-9]{0,9}\"$").matches(it))}
        val payload=body?.toByteArray(Charsets.UTF_8)
        require(payload==null || (method in setOf("POST","PUT") && payload.size in 1..65_536))
        require(if(method=="GET")payload==null && key==null && ifMatch==null else payload!=null && key!=null)
        val connection=open(URL(base+path));val operation=coroutineContext
        val expired=AtomicBoolean(false)
        val timeout=watchdog.schedule({expired.set(true);connection.disconnect()},30,TimeUnit.SECONDS)
        val cancellation=launch(Dispatchers.IO,start=CoroutineStart.UNDISPATCHED) {
            try {awaitCancellation()}finally {connection.disconnect()}
        }
        fun alive(){operation.ensureActive();if(expired.get())throw IOException("energy_timeout")}
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
            alive();beforeSend();alive()
            if(payload!=null)connection.outputStream.use {output->output.write(payload);alive()}
            alive();val status=connection.responseCode;alive()
            require(status in 200..599 && status !in 300..399)
            require(connection.getHeaderField("Content-Encoding").let {it==null || it.equals("identity",true)})
            require(connection.contentType?.substringBefore(';')?.trim()?.equals("application/json",true)==true)
            require(connection.getHeaderField("Cache-Control")?.split(',')?.any {it.trim().equals("no-store",true)}==true)
            val maximum=if(status in 200..299)2*1_048_576 else 65_536
            val length=connection.getHeaderField("Content-Length")?.let {
                require(Regex("^[0-9]{1,10}$").matches(it));it.toLong().also {size->require(size<=maximum)}
            }
            val bytes=ByteArrayOutputStream().also {result->
                requireNotNull(if(status>=400)connection.errorStream else connection.inputStream).use {input->
                    val buffer=ByteArray(8192)
                    while(true){alive();val count=input.read(buffer);alive();if(count<0)break
                        require(result.size().toLong()+count<=maximum);result.write(buffer,0,count)}
                }
            }.toByteArray()
            alive();require(bytes.isNotEmpty() && (length==null || length==bytes.size.toLong()))
            EnergyHttpResult(status,bytes,connection.getHeaderField("Retry-After"))
        }finally {timeout.cancel(false);cancellation.cancel();connection.disconnect()}
    }}
    companion object {
        private val watchdog=Executors.newSingleThreadScheduledExecutor {action->Thread(action,"energy-http-timeout").apply {isDaemon=true}}
        private val uuid="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        private fun allowedPath(method:String,path:String):Boolean=when(method) {
            "GET"->path in setOf("/me","/ai/capabilities","/me/energy/state","/me/energy/analyses?limit=100") ||
                Regex("/me/energy/history\\?after_revision=(0|[1-9][0-9]{0,9})&limit=100").matches(path) || Regex("/me/energy/analyses/$uuid").matches(path)
            "PUT"->path=="/me/consents"
            "POST"->path in setOf("/me/energy/analyses","/me/energy/analyses/accept","/me/energy/analyses/reject","/me/energy/revert","/me/energy/affirm")
            else->false
        }
    }
}
