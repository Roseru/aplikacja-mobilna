package pl.roseru.kalorie

import android.content.Context
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.MutableStateFlow
import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.SessionIdentity
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.energy.*
import pl.roseru.kalorie.session.*
import java.io.IOException
import java.time.Instant
import java.util.UUID

/** Synthetic API and authenticated-session boundary; the repository, Room and owner fences are real. */
internal object EnergyFixture {
    val context:Context get()=InstrumentationRegistry.getInstrumentation().targetContext
    val instant:Instant=Instant.parse("2026-10-24T10:00:00Z")
    fun bytes(name:String)=InstrumentationRegistry.getInstrumentation().context.assets.open("energy-$name.json").use {it.readBytes()}
    fun sample(name:String)=StrictJson.read(bytes(name))
    fun protocol()=EnergyProtocol(EnergySchema(context.assets.open("energy/energy.schema.json").use {it.readBytes()}))
    fun database(name:String)=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
    suspend fun account(db:CalorieDatabase,subject:String="A"):EnergyScope {
        val owners=LocalOwnerStore(db);val lease=owners.select(owners.registerIdentity("https://energy.fixture/realm",subject).id)
        if(db.bootstrapDao().binding(lease.storageScope)==null)db.bootstrapDao().insert(AccountBindingEntity(lease.storageScope,
            if(subject=="A")sample("profile").getString("account_id")else UUID.randomUUID().toString(),1,
            sample("state").getString("sync_epoch"),"2026-10-24T09:00:00Z",1,false))
        return checkNotNull(EnergyStore(db).scope(lease))
    }
    class Gate:ObservableNetworkAccessGate() {init {publish(NetworkAccessState.Allowed(1))};fun block(){publish(NetworkAccessState.Blocked)}}
    class Sessions(private val db:CalorieDatabase,scope:EnergyScope):EnergySessionAccess {
        override val view=MutableStateFlow(SessionView(binding=SessionBinding(checkNotNull(runBlockingOwner(scope)),scope.lease),hasSession=true,serverLinked=true))
        // Construction happens on a test worker, never on the Android main thread.
        private fun runBlockingOwner(scope:EnergyScope)=kotlinx.coroutines.runBlocking {db.ownerDao().byScope(scope.lease.storageScope)}
        override suspend fun session(scope:EnergyScope,forceRefresh:Boolean):ApiSession {
            EnergyStore(db).requireScope(scope)
            val owner=checkNotNull(db.ownerDao().byScope(scope.lease.storageScope))
            return ApiSession(SessionIdentity(checkNotNull(owner.issuer),checkNotNull(owner.subject)),scope.lease,"synthetic-access","{}",1)
        }
        override suspend fun <T> withSession(ticket:ApiSession,scope:EnergyScope,block:suspend ()->T):T {
            require(ticket.lease==scope.lease);EnergyStore(db).requireScope(scope);return block()
        }
        override suspend fun defer(ticket:ApiSession,scope:EnergyScope,until:Long) {withSession(ticket,scope){}}
    }
    class Server(var loseFirstCreate:Boolean=false):EnergyGateway {
        val requests=mutableListOf<Triple<String,String?,String?>>()
        var admissions=0;var afterReply:(suspend ()->Unit)?=null
        private val responses=mutableMapOf<String,Pair<String,ByteArray>>()
        private val state=sample("state");private val profile=sample("profile")
        private val versions=mutableListOf(sample("version"));private var analysis:JSONObject?=null
        override suspend fun request(session:ApiSession,epoch:String,method:String,path:String,body:String?,key:String?,ifMatch:String?,beforeSend:suspend ()->Unit):EnergyHttpResult {
            beforeSend();requests+=Triple(path,key,body)
            val response=if(method=="GET")when {
                path=="/me/energy/state"->state
                path=="/me"->profile
                path=="/ai/capabilities"->sample("capabilities")
                path=="/me/energy/analyses?limit=100"->JSONObject().put("items",JSONArray().also {rows->analysis?.let {rows.put(it)}})
                path.startsWith("/me/energy/history?")->{
                    val after=path.substringAfter("after_revision=").substringBefore('&').toInt()
                    val items=versions.filter {it.getInt("revision")>after}.take(100)
                    JSONObject().put("items",JSONArray(items)).put("next_revision",items.lastOrNull()?.getInt("revision")?:after)
                }
                path.startsWith("/me/energy/analyses/")->checkNotNull(analysis)
                else->error("Unexpected GET path")
            }else {
                val id=checkNotNull(key);val sent=checkNotNull(body)
                responses[id]?.let {saved->check(saved.first==sent);afterReply?.invoke();return EnergyHttpResult(200,saved.second,null)}
                val value=when(path) {
                    "/me/energy/analyses"->{admissions++;sample("analysis").also {analysis=it}}
                    "/me/energy/analyses/accept"->{
                        val input=StrictJson.read(sent.toByteArray());check(input.getInt("axis_revision")==3)
                        val next=sample("version").put("entity_id","66666666-6666-4666-8666-666666666666").put("revision",4)
                        next.getJSONObject("payload").put("maintenance_kcal","3100").put("effective_from","2026-10-25")
                            .put("method","energy_adjustment_v1").put("source","manual").put("source_id",input.getString("id"))
                            .put("supersedes",state.getString("current_id")).put("decided_at",instant.toString())
                            .put("audit",JSONObject().put("analysis_id",input.getString("id")).put("rules",checkNotNull(analysis).getJSONObject("result"))
                                .put("explanation",checkNotNull(analysis).getJSONObject("explanation")).put("decider","owner"))
                        versions+=next;state.put("axis_revision",4).put("baseline_id",next.getString("entity_id"))
                            .put("last_applied_at",instant.toString()).put("next_apply_at",instant.plusSeconds(336*3600L).toString())
                        analysis=checkNotNull(analysis).put("state","accepted").put("revision",3)
                        next
                    }
                    else->error("Unexpected mutation path")
                }
                val bytes=StrictJson.canonical(value).toByteArray();responses[id]=sent to bytes
                if(path=="/me/energy/analyses" && loseFirstCreate){loseFirstCreate=false;throw IOException("Synthetic lost response after admission")}
                value
            }
            afterReply?.invoke()
            return EnergyHttpResult(200,StrictJson.canonical(response).toByteArray(),null)
        }
    }
    fun repository(db:CalorieDatabase,scope:EnergyScope,server:Server)=EnergyRepository(EnergyStore(db),protocol(),Sessions(db,scope),Gate(),server){instant.toEpochMilli()}
}
