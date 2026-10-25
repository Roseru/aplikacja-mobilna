package pl.roseru.kalorie

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.community.*
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.net.URL
import java.security.Principal
import java.security.cert.Certificate
import java.time.LocalDate
import java.util.UUID
import javax.net.ssl.HttpsURLConnection

/** Real Room/diary/transport; synthetic accounts and sockets, no external API or TLS acceptance. */
class CommunityWorkflowTest {
    private val instrumentation=InstrumentationRegistry.getInstrumentation()
    private val context=instrumentation.targetContext
    private fun uuid()=UUID.randomUUID().toString()
    private fun sample()=instrumentation.context.assets.open("community-product.json").use {StrictJson.read(it.readBytes())}
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase,subject:String):CommunityScope {
        val owners=LocalOwnerStore(db)
        val lease=owners.select(owners.registerIdentity("https://community.fixture/realm",subject).id)
        if(db.bootstrapDao().binding(lease.storageScope)==null)db.bootstrapDao().insert(
            AccountBindingEntity(lease.storageScope,uuid(),1,uuid(),"2026-10-24T09:00:00Z",1,false))
        return checkNotNull(CommunityStore(db).scope(lease))
    }

    @Test fun cachedMergedRevisionAddsExactOfflineMealWithoutSharingAccountState()=runBlocking<Unit> {
        val db=memory()
        try {
            val store=CommunityStore(db);val first=account(db,"synthetic-A")
            val raw=sample().put("canonical_ref",PublicProductRef(uuid(),7).json())
                .put("density",JSONObject().put("amount","1.1").put("source_description","Syntetyczna etykieta gęstości"))
            val product=CommunityProtocol.product(raw)
            store.cache(first,listOf(product),100)
            val copy=store.cached(first,"rosol").single()
            val mealId=uuid()
            // An external edit to a returned JSONObject cannot mutate the stored snapshot.
            copy.json().getJSONObject("nutrition_per_100").put("energy_kcal","999")
            DiaryRepository(db,context,first.lease).addCommunity(first,copy,"100","ml",MealType.LUNCH,
                LocalDate.of(2026,10,24),mealId)
            val meal=checkNotNull(db.dao().meal(mealId,first.lease.storageScope))
            val item=meal.items.single();val wire=StrictJson.read(checkNotNull(item.wirePayload).toByteArray())
            assertEquals(product.ref.id,wire.getJSONObject("product").getString("product_id"))
            assertEquals(1,wire.getJSONObject("product").getInt("revision"))
            assertEquals("220",item.consumed().asExact().energy.canonical)
            assertFalse(item.consumed().asExact().carbs.complete)
            assertEquals("Syntetyczna etykieta gęstości",wire.getString("density_source"))
            assertEquals("catalog_snapshot",wire.getString("nutrition_origin"))
            assertNotNull(item.snapshotJson)
            assertEquals(1,db.dao().operationCount(first.lease.storageScope))
            val second=account(db,"synthetic-B")
            assertTrue(store.cached(second).isEmpty())
            assertTrue(runCatching {store.cached(first)}.isFailure)
            val restored=account(db,"synthetic-A")
            assertNotEquals(first.lease,restored.lease)
            assertEquals(product.ref,store.cached(restored).single().ref)
            assertNotNull(db.dao().meal(mealId,restored.lease.storageScope))
            val invalid=sample().put("complete",true)
            assertTrue(runCatching {CommunityProtocol.product(invalid)}.isFailure)
        }finally{db.close()}
    }

    @Test fun unknownWriteSurvivesDatabaseReopenAndCannotMoveToANewEpoch()=runBlocking<Unit> {
        val name="community-pending-${uuid()}"
        var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        try {
            val scope=account(db,"synthetic-pending");val store=CommunityStore(db)
            val body=CommunityProtocol.reportBody(CommunityProtocol.product(sample()).ref,"Syntetyczny powód","Syntetyczny opis")
            val row=store.prepare(scope,"report:fixture","report","POST","/products/${CommunityProtocol.product(sample()).ref.id}/reports",body,null,100)
            store.attempted(scope,row);store.defer(scope,123456789)
            db.close()
            db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
            val reopened=CommunityStore(db);val newScope=account(db,"synthetic-pending")
            val retained=reopened.open(newScope,row.id)
            assertTrue(retained.attempted);assertEquals("unknown",retained.state)
            assertEquals(row.body,retained.body);assertEquals(row.fingerprint,retained.fingerprint)
            assertEquals(123456789L,reopened.retryAt(newScope))
            assertTrue(runCatching {reopened.discardUnsent(newScope,row.id)}.isFailure)
            assertTrue(runCatching {reopened.prepare(newScope,row.resource,row.kind,row.method,row.path,row.body,row.ifMatch,101)}.isFailure)
            db.bootstrapDao().update(newScope.binding.copy(syncEpoch=uuid(),contextRevision=2))
            val changed=checkNotNull(reopened.scope(newScope.lease))
            assertTrue(runCatching {reopened.open(changed,row.id)}.isFailure)
            assertEquals(row.id,reopened.attempts(changed).single().id)
            assertEquals(retained,db.communityDao().attempt(row.id))
        }finally{db.close();context.deleteDatabase(name)}
    }

    @Test fun physicalAdapterUsesPublicApiPathsAndFrozenKeyBodyHeadersWithoutRedirects()=runBlocking<Unit> {
        val db=memory();val transportScope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
        try {
            val scope=account(db,"synthetic-http")
            val gate=object:ObservableNetworkAccessGate(){fun allow()=publish(NetworkAccessState.Allowed(1));fun block()=publish(NetworkAccessState.Blocked)}
            gate.allow()
            val calls=mutableListOf<Socket>()
            val factory=PolicyConnectionFactory(transportScope,gate) {url->Socket(url).also {calls+=it}}
            val client=HttpsCommunityGateway("https://community.fixture/api/v1",factory::open)
            val ticket=ApiSession(SessionIdentity("https://community.fixture/realm","synthetic-http"),scope.lease,"synthetic-access","synthetic-state",1)
            val key=uuid();val body="{\"value\":1}";val path="/products/${uuid()}/vote"
            repeat(2) {
                val response=client.request(ticket,scope.binding.syncEpoch,"PUT",path,body,key,"\"0\""){}
                assertEquals(200,response.status)
            }
            assertEquals(2,calls.size)
            calls.forEach {
                assertEquals("PUT",it.requestMethod);assertEquals(key,it.getRequestProperty("Idempotency-Key"))
                assertEquals(scope.binding.syncEpoch,it.getRequestProperty("X-Sync-Epoch"))
                assertEquals("\"0\"",it.getRequestProperty("If-Match"));assertEquals(body,it.sent.toString("UTF-8"))
                assertEquals("Bearer synthetic-access",it.getRequestProperty("Authorization"))
                assertFalse(it.instanceFollowRedirects);assertFalse(it.useCaches)
            }
            client.request(ticket,scope.binding.syncEpoch,"DELETE",path,null,uuid(),"\"1\""){}
            assertFalse(calls.last().doOutput);assertEquals(0,calls.last().sent.size())
            gate.block()
            assertTrue(runCatching {client.request(ticket,scope.binding.syncEpoch,"GET","/community/products?limit=10") {}}.isFailure)
            assertEquals(3,calls.size)
        }finally{transportScope.cancel();db.close()}
    }
    private class Socket(url:URL):HttpsURLConnection(url) {
        val sent=ByteArrayOutputStream()
        private val reply="{\"revision\":1,\"value\":1}".toByteArray()
        override fun connect(){}
        override fun disconnect(){}
        override fun usingProxy()=false
        override fun getResponseCode()=200
        override fun getOutputStream()=sent
        override fun getInputStream()=ByteArrayInputStream(reply)
        override fun getHeaderField(name:String):String?=when(name.lowercase()){"content-type"->"application/json";"content-length"->reply.size.toString();"cache-control"->"no-store";else->null}
        override fun getContentType()="application/json"
        override fun getCipherSuite()="SYNTHETIC"
        override fun getLocalCertificates():Array<Certificate>?=null
        override fun getServerCertificates():Array<Certificate> = emptyArray()
        override fun getPeerPrincipal():Principal=Principal {"synthetic"}
        override fun getLocalPrincipal():Principal?=null
    }

    @Test fun actualRoom22MigrationPreservesAllOldRowsAndAddsOnlyEmptyCommunityTables()=runBlocking<Unit> {
        val sourceName="community-source-${uuid()}";val oldName="community-room22-${uuid()}"
        val source=Room.databaseBuilder(context,CalorieDatabase::class.java,sourceName).addCallback(DATABASE_GUARDS).build()
        var migrated:CalorieDatabase?=null
        try {
            val owners=LocalOwnerStore(source);val guest=owners.currentLease()
            val repo=DiaryRepository(source,context,guest)
            repo.setProfile("Syntetyczny profil",180.125,ActivityClass.LINE,DietAim.MAINTAIN)
            repo.setGoal(2500.125,null,0.0,null)
            repo.addCustomProduct(CustomProductDraft("Syntetyczny produkt",321.125,null,0.0,12.5,"Źródło testowe"),
                75.123456789012,MealType.LUNCH,LocalDate.of(2026,10,24))
            repo.addWeight(81.123456789,LocalDate.of(2026,10,24))
            val schema=instrumentation.context.assets.open("pl.roseru.kalorie.data.CalorieDatabase/22.json").use {StrictJson.read(it.readBytes()).getJSONObject("database")}
            val entities=schema.getJSONArray("entities")
            fun dump(query:(String)->Cursor)=buildMap<String,List<List<String?>>>{for(i in 0 until entities.length()) {
                val name=entities.getJSONObject(i).getString("tableName")
                put(name,query("SELECT rowid,* FROM `$name` ORDER BY rowid").use {cursor->buildList {
                    while(cursor.moveToNext())add(legacySnapshotColumns(cursor).map {column->if(cursor.isNull(column))null else cursor.getString(column)})
                }})
            }}
            val before=dump {source.openHelper.readableDatabase.query(it)}
            context.getDatabasePath(oldName).parentFile!!.mkdirs()
            SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(oldName),null).use {old ->
                old.execSQL("PRAGMA foreign_keys=OFF")
                old.execSQL("ATTACH DATABASE ? AS origin",arrayOf(context.getDatabasePath(sourceName).absolutePath))
                for(i in 0 until entities.length()) {
                    val entity=entities.getJSONObject(i);val table=entity.getString("tableName")
                    old.execSQL(entity.getString("createSql").replace("\${TABLE_NAME}",table))
                    val indices=entity.optJSONArray("indices")?:JSONArray()
                    for(j in 0 until indices.length())old.execSQL(indices.getJSONObject(j).getString("createSql").replace("\${TABLE_NAME}",table))
                    val fields=entity.getJSONArray("fields")
                    val columns="rowid,"+(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                    old.execSQL("INSERT INTO `$table` ($columns) SELECT $columns FROM origin.`$table`")
                }
                old.execSQL("DETACH DATABASE origin")
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(schema.getString("identityHash")))
                old.version=22
            }
            migrated=Room.databaseBuilder(context,CalorieDatabase::class.java,oldName).addMigrations(MIGRATION_22_23, pl.roseru.kalorie.data.MIGRATION_23_24, pl.roseru.kalorie.energy.MIGRATION_24_25, pl.roseru.kalorie.data.MIGRATION_25_26).addCallback(DATABASE_GUARDS).build()
            val sql=migrated.openHelper.readableDatabase
            assertEquals(26,sql.version);assertEquals(before,dump {sql.query(it)})
            assertFalse(sql.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
            listOf("community_cache","community_attempts","community_backoff").forEach {table ->
                assertEquals(0,sql.query("SELECT count(*) FROM $table").use {it.moveToFirst();it.getInt(0)})
            }
        }finally{migrated?.close();source.close();context.deleteDatabase(sourceName);context.deleteDatabase(oldName)}
    }
}
