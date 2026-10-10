package pl.roseru.kalorie

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteFullException
import androidx.room.Room
import androidx.room.withTransaction
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.*
import pl.roseru.kalorie.data.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import java.time.LocalDate
import java.util.UUID
import java.util.zip.GZIPOutputStream

@RunWith(AndroidJUnit4::class)
class CatalogStorageTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val date = LocalDate.now().minusDays(4)
    private fun asset(name: String) = context.assets.open("catalog/e2/$name")
    private fun reader() = CatalogPackageReader(CatalogSchema(
        JSONObject(asset("common.schema.json").bufferedReader().use { it.readText() }),
        JSONObject(asset("catalog.schema.json").bufferedReader().use { it.readText() })), CatalogPackageReader.DEMO_ID, "demo")
    private fun demo() = reader().read(asset("manifest.json"), asset("base-pl.1.json.gz.bin"))
    private fun release(number: Int, edit: (JSONObject) -> Unit = {}): ValidatedCatalog {
        val payload = demo().payload().put("release", number).apply(edit)
        val raw = payload.toString().toByteArray(Charsets.UTF_8)
        val gzip = ByteArrayOutputStream().also { output -> GZIPOutputStream(output).use { it.write(raw) } }.toByteArray()
        val manifest = JSONObject(asset("manifest.json").bufferedReader().use { it.readText() })
            .put("release", number).put("path", "base-pl.$number.json.gz").put("counts", payload.getJSONObject("counts"))
            .put("compressed_bytes", gzip.size).put("uncompressed_bytes", raw.size)
            .put("sha256", MessageDigest.getInstance("SHA-256").digest(gzip).joinToString("") { "%02x".format(it.toInt() and 255) })
        return reader().read(ByteArrayInputStream(manifest.toString().toByteArray()), ByteArrayInputStream(gzip))
    }
    private fun newer(number: Int) = release(number) { payload ->
        val first = payload.getJSONArray("products").getJSONObject(0)
        first.put("revision", number).getJSONObject("nutrition_per_100").put("energy_kcal", "100")
        payload.getJSONArray("rations").objects().forEach { ration ->
            ration.put("revision", number)
            ration.getJSONArray("components").objects().forEach { part ->
                val ref = part.getJSONObject("product")
                if (ref.getString("product_id") == first.getString("product_id")) ref.put("revision", number)
            }
        }
    }
    private fun outbox(db: CalorieDatabase) = db.openHelper.readableDatabase.query("SELECT operationId,payload,status FROM outbox ORDER BY operationId").use { cursor ->
        buildList { while (cursor.moveToNext()) add((0..2).map { cursor.getString(it) }) }
    }
    private suspend fun fails(code: String, action: suspend () -> Unit) {
        try { action(); fail("Expected $code") } catch (error: CatalogError) { assertEquals(code, error.code) }
    }

    @Test fun stagingIsInvisibleAndActivationPersistsAcrossRestartWithoutDuplicates() = runBlocking {
        val name = "catalog-stage-${UUID.randomUUID()}.db"
        var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        try {
            val id = CatalogStore(db).stage(demo())
            assertTrue(db.dao().products().first().isEmpty()); assertTrue(db.dao().rations().first().isEmpty())
            assertNull(db.catalogDao().active(CatalogPackageReader.DEMO_ID))
            db.close(); db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            assertEquals(id, CatalogStore(db).stage(demo()))
            assertTrue(CatalogStore(db).activate(id)); assertFalse(CatalogStore(db).import(demo()))
            assertEquals(18, db.dao().products().first().size)
            assertEquals(18, db.dao().rations().first().single().components.size)
            assertEquals(0, db.dao().operationCount(DiaryRepository.GUEST))
            db.close(); db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            assertEquals(id, db.catalogDao().active(CatalogPackageReader.DEMO_ID)!!.generationId)
            assertEquals(18, db.dao().products().first().size)
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun partialRationKeepsExactSnapshotsAndQueueThroughCatalogUpdateAndEditing() = runBlocking {
        val name = "catalog-history-${UUID.randomUUID()}.db"
        var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        try {
            var repo = DiaryRepository(db, context); repo.initialize()
            assertEquals(33, db.dao().products().first().size); assertEquals(3, db.dao().rations().first().size)
            val ration = db.dao().rations().first().single { it.ration.catalogJson != null }
            val parts = ration.components.sortedBy { it.position }
            repo.addRation(ration.ration.id, mapOf(parts[0].id to 150.0, parts[2].id to 25.0), MealType.LUNCH, date, "partial")
            repo.addRation(ration.ration.id, mapOf(parts[0].id to 150.0), MealType.LUNCH, date, "partial")
            val before = db.dao().meal("partial", DiaryRepository.GUEST)!!
            assertEquals(2, before.items.size)
            val totals = before.items.map { it.consumed() }.total().asExact()
            assertEquals("213", totals.energy.canonical); assertEquals("18.5", totals.protein.canonical)
            assertEquals("5.5", totals.fat.canonical); assertEquals("20.7", totals.carbs.canonical)
            before.items.forEach { item ->
                val snapshot = JSONObject(item.snapshotJson!!)
                assertEquals("nutrition_v1", snapshot.getString("formula_version"))
                assertEquals(1, snapshot.getJSONObject("product").getInt("revision"))
                assertEquals(1, snapshot.getJSONArray("sources").length())
            }
            val queue = outbox(db)
            assertTrue(CatalogStore(db).import(newer(2)))
            assertEquals(before, db.dao().meal("partial", DiaryRepository.GUEST)); assertEquals(queue, outbox(db))
            assertNotNull(db.dao().ration(ration.ration.id))
            assertFalse(db.dao().rations().first().any { it.ration.id == ration.ration.id })
            val item = before.items.single { it.rationComponentId == parts[0].id }
            repo.editItem("partial", item.id, 12.123456789123, "12.123456789123")
            val edited = db.dao().meal("partial", DiaryRepository.GUEST)!!.items.single { it.id == item.id }
            assertEquals("12.123456789123", edited.amountText)
            assertEquals("10.54740740653701", edited.consumed().asExact().energy.canonical)
            db.close(); db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            repo = DiaryRepository(db, context); repo.initialize()
            assertEquals(2, db.catalogDao().active(CatalogPackageReader.DEMO_ID)!!.release)
            assertEquals(edited, db.dao().meal("partial", DiaryRepository.GUEST)!!.items.single { it.id == item.id })
            assertEquals(2, db.dao().operationCount(DiaryRepository.GUEST))
            repo.delete("partial"); assertTrue(db.dao().meal("partial", DiaryRepository.GUEST)!!.meal.deleted)
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun staleActivationAndImmutableVersionConflictsCannotReplaceActiveCatalog() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val store = CatalogStore(db); store.import(demo())
            val second = store.stage(newer(2)); val third = store.stage(newer(3))
            assertTrue(store.activate(third)); assertFalse(store.activate(second))
            assertEquals(3, db.catalogDao().active(CatalogPackageReader.DEMO_ID)!!.release)
            fails("release_conflict") { store.stage(release(3)) }
            fails("version_conflict") { store.stage(release(4) { it.getJSONArray("products").getJSONObject(0).put("name", "Inna treść tej samej wersji") }) }
            assertNull(db.catalogDao().generation(CatalogPackageReader.DEMO_ID, 4))
            fails("unknown_generation") { store.activate("missing") }
            assertEquals(3, db.catalogDao().active(CatalogPackageReader.DEMO_ID)!!.release)
            assertEquals(18, db.dao().products().first().size)
        } finally { db.close() }
    }

    @Test fun interruptionBeforeStageOrActivateCommitRollsBackAndRetryRecovers() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val store = CatalogStore(db); store.import(demo())
            try { CatalogStore(db, beforeStageCommit = { throw IllegalStateException("interrupted") }).stage(newer(2)); fail() }
            catch (_: IllegalStateException) { }
            assertNull(db.catalogDao().generation(CatalogPackageReader.DEMO_ID, 2))
            val stage = store.stage(newer(2))
            try { CatalogStore(db, beforeActivateCommit = { throw IllegalStateException("interrupted") }).activate(stage); fail() }
            catch (_: IllegalStateException) { }
            assertEquals(1, db.catalogDao().active(CatalogPackageReader.DEMO_ID)!!.release)
            assertTrue(store.activate(stage)); assertFalse(store.activate(stage))
            assertEquals(2, db.catalogDao().active(CatalogPackageReader.DEMO_ID)!!.release)
        } finally { db.close() }
    }

    @Test fun actualSqliteFullDuringStagePreservesPreviousCatalogDiaryAndOutbox() = runBlocking {
        val name = "catalog-full-${UUID.randomUUID()}.db"
        val db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        try {
            val repo = DiaryRepository(db, context); repo.initialize()
            repo.add("basic-banana", 120.0, MealType.LUNCH, date, "preserve-meal")
            val before = db.dao().meal("preserve-meal", DiaryRepository.GUEST); val queue = outbox(db)
            val sql = db.openHelper.writableDatabase
            val pages = sql.query("PRAGMA page_count").use { it.moveToFirst(); it.getInt(0) }
            val large = release(2) { payload ->
                val products = payload.getJSONArray("products"); val first = products.getJSONObject(0)
                repeat(300) { products.put(JSONObject(first.toString()).put("product_id", UUID.randomUUID().toString())) }
                payload.getJSONObject("counts").put("products", products.length())
            }
            var writerFailure: Throwable? = null
            try {
                db.withTransaction {
                    // PRAGMA applies per connection. Hold Room's writer while limiting and importing.
                    sql.query("PRAGMA max_page_count=$pages").use { cursor ->
                        assertTrue(cursor.moveToFirst()); assertEquals(pages, cursor.getInt(0))
                    }
                    try { CatalogStore(db).stage(large) }
                    catch (error: Throwable) { writerFailure = error; throw error }
                }
                fail("Expected SQLITE_FULL")
            }
            catch (error: Exception) {
                // SQLITE_FULL aborts SQLite's transaction; the outer Room rollback may mask it.
                val original = writerFailure ?: error
                assertTrue(original.toString(), generateSequence(original) { it.cause }.any { it is SQLiteFullException })
            } finally { db.withTransaction { sql.query("PRAGMA max_page_count=2147483646").use { it.moveToFirst() } } }
            assertEquals(1, db.catalogDao().active(CatalogPackageReader.DEMO_ID)!!.release)
            assertNull(db.catalogDao().generation(CatalogPackageReader.DEMO_ID, 2))
            assertEquals(before, db.dao().meal("preserve-meal", DiaryRepository.GUEST)); assertEquals(queue, outbox(db))
            assertEquals(33, db.dao().products().first().size)
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun millilitresUnknownEnergyAndKnownZeroSurviveRoomSnapshot() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val value = release(1) { payload ->
                val product = payload.getJSONArray("products").getJSONObject(0)
                product.put("basis_unit", "ml").getJSONObject("package_quantity").put("unit", "ml")
                product.getJSONObject("nutrition_per_100").put("energy_kcal", JSONObject.NULL).put("protein_g", "0")
                val id = product.getString("product_id")
                payload.getJSONArray("rations").objects().forEach { ration -> ration.getJSONArray("components").objects().forEach { part ->
                    if (part.getJSONObject("product").getString("product_id") == id) part.getJSONObject("quantity").put("unit", "ml")
                } }
            }
            CatalogStore(db).import(value)
            val row = value.payload().getJSONArray("products").getJSONObject(0)
            val id = CatalogStore.recordId("product", row.getString("product_id"), 1)
            val repo = DiaryRepository(db, context)
            repo.add(id, 250.0, MealType.LUNCH, date, "drink", "250")
            val item = db.dao().meal("drink", DiaryRepository.GUEST)!!.items.single()
            assertEquals("ml", item.unit); assertEquals("250", item.amountText)
            val totals = item.consumed().asExact()
            assertFalse(totals.energy.complete); assertEquals(1, totals.energy.missingCount)
            assertEquals("0", totals.energy.canonical); assertEquals("≥ 0", item.consumed().energyText())
            assertTrue(totals.protein.complete); assertEquals("0", totals.protein.canonical)
            assertEquals("ml", item.withAmount("100,5").unit)
        } finally { db.close() }
    }

    @Test fun inconsistentProjectionOrExcessRationQuantityRollsBackMealAndQueue() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val repo = DiaryRepository(db, context); repo.initialize()
            val ration = db.dao().rations().first().single { it.ration.catalogJson != null }
            val part = ration.components.minBy { it.position }
            try { repo.add(part.productId, 20.0, MealType.LUNCH, date, "mismatch", "30"); fail() } catch (_: IllegalArgumentException) { }
            try { repo.addRation(ration.ration.id, mapOf(part.id to part.packageGrams), MealType.LUNCH, date, "excess",
                mapOf(part.id to (java.math.BigDecimal(part.quantityText!!) + java.math.BigDecimal("0.000000000001")).toPlainString())); fail() }
            catch (_: IllegalArgumentException) { }
            assertNull(db.dao().meal("mismatch", DiaryRepository.GUEST)); assertNull(db.dao().meal("excess", DiaryRepository.GUEST))
            assertEquals(0, db.dao().operationCount(DiaryRepository.GUEST))
        } finally { db.close() }
    }

    @Test fun migrationFromActualV3SchemaPreservesEveryOldColumnBeforeImport() = runBlocking {
        val name = "migration-v3-${UUID.randomUUID()}.db"
        val schema = JSONObject(InstrumentationRegistry.getInstrumentation().context.assets
            .open("pl.roseru.kalorie.data.CalorieDatabase/3.json").bufferedReader().use { it.readText() }).getJSONObject("database")
        val entities = schema.getJSONArray("entities").objects()
        val file = context.getDatabasePath(name); file.parentFile!!.mkdirs()
        val queries = entities.associate { row -> row.getString("tableName") to
            "SELECT " + row.getJSONArray("fields").objects().joinToString(",") { "`${it.getString("columnName")}`" } +
            " FROM `${row.getString("tableName")}` ORDER BY 1" }
        val expected = mutableMapOf<String, List<List<String?>>>()
        SQLiteDatabase.openOrCreateDatabase(file, null).use { old ->
            entities.forEach { row ->
                fun resolve(text: String) = text.replace("\${TABLE_NAME}", row.getString("tableName"))
                old.execSQL(resolve(row.getString("createSql")))
                row.optJSONArray("indices")?.objects()?.forEach { old.execSQL(resolve(it.getString("createSql"))) }
            }
            old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY, identity_hash TEXT)")
            old.execSQL("INSERT INTO room_master_table VALUES (42, ?)", arrayOf(schema.getString("identityHash")))
            old.execSQL("INSERT INTO products VALUES ('private','Prywatny','prywatny',100.123456789,NULL,0,3,12.5,'Własny','Etykieta',0,'guest')")
            old.execSQL("INSERT INTO meals VALUES ('old','guest','2026-10-01','2026-10-01T10:00:00Z','Europe/Warsaw','LUNCH',4,7,0,'ration-old','Historyczna racja')")
            old.execSQL("INSERT INTO meals VALUES ('tombstone','guest','2026-10-01','2026-10-01T11:00:00Z','Europe/Warsaw','DINNER',3,8,1,NULL,NULL)")
            old.execSQL("INSERT INTO meal_items VALUES ('item','old','private','Prywatny',12.5,100.123456789,NULL,0,3,'old-component')")
            old.execSQL("INSERT INTO goals VALUES ('goal','guest','1970-01-01',2900,NULL,90,300)")
            old.execSQL("INSERT INTO outbox VALUES ('pending','guest','meal','old','update',4,'{\"audit\":\"old payload\"}','2026-10-01T10:00:00Z','pending')")
            old.execSQL("INSERT INTO outbox VALUES ('sent','guest','meal','tombstone','delete',3,'{\"deleted\":true}','2026-10-01T11:00:00Z','acked')")
            old.execSQL("INSERT INTO profiles VALUES ('profile','guest','Poligon',182.5,'LINE','REDUCE','Europe/Warsaw',3)")
            old.execSQL("INSERT INTO weights VALUES ('weight','guest','2026-10-01','2026-10-01T10:00:00Z','Europe/Warsaw',82.4,0,2)")
            old.execSQL("INSERT INTO weights VALUES ('deleted-weight','guest','2026-10-01','2026-10-01T11:00:00Z','Europe/Warsaw',82.1,1,3)")
            old.execSQL("INSERT INTO diary_days VALUES ('day','guest','2026-10-01',1,5)")
            old.execSQL("INSERT INTO rations VALUES ('ration-old','Racja','Opis','Źródło',1)")
            old.execSQL("INSERT INTO ration_components VALUES ('old-component','ration-old','private',100,0)")
            queries.forEach { (table, query) -> expected[table] = old.rawQuery(query, null).use { cursor ->
                buildList { while (cursor.moveToNext()) add((0 until cursor.columnCount).map { if (cursor.isNull(it)) null else cursor.getString(it) }) }
            } }
            old.version = 3
        }
        val db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addMigrations(MIGRATION_3_4, MIGRATION_4_5, MIGRATION_5_6).addCallback(DATABASE_GUARDS).build()
        try {
            val sql = db.openHelper.readableDatabase
            queries.forEach { (table, query) -> assertEquals(table, expected.getValue(table), sql.query(query).use { cursor ->
                buildList { while (cursor.moveToNext()) add((0 until cursor.columnCount).map { if (cursor.isNull(it)) null else cursor.getString(it) }) }
            }) }
            assertNull(db.dao().meal("old", DiaryRepository.GUEST)!!.items.single().snapshotJson)
            val before = outbox(db); DiaryRepository(db, context).initialize()
            assertEquals(before, outbox(db))
            assertEquals(12.515432098625, db.dao().meal("old", DiaryRepository.GUEST)!!.items.single().consumed().kcal, 0.0)
            assertTrue(db.dao().meal("tombstone", DiaryRepository.GUEST)!!.meal.deleted)
            assertTrue(db.dao().weight("deleted-weight", DiaryRepository.GUEST)!!.deleted)
            assertEquals("Poligon", db.dao().currentProfile(DiaryRepository.GUEST)!!.nickname)
            assertTrue(db.dao().currentDiaryDay(DiaryRepository.GUEST, "2026-10-01")!!.declaredComplete)
        } finally { db.close(); context.deleteDatabase(name) }
    }
}
