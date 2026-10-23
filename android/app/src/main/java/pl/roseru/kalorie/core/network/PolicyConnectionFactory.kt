package pl.roseru.kalorie.core.network

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import java.io.InputStream
import java.io.OutputStream
import java.net.URL
import java.security.Principal
import java.security.cert.Certificate
import java.util.concurrent.atomic.AtomicBoolean
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLSocketFactory

/** A common connection builder for API and AppAuth; leaves platform TLS/hostname validation intact. */
class PolicyConnectionFactory(private val scope:CoroutineScope,private val gate:NetworkAccessGate=ClosedNetworkAccessGate,
    private val openConnection:(URL)->HttpsURLConnection={it.openConnection() as HttpsURLConnection}) {
    fun open(url:URL):HttpsURLConnection {
        require(url.protocol=="https" && url.userInfo==null && url.ref==null)
        val permit=gate.captureAllowed()
        val connection=openConnection(url)
        try {
            gate.requireCurrent(permit)
            connection.instanceFollowRedirects=false
            return PolicyConnection(connection,permit)
        }catch(error:Exception){connection.disconnect();throw error}
    }
    private inner class PolicyConnection(private val delegate:HttpsURLConnection,private val permit:NetworkPermit):HttpsURLConnection(delegate.url) {
        private val closed=AtomicBoolean(false)
        private var watcher:Job?=null
        init {
            val observing=scope.launch(Dispatchers.IO,start=CoroutineStart.UNDISPATCHED) {
                try {
                    gate.state.first {try{gate.requireCurrent(permit);false}catch(_:NetworkAccessDenied){true}}
                } finally {closeDelegate()}
            }
            watcher=observing
            if(closed.get())observing.cancel()
        }
        private fun current() {
            if(closed.get())throw NetworkAccessDenied(NetworkDenial.STALE_PERMIT)
            gate.requireCurrent(permit)
        }
        private fun <T> io(action:()->T):T {
            current()
            val result=action()
            connected=true
            current()
            return result
        }
        private fun closeDelegate() {
            if(closed.compareAndSet(false,true))try{delegate.disconnect()}catch(_:Exception){}
        }
        private fun input(value:InputStream)=object:InputStream() {
            override fun read():Int=io{value.read()}
            override fun read(bytes:ByteArray,offset:Int,length:Int):Int=io{value.read(bytes,offset,length)}
            override fun skip(count:Long):Long=io{value.skip(count)}
            override fun available():Int=io{value.available()}
            override fun close(){value.close()}
        }
        override fun getInputStream():InputStream=input(io{delegate.inputStream})
        override fun getErrorStream():InputStream?=io{delegate.errorStream}?.let(::input)
        override fun getOutputStream():OutputStream {
            val output=io{delegate.outputStream}
            return object:OutputStream() {
                override fun write(value:Int){io{output.write(value)}}
                override fun write(bytes:ByteArray,offset:Int,length:Int){io{output.write(bytes,offset,length)}}
                override fun flush(){io{output.flush()}}
                override fun close(){
                    try{io{output.close()}}
                    catch(error:NetworkAccessDenied){closeDelegate();throw error}
                }
            }
        }
        override fun connect(){io{delegate.connect()}}
        override fun disconnect(){closeDelegate();watcher?.cancel()}
        override fun usingProxy():Boolean=delegate.usingProxy()
        override fun getResponseCode():Int=io{delegate.responseCode}
        override fun getResponseMessage():String?=io{delegate.responseMessage}
        override fun getHeaderField(name:String?):String?=io{delegate.getHeaderField(name)}
        override fun getHeaderField(index:Int):String?=io{delegate.getHeaderField(index)}
        override fun getHeaderFieldKey(index:Int):String?=io{delegate.getHeaderFieldKey(index)}
        override fun getHeaderFields():Map<String,List<String>> = io{delegate.headerFields}
        override fun getContentLength():Int=io{delegate.contentLength}
        override fun getContentLengthLong():Long=io{delegate.contentLengthLong}
        override fun getContentType():String?=io{delegate.contentType}
        override fun getContentEncoding():String?=io{delegate.contentEncoding}
        override fun setRequestMethod(method:String){delegate.requestMethod=method}
        override fun getRequestMethod():String=delegate.requestMethod
        override fun setInstanceFollowRedirects(follow:Boolean){require(!follow);delegate.instanceFollowRedirects=false}
        override fun getInstanceFollowRedirects():Boolean=delegate.instanceFollowRedirects
        override fun setConnectTimeout(value:Int){delegate.connectTimeout=value}
        override fun getConnectTimeout():Int=delegate.connectTimeout
        override fun setReadTimeout(value:Int){delegate.readTimeout=value}
        override fun getReadTimeout():Int=delegate.readTimeout
        override fun setDoInput(value:Boolean){delegate.doInput=value}
        override fun getDoInput():Boolean=delegate.doInput
        override fun setDoOutput(value:Boolean){delegate.doOutput=value}
        override fun getDoOutput():Boolean=delegate.doOutput
        override fun setUseCaches(value:Boolean){delegate.useCaches=value}
        override fun getUseCaches():Boolean=delegate.useCaches
        override fun setDefaultUseCaches(value:Boolean){delegate.defaultUseCaches=value}
        override fun getDefaultUseCaches():Boolean=delegate.defaultUseCaches
        override fun setAllowUserInteraction(value:Boolean){delegate.allowUserInteraction=value}
        override fun getAllowUserInteraction():Boolean=delegate.allowUserInteraction
        override fun setIfModifiedSince(value:Long){delegate.ifModifiedSince=value}
        override fun getIfModifiedSince():Long=delegate.ifModifiedSince
        override fun setFixedLengthStreamingMode(value:Int){delegate.setFixedLengthStreamingMode(value)}
        override fun setFixedLengthStreamingMode(value:Long){delegate.setFixedLengthStreamingMode(value)}
        override fun setChunkedStreamingMode(value:Int){delegate.setChunkedStreamingMode(value)}
        override fun setRequestProperty(name:String,value:String){delegate.setRequestProperty(name,value)}
        override fun addRequestProperty(name:String,value:String){delegate.addRequestProperty(name,value)}
        override fun getRequestProperty(name:String):String?=delegate.getRequestProperty(name)
        override fun getRequestProperties():Map<String,List<String>> = delegate.requestProperties
        override fun getCipherSuite():String=io{delegate.cipherSuite}
        override fun getLocalCertificates():Array<Certificate>?=io{delegate.localCertificates}
        override fun getServerCertificates():Array<Certificate> = io{delegate.serverCertificates}
        override fun getPeerPrincipal():Principal=io{delegate.peerPrincipal}
        override fun getLocalPrincipal():Principal?=io{delegate.localPrincipal}
        override fun setHostnameVerifier(value:HostnameVerifier){delegate.hostnameVerifier=value}
        override fun getHostnameVerifier():HostnameVerifier=delegate.hostnameVerifier
        override fun setSSLSocketFactory(value:SSLSocketFactory){delegate.sslSocketFactory=value}
        override fun getSSLSocketFactory():SSLSocketFactory=delegate.sslSocketFactory
        override fun toString()="PolicyConnection(redacted)"
    }
}
