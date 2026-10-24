package pl.roseru.kalorie

import android.content.Context
import android.net.Uri
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.*
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import net.openid.appauth.AuthorizationServiceConfiguration
import net.openid.appauth.TokenRequest
import net.openid.appauth.connectivity.ConnectionBuilder
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.session.AppAuthGateway
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.URL
import java.security.cert.Certificate
import java.util.Collections
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import javax.net.ssl.HttpsURLConnection

@RunWith(AndroidJUnit4::class)
class NetworkPolicyStorageTest {
    private suspend fun denied(action:suspend()->Unit):NetworkAccessDenied {
        try{action()}catch(error:NetworkAccessDenied){return error}
        throw AssertionError("Expected network denial")
    }
    private class FaultStore:DataStore<Preferences> {
        val values=MutableStateFlow<Preferences>(emptyPreferences())
        override val data:Flow<Preferences> = values
        var rejectWrite=false
        override suspend fun updateData(transform:suspend(Preferences)->Preferences):Preferences {
            if(rejectWrite)throw IOException("Synthetic preference write failure")
            return transform(values.value).also{values.value=it}
        }
    }
    @Test fun policyFailsClosedAndPersistsBlockWithRevisionAndProviderFencesAcrossRestart()=runBlocking<Unit> {
        val errorScope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
        try {
            val failing=FaultStore();val policy=DeviceNetworkPolicy(failing,errorScope)
            withTimeout(10_000){policy.state.first{it is NetworkAccessState.Allowed}}
            val old=policy.captureAllowed();failing.rejectWrite=true
            try{policy.setBlocked(true);fail("Expected preference failure")}catch(_:IOException){}
            assertEquals(NetworkAccessState.Unavailable,policy.state.value)
            denied{policy.captureAllowed()};denied{policy.requireCurrent(old)}
            failing.rejectWrite=false;policy.setBlocked(false)
            assertTrue((policy.state.value as NetworkAccessState.Allowed).revision>old.revision)
            denied{policy.requireCurrent(old)}
            policy.requireCurrent(policy.captureAllowed())
        }finally{errorScope.coroutineContext.job.cancelAndJoin()}

        val context=ApplicationProvider.getApplicationContext<Context>()
        val folder=File(context.cacheDir,"network-policy-test-${UUID.randomUUID()}").apply{mkdirs()}
        val file=File(folder,"device.preferences_pb")
        val scopes=mutableListOf<CoroutineScope>()
        fun fresh():Pair<DeviceNetworkPolicy,CoroutineScope> {
            val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO);scopes+=scope
            val store=PreferenceDataStoreFactory.create(scope=scope,produceFile={file})
            return DeviceNetworkPolicy(store,scope) to scope
        }
        try {
            val (first,firstScope)=fresh()
            withTimeout(10_000){first.state.first{it is NetworkAccessState.Allowed}}
            val original=first.captureAllowed()
            first.setBlocked(true);assertEquals(NetworkAccessState.Blocked,first.state.value)
            denied{first.requireCurrent(original)}
            first.setBlocked(false)
            val reopened=first.captureAllowed();assertTrue(reopened.revision>original.revision)
            denied{first.requireCurrent(original)}
            firstScope.coroutineContext.job.cancelAndJoin()
            val (second,secondScope)=fresh()
            withTimeout(10_000){second.state.first{it is NetworkAccessState.Allowed}}
            assertEquals(reopened.revision,(second.state.value as NetworkAccessState.Allowed).revision)
            denied{second.requireCurrent(reopened)}
            second.setBlocked(true);secondScope.coroutineContext.job.cancelAndJoin()
            val (third,_)=fresh()
            withTimeout(10_000){third.state.first{it==NetworkAccessState.Blocked}}
            denied{third.captureAllowed()}
        }finally{scopes.forEach{it.coroutineContext.job.cancelAndJoin()};folder.deleteRecursively()}
    }

    private class Connection(url:URL,private val hold:Boolean):HttpsURLConnection(url) {
        val entered=CountDownLatch(1);val released=CountDownLatch(1)
        val disconnects=AtomicInteger();val outputCloses=AtomicInteger();val outputOpens=AtomicInteger();val inputCloses=AtomicInteger()
        override fun disconnect(){disconnects.incrementAndGet();released.countDown()}
        override fun usingProxy()=false
        override fun connect(){}
        override fun getCipherSuite()="SYNTHETIC"
        override fun getLocalCertificates():Array<Certificate>?=null
        override fun getServerCertificates():Array<Certificate> = emptyArray()
        override fun getInputStream():InputStream {
            if(!hold)return object:ByteArrayInputStream("ok".toByteArray()) {
                override fun close(){inputCloses.incrementAndGet();super.close()}
            }
            return object:InputStream() {
                override fun read():Int {
                    entered.countDown()
                    check(released.await(10,TimeUnit.SECONDS))
                    throw IOException("Synthetic disconnected read")
                }
            }
        }
        override fun getOutputStream():OutputStream {
            outputOpens.incrementAndGet()
            return object:ByteArrayOutputStream(){override fun close(){outputCloses.incrementAndGet();super.close()}}
        }
    }
    @Test fun connectionBuilderClosesHeldReadAndCannotFlushOrReviveAnOldPermitAfterAba()=runBlocking<Unit> {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
        val gate=CatalogUpdateFixtures.Gate().apply{allow()}
        val connections=Collections.synchronizedList(mutableListOf<Connection>())
        val url=URL("https://fixture.invalid/api/v1/offline-package/manifest")
        val factory=PolicyConnectionFactory(scope,gate){address->Connection(address,connections.isEmpty()).also{connections+=it}}
        try {
            denied{PolicyConnectionFactory(scope).open(url)}
            val old=factory.open(url);val first=connections.single()
            assertSame(first.hostnameVerifier,old.hostnameVerifier)
            assertSame(first.sslSocketFactory,old.sslSocketFactory)
            val reading=async(Dispatchers.IO){runCatching{old.inputStream.read()}}
            assertTrue(withContext(Dispatchers.IO){first.entered.await(10,TimeUnit.SECONDS)})
            gate.block();gate.allow(2)
            val result=withTimeout(10_000){reading.await()}
            assertTrue(result.isFailure)
            assertEquals(1,first.disconnects.get())
            denied{old.outputStream.write(1)}
            assertEquals(0,first.outputOpens.get())
            val replacement=factory.open(url)
            assertEquals('o'.code,replacement.inputStream.read());replacement.disconnect()
            val pending=factory.open(url);pending.doOutput=true
            val output=pending.outputStream;output.write("synthetic".toByteArray())
            val third=connections.last()
            gate.block();gate.allow(3)
            denied{output.close()}
            assertEquals(0,third.outputCloses.get())
            pending.disconnect();old.disconnect()
            val response=factory.open(url);val input=response.inputStream
            val fourth=connections.last()
            gate.block();gate.allow(4)
            denied{input.close()}
            assertEquals(0,fourth.inputCloses.get())
            assertEquals(1,fourth.disconnects.get())
            response.disconnect()
            // AppAuth catches IOException on its background thread. A policy race must reach
            // its callback normally instead of escaping as an unchecked AsyncTask failure.
            val authGate=CatalogUpdateFixtures.Gate().apply{allow()}
            val builder=ConnectionBuilder { uri->
                authGate.block()
                PolicyConnectionFactory(scope,authGate).open(URL(uri.toString()))
            }
            val context=ApplicationProvider.getApplicationContext<Context>()
            val auth=AppAuthGateway(context,builder,authGate)
            val configuration=AuthorizationServiceConfiguration(Uri.parse("https://fixture.invalid/auth"),Uri.parse("https://fixture.invalid/token"))
            val request=TokenRequest.Builder(configuration,"synthetic-public-client").setGrantType("refresh_token")
                .setRefreshToken("synthetic-never-sent").build()
            withTimeout(10_000){denied{auth.tokens(request)}}
        }finally{scope.coroutineContext.job.cancelAndJoin()}
    }
}
