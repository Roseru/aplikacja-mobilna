package pl.roseru.kalorie.catalogupdate

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import pl.roseru.kalorie.core.catalog.CatalogManifest
import pl.roseru.kalorie.core.catalog.CatalogPackageReader
import pl.roseru.kalorie.session.BootstrapHttpProtocol
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.OutputStream
import java.net.URL
import javax.net.ssl.HttpsURLConnection

/** Adapter to the existing device network policy, never another persisted field-mode switch. */
interface CatalogNetworkGate { val allowed:StateFlow<Boolean> }
object ClosedCatalogNetworkGate:CatalogNetworkGate {
    private val closed=MutableStateFlow(false)
    override val allowed:StateFlow<Boolean> = closed
}
class CatalogNetworkBlocked:Exception("catalog_network_blocked")
class CatalogTransferRejected(val code:String):Exception(code)

internal sealed interface CatalogHttpResult {
    class Success(val bytes:ByteArray?=null):CatalogHttpResult
    data object Missing:CatalogHttpResult
    class Retry(val value:String?):CatalogHttpResult
}
internal interface CatalogDownloadGateway {
    suspend fun manifest():CatalogHttpResult
    suspend fun download(manifest:CatalogManifest,target:File,progress:(Long,Long)->Unit):CatalogHttpResult
}

/** Public same-origin GET only: no session, bearer, redirects, cookies or arbitrary manifest URL. */
internal class HttpsCatalogDownloadGateway(base:String,private val gate:CatalogNetworkGate,
    private val open:(URL)->HttpsURLConnection={it.openConnection() as HttpsURLConnection}):CatalogDownloadGateway {
    private val base=BootstrapHttpProtocol.endpoint(base).toString().removeSuffix("/me/bootstrap")
    override suspend fun manifest():CatalogHttpResult {
        val output=ByteArrayOutputStream()
        val result=request(URL("$base/offline-package/manifest"),"application/json",CatalogPackageReader.MAX_MANIFEST,
            30_000,output,null){_,_->}
        return if(result is CatalogHttpResult.Success)CatalogHttpResult.Success(output.toByteArray()) else result
    }
    override suspend fun download(manifest:CatalogManifest,target:File,progress:(Long,Long)->Unit):CatalogHttpResult {
        require(manifest.packageId==CatalogPackageReader.OFFICIAL_ID && manifest.kind=="official")
        require(manifest.path=="base-pl.${manifest.release}.json.gz" && manifest.release>0)
        return target.outputStream().use { output->
            request(URL("$base/offline-package/${manifest.path}"),"application/gzip",manifest.compressedBytes,
                120_000,output,manifest.sha256,progress)
        }
    }
    private suspend fun request(url:URL,type:String,limit:Int,timeout:Long,output:OutputStream,
        hash:String?,progress:(Long,Long)->Unit):CatalogHttpResult = coroutineScope {
        if(!gate.allowed.value)throw CatalogNetworkBlocked()
        require(limit in 1..CatalogPackageReader.MAX_GZIP)
        val connection=open(url)
        // This sibling also disconnects a blocking socket when the user cancels the job.
        val policy=launch(Dispatchers.IO,start=CoroutineStart.UNDISPATCHED) {
            try {gate.allowed.first{!it}} finally {connection.disconnect()}
        }
        try {withContext(Dispatchers.IO) {
            val started=System.nanoTime()
            fun current() {
                ensureActive()
                if(!gate.allowed.value)throw CatalogNetworkBlocked()
                if((System.nanoTime()-started)/1_000_000>=timeout)throw CatalogTransferRejected("catalog_timeout")
            }
            connection.requestMethod="GET";connection.instanceFollowRedirects=false
            connection.useCaches=false;connection.doOutput=false
            connection.connectTimeout=15_000;connection.readTimeout=15_000
            connection.setRequestProperty("Accept",type)
            connection.setRequestProperty("Accept-Encoding","identity")
            connection.setRequestProperty("Cache-Control","no-cache")
            connection.setRequestProperty("Cookie","");connection.setRequestProperty("Cookie2","")
            current()
            val status=connection.responseCode
            current()
            when(status) {
                404->return@withContext CatalogHttpResult.Missing
                429,503->return@withContext CatalogHttpResult.Retry(connection.getHeaderField("Retry-After"))
                200->Unit
                else->throw CatalogTransferRejected("catalog_http")
            }
            val media=connection.contentType?.substringBefore(';')?.trim()?.lowercase()
            if(media!=type)throw CatalogTransferRejected("catalog_content_type")
            val encoding=connection.getHeaderField("Content-Encoding")?.trim()
            if(encoding!=null && !encoding.equals("identity",true))throw CatalogTransferRejected("catalog_content_encoding")
            val length=connection.contentLengthLong
            if(length==0L || length>limit || (hash!=null && length>=0 && length!=limit.toLong()))
                throw CatalogTransferRejected("catalog_size")
            val etag=connection.getHeaderField("ETag")
            if(hash!=null && etag!=null && etag!="\"$hash\"")throw CatalogTransferRejected("catalog_etag")
            var received=0L;progress(0,limit.toLong())
            connection.inputStream.use { input->
                val buffer=ByteArray(8192)
                while(true) {
                    current()
                    val count=input.read(buffer,0,minOf(buffer.size.toLong(),limit-received+1).toInt())
                    current()
                    if(count<0)break
                    if(count==0 || received+count>limit)throw CatalogTransferRejected("catalog_size")
                    output.write(buffer,0,count);received+=count;progress(received,limit.toLong())
                }
            }
            if(hash!=null && received!=limit.toLong())throw CatalogTransferRejected("compressed_size")
            if(length>=0 && received!=length)throw CatalogTransferRejected("catalog_size")
            CatalogHttpResult.Success()
        }} finally {policy.cancel();connection.disconnect()}
    }
}
