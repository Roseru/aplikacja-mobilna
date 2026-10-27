package pl.roseru.kalorie

import androidx.room.Room
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.energy.*
import pl.roseru.kalorie.session.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.net.URL
import java.security.cert.Certificate
import javax.net.ssl.HttpsURLConnection
import java.time.LocalDate
import java.util.UUID

/** Real Room/owner/projection boundaries with synthetic server copies; no live API/AI claim. */
class EnergySyncWorkflowTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val energy get()=EnergySchema(context.assets.open("energy/energy.schema.json").use {it.readBytes()})
    private val protocol get()=SnapshotProtocol(schema,energy)
    private val epoch="11111111-1111-4111-8111-111111111111"
    private val weightId="99999999-9999-4999-8999-999999999999"
    private fun open(name:String)=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);val lease=owners.select(owners.registerIdentity("https://sync.fixture/realm","A").id)
        val bootstrap=AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease),BootstrapResponse("44444444-4444-4444-8444-444444444444",epoch,1,"2026-10-24T09:00:00Z"))
        return lease
    }
    private fun weight(revision:Int,kg:String)=JSONObject().put("entity_type","weight").put("entity_id",weightId).put("revision",revision)
        .put("deleted",false).put("payload",JSONObject().put("weight_kg",kg).put("occurred_at","2026-10-24T09:00:00Z")
            .put("time_zone","UTC").put("local_date","2026-10-24"))
    private fun page(rows:List<JSONObject>,checkpoint:String="energy-checkpoint",next:String?=null,mode:String="snapshot",timeline:Int=0)=
        StrictJson.canonical(JSONObject().put("sync_epoch",epoch).put("mode",mode)
            .put("snapshot_token",if(mode=="snapshot")"snapshot-$checkpoint"else JSONObject.NULL)
            .put("page_token",next?:JSONObject.NULL).put("checkpoint",if(next==null)checkpoint else JSONObject.NULL)
            .put("server_time","2026-10-24T10:00:00Z").put("goal_timeline_revision",timeline).put("entities",JSONArray(rows))
            .put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())).toByteArray(Charsets.UTF_8)
    private suspend fun rejected(block:suspend ()->Unit) {
        var refused=false
        try {block()}catch(error:kotlinx.coroutines.CancellationException){throw error}catch(_:Exception){refused=true}
        assertTrue("Expected rejection without private diagnostic data",refused)
    }
    private suspend fun full(db:CalorieDatabase,lease:OwnerLease):String {
        val binding=checkNotNull(db.bootstrapDao().binding(lease.storageScope))
        assertEquals(SyncProtocolScope.ENERGY_V1,SyncProtocolStore(db).readScope(lease,binding,true))
        val store=ServerSnapshotStore(db,protocol);val first=store.beginRead(lease,SyncProtocolScope.ENERGY_V1)
        store.apply(first,page(listOf(weight(1,"80"),EnergyFixture.sample("version"))))
        ServerDiaryStore(db,schema,energy).apply(lease,first.runId)
        return first.runId
    }
    @Test fun legacyFrozenRequestDrainsThenSevenDomainsCommitTogetherAndDeltaPreservesLaterLocalEdit()=runBlocking<Unit> {
        val name="energy-sync-${UUID.randomUUID()}";var db=open(name)
        try {
            val lease=account(db);var snapshots=ServerSnapshotStore(db,protocol)
            val absentId="77777777-7777-4777-8777-777777777777"
            val auxiliary=weight(1,"79").put("entity_id",absentId)
            val legacy=snapshots.begin(lease);snapshots.apply(legacy,page(listOf(weight(1,"80"),auxiliary),"legacy-checkpoint"))
            ServerDiaryStore(db,schema,energy).apply(lease,legacy.runId)
            val diary=DiaryRepository(db,context,lease)
            diary.setGoal(2500.0,150.0,null,300.0)
            diary.addWeight(81.0,LocalDate.of(2026,10,24))
            var push=MealPushStore(db,schema);val old=checkNotNull(push.prepare(lease));push.markAttempted(old)
            val frozen=checkNotNull(db.pushDao().batch(old.id));val binding=checkNotNull(db.bootstrapDao().binding(lease.storageScope))
            assertEquals(SyncProtocolScope.LEGACY,SyncProtocolStore(db).readScope(lease,binding,true))
            db.close();db=open(name);push=MealPushStore(db,schema)
            val resumed=push.open(lease,old.id)
            assertEquals(frozen.requestJson,resumed.row.requestJson);assertEquals(frozen.requestHash,resumed.batch.sha256)
            assertEquals(SyncProtocolScope.LEGACY,resumed.batch.protocolScope)
            val operations=resumed.batch.json().getJSONArray("operations")
            val results=JSONArray()
            for(i in 0 until operations.length()) {
                val op=operations.getJSONObject(i)
                results.put(JSONObject().put("operation_id",op.getString("operation_id")).put("entity_id",op.getString("entity_id"))
                    .put("status","accepted").put("revision",if(op.isNull("base_revision"))1 else op.getInt("base_revision")+1)
                    .put("recovery_mapping",JSONObject.NULL))
            }
            val reply=StrictJson.canonical(JSONObject().put("sync_epoch",epoch).put("server_time","2026-10-24T10:00:00Z").put("results",results))
            push.applyAck(push.prepareAck(resumed,200,reply.toByteArray()))
            val accepted=(0 until operations.length()).map {i->operations.getJSONObject(i)}.map {op->
                JSONObject().put("entity_type",op.getString("entity_type")).put("entity_id",op.getString("entity_id"))
                    .put("revision",1).put("deleted",false).put("payload",op.getJSONObject("payload"))
            }
            assertEquals(SyncProtocolScope.ENERGY_V1,SyncProtocolStore(db).readScope(lease,binding,true))
            snapshots=ServerSnapshotStore(db,protocol)
            val first=snapshots.beginRead(lease,SyncProtocolScope.ENERGY_V1)
            val second=checkNotNull(snapshots.apply(first,page(listOf(EnergyFixture.sample("version")),next="continuation",timeline=1)))
            assertEquals(legacy.runId,snapshots.active(lease)!!.id)
            assertTrue(db.canonicalEnergyDao().all(lease.storageScope,CanonicalMealRows.context(binding)).isEmpty())
            db.close();db=open(name);snapshots=ServerSnapshotStore(db,protocol)
            val again=snapshots.beginRead(lease,SyncProtocolScope.ENERGY_V1)
            assertEquals(second.runId,again.runId);assertEquals(second.query.canonical,again.query.canonical)
            val goal=db.serverDiaryDao().allGoals(lease.storageScope)
            assertNull(snapshots.apply(again,page(listOf(weight(1,"80"))+accepted,timeline=1)))
            assertEquals(legacy.runId,snapshots.active(lease)!!.id)
            assertEquals(first.runId,snapshots.pendingProjection(lease)!!.id)
            ServerDiaryStore(db,schema,energy).apply(lease,first.runId)
            assertEquals(first.runId,snapshots.active(lease)!!.id)
            assertEquals("active",SyncProtocolStore(db).current(lease,binding)!!.phase)
            assertTrue(db.serverDiaryDao().records(lease.storageScope).single {it.entityId==absentId}.absent)
            assertEquals(goal,db.serverDiaryDao().allGoals(lease.storageScope))
            assertEquals(1,EnergyStore(db).cached(checkNotNull(EnergyStore(db).scope(lease))).count {it.kind=="version"})

            DiaryRepository(db,context,lease).editWeight(weightId,83.0)
            val localWeight=db.dao().weight(weightId,lease.storageScope)
            val queue=db.serverDiaryDao().unsettled(lease.storageScope)
            val delta=snapshots.beginRead(lease,SyncProtocolScope.ENERGY_V1)
            assertTrue(delta.query.json().has("checkpoint"))
            val nextVersion=EnergyFixture.sample("version").put("entity_id","88888888-8888-4888-8888-888888888888").put("revision",4)
            nextVersion.getJSONObject("payload").put("supersedes",EnergyFixture.sample("version").getString("entity_id")).put("effective_from","2026-10-25")
            snapshots.apply(delta,page(listOf(weight(2,"81"),weight(3,"82"),nextVersion),"delta-checkpoint",mode="incremental",timeline=1))
            assertEquals(first.runId,snapshots.active(lease)!!.id)
            ServerDiaryStore(db,schema,energy).apply(lease,delta.runId)
            assertEquals(delta.runId,snapshots.active(lease)!!.id)
            assertEquals(localWeight,db.dao().weight(weightId,lease.storageScope))
            assertEquals(queue,db.serverDiaryDao().unsettled(lease.storageScope))
            assertEquals(3,db.serverDiaryDao().records(lease.storageScope).single {it.entityId==weightId}.knownRevision)
            val absent=db.serverDiaryDao().records(lease.storageScope).single {it.entityId==absentId}
            assertTrue(absent.absent);assertEquals(1,absent.knownRevision)
            assertEquals(2,db.canonicalEnergyDao().all(lease.storageScope,CanonicalMealRows.context(binding)).size)
            val preserved=checkNotNull(db.pushDao().batch(old.id))
            assertEquals(frozen.requestJson,preserved.requestJson);assertEquals(frozen.requestHash,preserved.requestHash)
            assertEquals(frozen.protocolScope,preserved.protocolScope)
            assertEquals(goal,db.serverDiaryDao().allGoals(lease.storageScope))
            assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
        }finally {db.close();context.deleteDatabase(name)}
    }
    @Test fun expiredCursorAndRejectedDeltaRequireFreshFullCopyWithoutTouchingQueueOrOldAxis()=runBlocking<Unit> {
        val name="energy-expiry-${UUID.randomUUID()}";val db=open(name)
        try {
            val lease=account(db);val base=full(db,lease);val snapshots=ServerSnapshotStore(db,protocol)
            DiaryRepository(db,context,lease).editWeight(weightId,84.0)
            val before=db.serverDiaryDao().unsettled(lease.storageScope)
            val binding=checkNotNull(db.bootstrapDao().binding(lease.storageScope));val oldAxis=db.canonicalEnergyDao().all(lease.storageScope,CanonicalMealRows.context(binding))
            val expired=snapshots.beginRead(lease,SyncProtocolScope.ENERGY_V1)
            snapshots.expire(expired,fullRequired=true)
            val replacement=snapshots.beginRead(lease,SyncProtocolScope.ENERGY_V1)
            assertFalse(replacement.query.json().has("checkpoint"));assertEquals(base,snapshots.active(lease)!!.id)
            snapshots.apply(replacement,page(listOf(weight(1,"80"),EnergyFixture.sample("version")),"fresh-full"))
            ServerDiaryStore(db,schema,energy).apply(lease,replacement.runId)
            val invalid=snapshots.beginRead(lease,SyncProtocolScope.ENERGY_V1)
            snapshots.apply(invalid,page(listOf(weight(1,"99")),"invalid-delta",mode="incremental"))
            rejected {ServerDiaryStore(db,schema,energy).apply(lease,invalid.runId)}
            assertEquals(replacement.runId,snapshots.active(lease)!!.id)
            assertEquals("expired",db.snapshotDao().run(invalid.runId)!!.state)
            assertFalse(snapshots.beginRead(lease,SyncProtocolScope.ENERGY_V1).query.json().has("checkpoint"))
            assertEquals(before,db.serverDiaryDao().unsettled(lease.storageScope));assertEquals(oldAxis,db.canonicalEnergyDao().all(lease.storageScope,CanonicalMealRows.context(binding)))
            rejected {db.openHelper.writableDatabase.execSQL("UPDATE sync_protocol_states SET activeScope='calorie-app',phase='draining'")}
            rejected {db.openHelper.writableDatabase.execSQL("UPDATE canonical_energy_versions SET wire='changed'")}
        }finally {db.close();context.deleteDatabase(name)}
    }
    @Test fun accountAbaRejectsLateSevenDomainPageAndKeepsItsSavedEvidence()=runBlocking<Unit> {
        val name="energy-scope-${UUID.randomUUID()}";val db=open(name)
        try {
            val lease=account(db);val binding=checkNotNull(db.bootstrapDao().binding(lease.storageScope))
            SyncProtocolStore(db).readScope(lease,binding,true)
            val snapshots=ServerSnapshotStore(db,protocol);val first=snapshots.beginRead(lease,SyncProtocolScope.ENERGY_V1)
            val next=checkNotNull(snapshots.apply(first,page(listOf(EnergyFixture.sample("version")),next="saved-next")))
            val saved=db.snapshotDao().pages(first.runId)
            val owners=LocalOwnerStore(db);owners.select(owners.ensureGuest().id)
            rejected {snapshots.apply(next,page(listOf(weight(1,"80"))))}
            assertEquals(saved,db.snapshotDao().pages(first.runId))
            val again=owners.select(db.ownerDao().byScope(lease.storageScope)!!.id)
            assertNotEquals(lease.generation,again.generation)
            val current=snapshots.beginRead(again,SyncProtocolScope.ENERGY_V1)
            assertNotEquals(first.runId,current.runId);assertEquals(saved,db.snapshotDao().pages(first.runId))
            assertNull(snapshots.active(again));assertTrue(db.canonicalEnergyDao().all(again.storageScope,CanonicalMealRows.context(binding)).isEmpty())
        }finally {db.close();context.deleteDatabase(name)}
    }
    @Test fun room25MigrationPreservesAllOldFieldsRowidsAndThreeFrozenEnvelopeScopes()=runBlocking<Unit> {
        val sourceName="energy-sync-source-${UUID.randomUUID()}";val name="energy-sync-room25-${UUID.randomUUID()}"
        val source=open(sourceName);var migrated:CalorieDatabase?=null
        try {
            val lease=account(source);val snapshots=ServerSnapshotStore(source,protocol)
            val run=snapshots.begin(lease);snapshots.apply(run,page(listOf(weight(1,"80")),"legacy-checkpoint"))
            ServerDiaryStore(source,schema,energy).apply(lease,run.runId)
            DiaryRepository(source,context,lease).addWeight(81.0,LocalDate.of(2026,10,24))
            val push=MealPushStore(source,schema);val request=checkNotNull(push.prepare(lease));push.markAttempted(request)
            val binding=checkNotNull(source.bootstrapDao().binding(lease.storageScope));val wireContext=CanonicalMealRows.context(binding)
            val plan=ImportPlan(UUID.randomUUID().toString(),lease.storageScope,lease.storageScope,binding.accountId,
                "https://sync.fixture/realm","A","reconcile_same_epoch","fixture",wireContext,"2026-10-24T10:00:00Z")
            source.importDao().insert(plan)
            source.importDao().insert(ReconciliationBatch(UUID.randomUUID().toString(),plan.id,"checkpoint_replay",wireContext,
                run.runId,request.row.requestJson,request.row.requestHash,request.id,"2026-10-24T10:00:00Z",attempted=true))
            val oldSchema=InstrumentationRegistry.getInstrumentation().context.assets.open("pl.roseru.kalorie.data.CalorieDatabase/25.json")
                .use {StrictJson.read(it.readBytes()).getJSONObject("database")}
            val tables=oldSchema.getJSONArray("entities")
            fun columns(table:JSONObject)="rowid,"+table.getJSONArray("fields").let {fields->
                (0 until fields.length()).joinToString(",") {"`"+fields.getJSONObject(it).getString("columnName")+"`"}}
            fun dump(query:(String)->Cursor)=buildMap<String,List<List<String?>>>{for(i in 0 until tables.length()) {
                val table=tables.getJSONObject(i)
                put(table.getString("tableName"),query("SELECT ${columns(table)} FROM `${table.getString("tableName")}` ORDER BY rowid").use {cursor->
                    buildList {while(cursor.moveToNext())add((0 until cursor.columnCount).map {if(cursor.isNull(it))null else "${cursor.getType(it)}:${cursor.getString(it)}"})}})
            }}
            val before=dump {source.openHelper.readableDatabase.query(it)}
            context.getDatabasePath(name).parentFile!!.mkdirs()
            SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name),null).use {old->
                old.execSQL("PRAGMA foreign_keys=OFF");old.execSQL("ATTACH DATABASE ? AS origin",arrayOf(context.getDatabasePath(sourceName).absolutePath))
                for(i in 0 until tables.length()) {
                    val table=tables.getJSONObject(i);val tableName=table.getString("tableName")
                    fun resolved(sql:String)=sql.replace("\${TABLE_NAME}",tableName)
                    old.execSQL(resolved(table.getString("createSql")))
                    val indices=table.optJSONArray("indices")?:JSONArray()
                    for(j in 0 until indices.length())old.execSQL(resolved(indices.getJSONObject(j).getString("createSql")))
                    old.execSQL("INSERT INTO `$tableName` (${columns(table)}) SELECT ${columns(table)} FROM origin.`$tableName`")
                }
                old.execSQL("DETACH DATABASE origin");old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(oldSchema.getString("identityHash")));old.version=25
            }
            migrated=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addMigrations(MIGRATION_25_26, pl.roseru.kalorie.data.MIGRATION_26_27).addCallback(DATABASE_GUARDS).build()
            val sql=migrated.openHelper.readableDatabase
            assertEquals(27,sql.version);assertEquals(before,dump {sql.query(it)})
            for(table in listOf("server_snapshot_runs","sync_push_batches","reconciliation_batches")) {
                assertTrue(sql.query("SELECT count(*) FROM $table WHERE protocolScope='calorie-app'").use {it.moveToFirst();it.getInt(0)>0})
                rejected {sql.execSQL("UPDATE $table SET protocolScope='calorie-app:energy_estimates_v1'")}
            }
            assertEquals(before,dump {sql.query(it)})
            for(table in listOf("sync_protocol_states","canonical_energy_versions"))assertEquals(0,sql.query("SELECT count(*) FROM $table").use {it.moveToFirst();it.getInt(0)})
            assertFalse(sql.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
        }finally {migrated?.close();source.close();context.deleteDatabase(name);context.deleteDatabase(sourceName)}
    }
    @Test fun realTransportUsesCapturedScopeForBothReadModesAndFrozenPushWithoutChangingBody()=runBlocking<Unit> {
        val name="energy-headers-${UUID.randomUUID()}";val db=open(name)
        try {
            val lease=account(db);full(db,lease)
            val scope=checkNotNull(EnergyStore(db).scope(lease));val session=EnergyFixture.Sessions(db,scope).session(scope,false)
            val connections=mutableListOf<RecordingConnection>()
            fun connection(url:URL)=RecordingConnection(url).also {connections+=it}
            val reads=HttpsSnapshotGateway("https://sync.fixture/api/v1",::connection)
            reads.get(session,SnapshotProtocol(schema).query(epoch)){}
            reads.get(session,protocol.query(epoch,scope=SyncProtocolScope.ENERGY_V1)){}
            reads.get(session,protocol.incrementalQuery(epoch,"energy-checkpoint")){}
            DiaryRepository(db,context,lease).editWeight(weightId,85.0)
            val push=checkNotNull(MealPushStore(db,schema).prepare(lease))
            HttpsMealPushGateway("https://sync.fixture/api/v1",::connection).post(session,push.batch){}
            assertNull(connections.first().getRequestProperty("X-Sync-Capability"))
            for(connection in connections.drop(1))assertEquals("energy_estimates_v1",connection.getRequestProperty("X-Sync-Capability"))
            assertArrayEquals(push.batch.body(),connections.last().sent.toByteArray())
            assertEquals(push.row.requestHash,push.batch.sha256)
            assertTrue(connections.all {it.disconnected})
            assertTrue(connections[2].url.query.contains("checkpoint="))
        }finally {db.close();context.deleteDatabase(name)}
    }
    private class RecordingConnection(url:URL):HttpsURLConnection(url) {
        val sent=ByteArrayOutputStream();var disconnected=false
        override fun connect(){}
        override fun disconnect(){disconnected=true}
        override fun usingProxy()=false
        override fun getResponseCode()=200
        override fun getOutputStream()=sent
        override fun getInputStream()=ByteArrayInputStream("{}".toByteArray())
        override fun getHeaderField(name:String):String?=when(name.lowercase()) {
            "content-type"->"application/json";"cache-control"->"no-store";else->null
        }
        override fun getContentType()="application/json"
        override fun getCipherSuite()="SYNTHETIC"
        override fun getLocalCertificates():Array<Certificate>?=null
        override fun getServerCertificates():Array<Certificate> = emptyArray()
    }
}
