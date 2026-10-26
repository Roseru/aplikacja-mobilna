package pl.roseru.kalorie

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.*
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/** Local SQLite/Compose only; no TLS, provider, live server or new award qualification. */
class PrivatePreviewFlowTest {
    @get:Rule val compose=createComposeRule()
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val assets get()=InstrumentationRegistry.getInstrumentation().context.assets
    private fun json(path:String)=assets.open(path).bufferedReader().use {JSONObject(it.readText())}
    private fun own()=json("motivation/motivation-final.json")
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/preview",UUID.randomUUID().toString()).id)
        val bootstrap=AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),own().getString("sync_epoch"),1,"2026-10-26T09:00:00Z"))
        return lease
    }
    @Test fun cacheIsBoundedDetectsCorruptionAndNeverTouchesDiaryOrOutbox()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!
            DiaryRepository(db,context,lease).apply {initialize();setGoal(2400.0,null,null,null);add("basic-banana",100.0,MealType.LUNCH,LocalDate.now(),"preview-budget-diary")}
            val queue=db.dao().operationCount(lease.storageScope);val store=PrivatePreviewStore(db)
            store.save(lease,binding,PrivatePreviewKind.MOTIVATION,"self",JSONObject().put("format_version",1).put("motivation",own()).toString().toByteArray(),1)
            val keys=List(33){UUID.randomUUID().toString()}
            keys.forEachIndexed { index,id ->
                val challenge=json("nemesis/metadata.json").put("id",id).put("status","invited")
                listOf("accepted_at","start_date","end_date","start_at","end_at","deadline","result_status").forEach {challenge.put(it,JSONObject.NULL)}
                val envelope=JSONObject().put("format_version",1).put("motivation",own()).put("challenge",challenge).put("statistics",JSONObject.NULL)
                store.save(lease,binding,PrivatePreviewKind.NEMESIS_DETAIL,id,envelope.toString().toByteArray(),index+2L)
            }
            val wire=CanonicalMealRows.context(binding)
            assertEquals(PrivatePreviewStore.MAX_ENTRIES,db.privatePreviewDao().refs(lease.storageScope,wire).size)
            assertTrue(db.privatePreviewDao().bytes(lease.storageScope)<=PrivatePreviewStore.MAX_OWNER_BYTES)
            assertNull(store.read(lease,binding,PrivatePreviewKind.NEMESIS_DETAIL,keys.first()))
            assertNotNull(store.read(lease,binding,PrivatePreviewKind.MOTIVATION,"self"))
            val latest=db.privatePreviewDao().entry(lease.storageScope,wire,PrivatePreviewKind.NEMESIS_DETAIL.name,keys.last())!!
            db.privatePreviewDao().save(latest.copy(payloadHash="0".repeat(64)))
            assertThrows(PrivatePreviewUnavailableException::class.java){runBlocking {store.read(lease,binding,PrivatePreviewKind.NEMESIS_DETAIL,keys.last())}}
            store.clear(lease,setOf(PrivatePreviewKind.NEMESIS_LIST,PrivatePreviewKind.NEMESIS_DETAIL))
            val cancelled=json("nemesis/metadata.json").put("id",keys.last()).put("status","cancelled").put("cancel_reason","sharing_revoked")
            val cancelledEnvelope=JSONObject().put("format_version",1).put("motivation",own()).put("challenge",cancelled).put("statistics",JSONObject.NULL)
            store.save(lease,binding,PrivatePreviewKind.NEMESIS_DETAIL,keys.last(),cancelledEnvelope.toString().toByteArray(),99)
            val stored=db.privatePreviewDao().entry(lease.storageScope,wire,PrivatePreviewKind.NEMESIS_DETAIL.name,keys.last())!!
            assertFalse(stored.payloadJson.contains("Nemesis fixture"))
            assertNull((store.read(lease,binding,PrivatePreviewKind.NEMESIS_DETAIL,keys.last())!!.value as PrivatePreviewValue.NemesisDetail).challenge.partner)
            assertEquals(queue,db.dao().operationCount(lease.storageScope))
            assertNotNull(store.read(lease,binding,PrivatePreviewKind.MOTIVATION,"self"))
        }finally{db.close()}
    }
    @Test fun populatedRoom26UpgradePreservesAllExistingTablesRowIdsAndPendingBodies()=runBlocking<Unit> {
        val source=memory();val name="preview-migration-${UUID.randomUUID()}";var target:CalorieDatabase?=null
        try {
            val owners=LocalOwnerStore(source);owners.ensureGuest();val guest=owners.currentLease()
            DiaryRepository(source,context,guest).apply {initialize();setGoal(2500.5,null,0.0,null);add("basic-banana",150.5,MealType.LUNCH,LocalDate.now(),"preview-migration-meal")}
            account(source)
            val schema=json("pl.roseru.kalorie.data.CalorieDatabase/26.json").getJSONObject("database")
            val entities=schema.getJSONArray("entities")
            fun dump(query:(String)->Cursor)=buildMap<String,List<List<String?>>>() {
                for(i in 0 until entities.length()) {
                    val entity=entities.getJSONObject(i);val fields=entity.getJSONArray("fields");val table=entity.getString("tableName")
                    val columns="rowid,"+(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                    put(table,query("SELECT $columns FROM `$table` ORDER BY rowid").use {cursor->buildList {
                        while(cursor.moveToNext())add((0 until cursor.columnCount).map {when {
                            cursor.isNull(it)->null;cursor.getType(it)==Cursor.FIELD_TYPE_FLOAT->cursor.getDouble(it).toString();else->cursor.getString(it)
                        }})
                    }})
                }
            }
            val before=dump {source.openHelper.readableDatabase.query(it)}
            context.getDatabasePath(name).parentFile!!.mkdirs()
            SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name),null).use {old->
                for(i in 0 until entities.length()) {
                    val entity=entities.getJSONObject(i);val table=entity.getString("tableName")
                    old.execSQL(entity.getString("createSql").replace("\${TABLE_NAME}",table))
                    val indices=entity.optJSONArray("indices")?:JSONArray()
                    for(j in 0 until indices.length())old.execSQL(indices.getJSONObject(j).getString("createSql").replace("\${TABLE_NAME}",table))
                    val fields=entity.getJSONArray("fields")
                    val columns="rowid,"+(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                    val marks=(0..fields.length()).joinToString(","){"?"}
                    before.getValue(table).forEach {old.execSQL("INSERT INTO `$table` ($columns) VALUES ($marks)",it.toTypedArray())}
                }
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(schema.getString("identityHash")))
                old.version=26
            }
            target=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addMigrations(MIGRATION_26_27).addCallback(DATABASE_GUARDS).build()
            val sql=target!!.openHelper.readableDatabase
            assertEquals(27,sql.version);assertEquals(54,before.size);assertEquals(before,dump {sql.query(it)})
            assertFalse(sql.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
            assertEquals(0L,sql.query("SELECT COUNT(*) FROM private_preview_cache").use {assertTrue(it.moveToFirst());it.getLong(0)})
        }finally{target?.close();source.close();context.deleteDatabase(name)}
    }
    @Test fun threeOfflineScreensShowSavedDatesAndCannotContinuePagesOrIssueNemesisDecisions() {
        val db=memory();val lease=runBlocking {account(db)}
        val binding=runBlocking {SessionBinding(db.ownerDao().byScope(lease.storageScope)!!,lease)}
        val motivation=MotivationReadProtocol.parse(own().toString().toByteArray())
        val challenge=NemesisReadProtocol.metadata(json("nemesis/metadata.json").toString().toByteArray())
        val statistics=NemesisReadProtocol.statistics(json("nemesis/provisional.json").toString().toByteArray(),challenge)
        val page=RankingPage(Instant.parse("2026-10-26T09:00:00Z"),listOf(RankingEntry(1,"Zapisany żołnierz",20,"Szeregowy",2)),"rk1."+"A".repeat(43),Instant.parse("2026-10-26T09:10:00Z"))
        val network=AtomicInteger();val cleared=AtomicInteger();var screen by mutableIntStateOf(0)
        val actions=SessionActions({},{},{},{},{},{},readRanking={network.incrementAndGet()},nextRankingPage={network.incrementAndGet()},
            readNemesis={network.incrementAndGet()},acceptNemesis={_,_,_,_->network.incrementAndGet()},
            clearSavedPrivatePreview={owner,_->assertEquals(lease,owner);cleared.incrementAndGet()})
        try {
            compose.setContent {CalorieTheme(false) {
                val view=SessionView(binding=binding,serverLinked=true,
                    motivation=MotivationState.Saved(motivation,1_793_000_000_000),ranking=RankingState.Saved(page,1_793_000_000_000),
                    nemesis=NemesisState.DetailSaved(challenge,statistics,1_793_000_000_000))
                when(screen) {
                    0->ServerMotivationPanel(view,{network.incrementAndGet()},{})
                    1->RankingScreen(view,actions,{},{},{})
                    else->NemesisScreen(view,actions,{},{})
                }
            }}
            compose.onNodeWithTag("saved-preview-date").assertExists();compose.onNodeWithTag("achievement-server-read").assertDoesNotExist()
            compose.runOnIdle {screen=1}
            compose.onNodeWithTag("ranking-content").performScrollToNode(hasText("Zapisany żołnierz"))
            compose.onNodeWithText("Zapisany żołnierz").assertExists();compose.onNodeWithTag("ranking-next").assertDoesNotExist()
            compose.onNodeWithTag("ranking-saved-clear").performScrollTo().performClick();assertEquals(1,cleared.get())
            compose.runOnIdle {screen=2}
            compose.onNodeWithTag("saved-preview-date").assertExists();compose.onNodeWithTag("nemesis-mutations").assertDoesNotExist()
            compose.onNodeWithTag("nemesis-next").assertDoesNotExist();assertEquals(0,network.get())
        }finally{db.close()}
    }
}
