package pl.roseru.kalorie

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

class DomainSyncMigrationTest {
    @Test fun actualRoom17PreservesEveryOldValueRowidLegacyOutboxAndProvenServerSnapshot() = runBlocking<Unit> {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val source = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val name = "domains-room17-${UUID.randomUUID()}"; var target: CalorieDatabase? = null
        fun uuid() = UUID.randomUUID().toString()
        try {
            val owners = LocalOwnerStore(source); owners.ensureGuest(); val guest = owners.currentLease()
            val repo = DiaryRepository(source, context, guest)
            val date = LocalDate.of(2026, 10, 21)
            repo.setProfile("Legacy guest", 177.125, ActivityClass.LINE, DietAim.MAINTAIN)
            repo.setGoal(2500.125, null, 0.0, null); repo.setGoal(2400.5, null, null, 200.125)
            repo.addCustomProduct(CustomProductDraft("Legacy private", 321.125, null, 0.0, 12.5, "Original source"),
                75.123456789012, MealType.LUNCH, date)
            val weight = uuid(); repo.addWeight(81.123456789, date, weight)
            repo.setDayComplete(date, true)
            val account = owners.select(owners.registerIdentity("https://fixture.example/realms/migration", uuid()).id)
            val epoch = "55555555-5555-4555-8555-555555555555"
            val bootstrap = AccountBootstrapStore(source)
            bootstrap.apply(bootstrap.begin(account), BootstrapResponse(uuid(), epoch, 1, "2026-10-23T12:00:00Z"))
            val wireSchema = CanonicalMealRows.schema(context)
            val snapshots = ServerSnapshotStore(source, SnapshotProtocol(wireSchema))
            val page = JSONObject().put("sync_epoch", epoch).put("mode", "snapshot").put("snapshot_token", "migration-snapshot")
                .put("page_token", JSONObject.NULL).put("checkpoint", "migration-checkpoint")
                .put("server_time", "2026-10-23T12:00:00Z").put("goal_timeline_revision", 7)
                .put("entities", JSONArray()).put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray())
            assertNull(snapshots.apply(snapshots.begin(account), page.toString().toByteArray()))
            val run = MealPushStore(source, wireSchema).gate(account).run.id
            val wireContext = CanonicalMealRows.context(source.bootstrapDao().binding(account.storageScope)!!)
            val profile = uuid()
            source.dao().saveProfile(ProfileEntity(profile, account.storageScope, "Server profile", null,
                ActivityClass.LINE.name, DietAim.MAINTAIN.name, "Europe/Warsaw", 1))
            val profilePayload = """{"pseudonym":"Server profile","height_cm":null,"activity_class":"line","time_zone":"Europe/Warsaw"}"""
            source.serverDiaryDao().save(ServerDiaryRecord(account.storageScope, "profile", profile, profile,
                wireContext, 4, false, false, profilePayload, run, "applied"))
            val held = uuid()
            source.serverDiaryDao().save(ServerDiaryRecord(account.storageScope, "product_draft", held, null,
                wireContext, 9, false, false, null, run, "held"))
            source.serverDiaryDao().insert(ServerDiaryApplication(run, account.storageScope, wireContext,
                "2026-10-23T12:00:00Z", 7, 1, 1, "2026-10-23T12:01:00Z"))
            val schema = InstrumentationRegistry.getInstrumentation().context.assets
                .open("pl.roseru.kalorie.data.CalorieDatabase/17.json").use { JSONObject(String(it.readBytes())).getJSONObject("database") }
            val entities = schema.getJSONArray("entities")
            fun dump(query: (String) -> Cursor) = buildMap<String, List<List<String?>>>() {
                for (i in 0 until entities.length()) {
                    val entity = entities.getJSONObject(i); val fields = entity.getJSONArray("fields")
                    val columns = "rowid," + (0 until fields.length()).joinToString(",") { "`" + fields.getJSONObject(it).getString("columnName") + "`" }
                    put(entity.getString("tableName"), query("SELECT $columns FROM `${entity.getString("tableName")}` ORDER BY rowid").use { cursor ->
                        buildList { while (cursor.moveToNext()) add((0 until cursor.columnCount).map { column ->
                            when {
                                cursor.isNull(column) -> null
                                cursor.getType(column) == Cursor.FIELD_TYPE_FLOAT -> cursor.getDouble(column).toString()
                                else -> cursor.getString(column)
                            }
                        }) }
                    })
                }
            }
            val values = dump { source.openHelper.readableDatabase.query(it) }
            assertTrue(source.dao().operationCount(guest.storageScope) >= 7)
            context.getDatabasePath(name).parentFile!!.mkdirs()
            var before = emptyMap<String, List<List<String?>>>()
            SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name), null).use { old ->
                old.execSQL("PRAGMA foreign_keys=OFF")
                for (i in 0 until entities.length()) {
                    val entity = entities.getJSONObject(i); val table = entity.getString("tableName")
                    old.execSQL(entity.getString("createSql").replace("\${TABLE_NAME}", table))
                    val indices = entity.optJSONArray("indices") ?: JSONArray()
                    for (j in 0 until indices.length()) old.execSQL(indices.getJSONObject(j).getString("createSql").replace("\${TABLE_NAME}", table))
                    val fields = entity.getJSONArray("fields")
                    val columns = "rowid," + (0 until fields.length()).joinToString(",") { "`" + fields.getJSONObject(it).getString("columnName") + "`" }
                    val marks = (0..fields.length()).joinToString(",") { "?" }
                    values.getValue(table).forEach { old.execSQL("INSERT INTO `$table` ($columns) VALUES ($marks)", it.toTypedArray()) }
                }
                old.execSQL("UPDATE weights SET rowid=777 WHERE id=?", arrayOf(weight))
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)", arrayOf(schema.getString("identityHash")))
                old.version = 17; before = dump { old.rawQuery(it, null) }
                assertFalse(old.rawQuery("PRAGMA foreign_key_check", null).use { it.moveToFirst() })
            }
            target = Room.databaseBuilder(context, CalorieDatabase::class.java, name)
                .addMigrations(MIGRATION_17_18, MIGRATION_18_19).addCallback(DATABASE_GUARDS).build()
            val sql = target!!.openHelper.readableDatabase
            assertEquals(18, sql.version)
            assertEquals(before, dump { sql.query(it) })
            assertFalse(sql.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
            assertEquals(81.123456789, target!!.dao().weight(weight, guest.storageScope)!!.kg, 0.0)
            assertEquals(777L, sql.query("SELECT rowid FROM weights WHERE id=?", arrayOf(weight)).use { assertTrue(it.moveToFirst()); it.getLong(0) })
            val migrated = target!!.domainSyncDao().state(account.storageScope, "profile", profile)!!
            assertEquals(profilePayload, migrated.wirePayload); assertEquals(4, migrated.serverRevision)
            assertFalse(migrated.deleted); assertEquals(wireContext, migrated.wireContext)
            assertNull(target!!.domainSyncDao().state(account.storageScope, "product_draft", held))
            assertEquals(7, target!!.domainSyncDao().timeline(account.storageScope)!!.revision)
            assertTrue(target!!.domainSyncDao().unsettled(guest.storageScope).isEmpty())
            assertNull(target!!.domainSyncDao().timeline(guest.storageScope))
            assertTrue(sql.query("SELECT 1 FROM outbox WHERE ownerScope=? AND wireFormat='legacy'", arrayOf(guest.storageScope)).use { it.moveToFirst() })
            assertEquals(2, target!!.serverDiaryDao().allGoals(guest.storageScope).size)
            assertNull(target!!.dao().currentProfile(account.storageScope)!!.heightCm)
        } finally { target?.close(); source.close(); context.deleteDatabase(name) }
    }
}
