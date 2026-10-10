package pl.roseru.kalorie

import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.objects
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class OwnerStorageTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val today = LocalDate.now()
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).build()
    private suspend fun rejects(action: suspend () -> Unit) {
        val error = try { action(); null } catch (error: Exception) { error }
        assertNotNull("Expected rejected operation", error)
    }
    private suspend fun stale(action: suspend () -> Unit) {
        val error = try { action(); null } catch (error: Exception) { error }
        assertTrue("Expected stale owner, got $error", error is StaleOwnerException)
    }

    @Test fun identityIsExactIdempotentAndRegistrationDoesNotSelectAccount() = runBlocking {
        val db = memory()
        try {
            val owners = LocalOwnerStore(db)
            val guest = owners.ensureGuest()
            UUID.fromString(guest.id)
            assertEquals(guest, owners.ensureGuest())
            val before = owners.currentLease()
            val account = owners.registerIdentity("https://identity.example/realm", "subject-A")
            assertEquals(account, owners.registerIdentity("https://identity.example/realm", "subject-A"))
            assertNotEquals(account.id, owners.registerIdentity("https://other.example/realm", "subject-A").id)
            assertNotEquals(account.id, owners.registerIdentity("https://identity.example/realm", "subject-B").id)
            assertNotEquals(account.id, owners.registerIdentity("https://identity.example/realm/", "subject-A").id)
            assertEquals(before, owners.currentLease())
            assertEquals(account.id, account.storageScope)
            for (issuer in listOf("http://identity.example", "https://identity.example?token=x", "https://user:pass@identity.example", "https://identity.example#fragment", "not-a-url")) {
                rejects { owners.registerIdentity(issuer, "valid-subject") }
            }
            for (subject in listOf("", " ", " padded", "line\nbreak", "x".repeat(256))) {
                rejects { owners.registerIdentity("https://identity.example", subject) }
            }
            owners.registerIdentity("http://localhost:8080/realms/dev", "dev-subject")
            rejects { owners.select("unknown-owner") }
            assertEquals(before, owners.currentLease())
        } finally { db.close() }
    }

    @Test fun guestAndTwoAccountsKeepPrivateDataAnalyticsAndQueuesSeparate() = runBlocking {
        val db = memory()
        try {
            val owners = LocalOwnerStore(db)
            val guest = owners.ensureGuest()
            val guestRepo = DiaryRepository(db, context, owners.currentLease())
            guestRepo.initialize()
            guestRepo.add("basic-banana", 100.0, MealType.LUNCH, today, "guest-meal")
            val a = owners.registerIdentity("https://identity.example", "A")
            val b = owners.registerIdentity("https://identity.example", "B")
            for ((account, value) in listOf(a to 100.0, b to 200.0)) {
                val repo = DiaryRepository(db, context, owners.select(account.id))
                repo.initialize()
                assertNull(repo.dao.goal(repo.owner, today.toString()).first())
                repo.addCustomProduct(CustomProductDraft("Produkt ${account.subject}", value, 10.0, 5.0, 20.0, "Przepis"),
                    100.0, MealType.LUNCH, today, "meal-${account.id}", "product-${account.id}")
                repo.setProfile("Konto ${account.subject}", 180.0, ActivityClass.LINE, DietAim.MAINTAIN)
                repo.setGoal(3000.0, 100.0, 80.0, 400.0)
                repo.addWeight(if (account == a) 80.0 else 90.0, today, "weight-${account.id}")
                repo.setDayComplete(today, true)
                assertEquals(6, repo.dao.operationCount(repo.owner))
                assertEquals(6, repo.dao.pending(repo.owner).first())
                assertEquals(34, repo.dao.products(repo.owner).first().size)
                assertEquals(1, repo.dao.day(repo.owner, today.toString()).first().size)
                assertEquals(1, repo.dao.recent(repo.owner).first().size)
                assertEquals("Konto ${account.subject}", repo.dao.profile(repo.owner).first()!!.nickname)
                val analytics = AnalyticsRepository(repo.dao).observe(repo.owner, AnalyticsWindow(today, AnalyticsPeriod.WEEK)).first()
                assertEquals(value.toBigDecimal().stripTrailingZeros(), analytics.days.last().total!!.asExact().energy.knownSum.stripTrailingZeros())
            }
            assertNull(db.dao().product("product-${a.id}", b.storageScope))
            assertNull(db.dao().meal("meal-${a.id}", b.storageScope))
            assertNull(db.dao().weight("weight-${a.id}", b.storageScope))
            assertEquals(90.0, db.dao().weights(b.storageScope).first().single().kg, 0.0)
            val back = DiaryRepository(db, context, owners.select(guest.id))
            assertEquals(1, back.dao.operationCount(back.owner))
            assertEquals(33, back.dao.products(back.owner).first().size)
            assertNull(back.dao.profile(back.owner).first())
            assertTrue(back.dao.weights(back.owner).first().isEmpty())
            assertNull(back.dao.diaryDay(back.owner, today.toString()).first())
            assertEquals("guest-meal", back.dao.day(back.owner, today.toString()).first().single().meal.id)
            assertEquals(6, db.dao().operationCount(a.storageScope))
            assertEquals(6, db.dao().operationCount(b.storageScope))
        } finally { db.close() }
    }

    @Test fun foreignIdsAndPrivateProductsCannotBeReadModifiedOrOverwritten() = runBlocking {
        val db = memory()
        try {
            val owners = LocalOwnerStore(db)
            val a = owners.registerIdentity("https://identity.example", "A")
            val b = owners.registerIdentity("https://identity.example", "B")
            val repoA = DiaryRepository(db, context, owners.select(a.id))
            repoA.initialize()
            repoA.addCustomProduct(CustomProductDraft("Prywatny", 100.0, null, null, null, "Przepis"), 100.0,
                MealType.LUNCH, today, "existing-meal", "existing-product")
            repoA.addWeight(80.0, today, "existing-weight")
            val before = db.dao().meal("existing-meal", a.storageScope)!!
            val weight = db.dao().weight("existing-weight", a.storageScope)
            val repoB = DiaryRepository(db, context, owners.select(b.id))
            rejects { repoB.add("existing-product", 100.0, MealType.LUNCH, today, "foreign-product-meal") }
            rejects { repoB.add("basic-banana", 100.0, MealType.LUNCH, today, "existing-meal") }
            rejects { repoB.addCustomProduct(CustomProductDraft("Kolizja", 200.0, null, null, null, "Przepis"),
                100.0, MealType.LUNCH, today, "collision-meal", "existing-product") }
            rejects { repoB.edit("existing-meal", 200.0) }
            rejects { repoB.editItem("existing-meal", before.items.single().id, 200.0) }
            rejects { repoB.removeItem("existing-meal", before.items.single().id) }
            rejects { repoB.delete("existing-meal") }
            rejects { repoB.addWeight(90.0, today, "existing-weight") }
            rejects { repoB.editWeight("existing-weight", 90.0) }
            rejects { repoB.deleteWeight("existing-weight") }
            assertEquals(before, db.dao().meal("existing-meal", a.storageScope))
            assertEquals(weight, db.dao().weight("existing-weight", a.storageScope))
            assertEquals(3, db.dao().operationCount(a.storageScope))
            assertEquals(0, db.dao().operationCount(b.storageScope))
            assertTrue(db.dao().day(b.storageScope, today.toString()).first().isEmpty())
        } finally { db.close() }
    }

    @Test fun sharedRationCatalogKeepsConsumedAmountsAndSnapshotsPrivate() = runBlocking {
        val db = memory()
        try {
            val owners = LocalOwnerStore(db)
            DiaryRepository(db, context).initialize()
            val guest = owners.ensureGuest()
            val account = owners.registerIdentity("https://identity.example", "A")
            val ration = db.dao().rations().first().single { it.ration.catalogJson != null }
            val part = ration.components.minBy { it.position }
            DiaryRepository(db, context, owners.currentLease()).addRation(ration.ration.id,
                mapOf(part.id to 100.0), MealType.LUNCH, today, "guest-ration")
            val repo = DiaryRepository(db, context, owners.select(account.id))
            repo.addRation(ration.ration.id, mapOf(part.id to 50.0), MealType.LUNCH, today, "account-ration")
            val guestMeal = db.dao().meal("guest-ration", guest.storageScope)!!
            val accountMeal = db.dao().meal("account-ration", account.storageScope)!!
            assertEquals(guestMeal.meal.rationId, accountMeal.meal.rationId)
            assertEquals("100", guestMeal.items.single().amountText)
            assertEquals("50", accountMeal.items.single().amountText)
            assertNotNull(accountMeal.items.single().snapshotJson)
            rejects { repo.editItem("guest-ration", guestMeal.items.single().id, 25.0) }
            repo.delete("account-ration")
            assertEquals(guestMeal, db.dao().meal("guest-ration", guest.storageScope))
            assertTrue(db.dao().day(account.storageScope, today.toString()).first().isEmpty())
            assertEquals(1, db.dao().operationCount(guest.storageScope))
            assertEquals(2, db.dao().operationCount(account.storageScope))
            assertEquals(3, db.dao().rations().first().size)
        } finally { db.close() }
    }

    @Test fun delayedWriteAndReturningToSameAccountCannotReuseOldLease() = runBlocking {
        val db = memory()
        try {
            val owners = LocalOwnerStore(db)
            val a = owners.registerIdentity("https://identity.example", "A")
            val b = owners.registerIdentity("https://identity.example", "B")
            val old = DiaryRepository(db, context, owners.select(a.id))
            old.initialize()
            val started = CompletableDeferred<Unit>()
            val release = CompletableDeferred<Unit>()
            val delayed = async {
                started.complete(Unit); release.await()
                stale { old.add("basic-banana", 100.0, MealType.LUNCH, today, "late") }
            }
            started.await()
            owners.select(b.id)
            release.complete(Unit); delayed.await()
            val fresh = DiaryRepository(db, context, owners.select(a.id))
            stale { old.setProfile("Nieaktualne", 180.0, ActivityClass.LINE, DietAim.REDUCE) }
            stale { old.addWeight(80.0, today, "stale-weight") }
            stale { old.setGoal(3000.0, null, null, null) }
            stale { old.setDayComplete(today, false) }
            fresh.add("basic-banana", 100.0, MealType.LUNCH, today, "fresh")
            assertNull(db.dao().meal("late", a.storageScope))
            assertNull(db.dao().currentProfile(a.storageScope))
            assertNull(db.dao().weight("stale-weight", a.storageScope))
            assertEquals(1, db.dao().operationCount(a.storageScope))
            assertEquals(0, db.dao().operationCount(b.storageScope))
            assertEquals("fresh", db.dao().day(a.storageScope, today.toString()).first().single().meal.id)
        } finally { db.close() }
    }

    @Test fun accountQueueFailureRollsBackPrivateDraftAndMealTogether() = runBlocking {
        val db = memory()
        try {
            val owners = LocalOwnerStore(db)
            val account = owners.registerIdentity("https://identity.example", "A")
            val repo = DiaryRepository(db, context, owners.select(account.id))
            repo.initialize()
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_account_queue BEFORE INSERT ON outbox WHEN NEW.entityType = 'meal' BEGIN SELECT RAISE(ABORT, 'queue failure'); END")
            rejects { repo.addCustomProduct(CustomProductDraft("Wycofany", 100.0, null, null, null, "Przepis"),
                100.0, MealType.LUNCH, today, "rolled-back-meal", "rolled-back-product") }
            assertNull(db.dao().product("rolled-back-product", repo.owner))
            assertNull(db.dao().meal("rolled-back-meal", repo.owner))
            assertEquals(0, db.dao().operationCount(repo.owner))
            assertEquals(owners.currentLease().storageScope, repo.owner)
        } finally { db.close() }
    }

    @Test fun activeOwnerGenerationAndGuestLogsSurviveDatabaseReopening() = runBlocking {
        val name = "owners-${UUID.randomUUID()}.db"
        var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).build()
        try {
            var owners = LocalOwnerStore(db)
            val guest = owners.ensureGuest()
            val guestRepo = DiaryRepository(db, context)
            guestRepo.initialize()
            guestRepo.add("basic-banana", 100.0, MealType.LUNCH, today, "guest-persist")
            val account = owners.registerIdentity("https://identity.example", "A")
            val lease = owners.select(account.id)
            DiaryRepository(db, context, lease).addWeight(80.0, today, "account-persist")
            db.close()
            db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).build()
            owners = LocalOwnerStore(db)
            assertEquals(guest, owners.ensureGuest())
            assertEquals(account, owners.registerIdentity("https://identity.example", "A"))
            assertEquals(lease, owners.currentLease())
            stale { DiaryRepository(db, context).add("basic-banana", 100.0, MealType.LUNCH, today, "wrong-default") }
            assertEquals(80.0, db.dao().weights(account.storageScope).first().single().kg, 0.0)
            assertEquals(1, db.dao().operationCount(account.storageScope))
            DiaryRepository(db, context, owners.select(guest.id)).add("basic-banana", 100.0, MealType.LUNCH, today, "guest-after")
            assertEquals(2, db.dao().day(guest.storageScope, today.toString()).first().size)
            assertEquals(2, db.dao().operationCount(guest.storageScope))
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun migrationFromActualV4PreservesEveryOldColumnSnapshotAndQueueStatus() = runBlocking {
        val name = "migration-v4-${UUID.randomUUID()}.db"
        val schema = JSONObject(InstrumentationRegistry.getInstrumentation().context.assets
            .open("pl.roseru.kalorie.data.CalorieDatabase/4.json").bufferedReader().use { it.readText() }).getJSONObject("database")
        val entities = schema.getJSONArray("entities").objects()
        val queries = entities.associate { row -> row.getString("tableName") to
            "SELECT " + row.getJSONArray("fields").objects().joinToString(",") { "`${it.getString("columnName")}`" } +
            " FROM `${row.getString("tableName")}` ORDER BY 1, 2" }
        val expected = mutableMapOf<String, List<List<String?>>>()
        val fixture = memory()
        try {
            val repo = DiaryRepository(fixture, context); repo.initialize()
            repo.addCustomProduct(CustomProductDraft("Zachowany", 100.123456789, null, 0.0, 3.0, "Przepis"),
                12.5, MealType.LUNCH, today, "private-meal", "private-product")
            val ration = fixture.dao().rations().first().single { it.ration.catalogJson != null }
            val part = ration.components.minBy { it.position }
            repo.addRation(ration.ration.id, mapOf(part.id to 100.0), MealType.DINNER, today, "exact-meal")
            repo.add("basic-banana", 100.0, MealType.LUNCH, today, "tombstone"); repo.delete("tombstone")
            repo.setGoal(2900.0, null, 90.0, 300.0)
            repo.setProfile("Poligon", 182.5, ActivityClass.LINE, DietAim.REDUCE)
            repo.addWeight(82.4, today, "weight"); repo.addWeight(82.1, today, "deleted-weight"); repo.deleteWeight("deleted-weight")
            repo.setDayComplete(today, true)
            val source = fixture.openHelper.writableDatabase
            source.execSQL("UPDATE outbox SET status = 'acked' WHERE action = 'delete'")
            source.execSQL("UPDATE meals SET serverRevision = 4, localRevision = 7 WHERE id = 'exact-meal'")
            val file = context.getDatabasePath(name); file.parentFile!!.mkdirs()
            SQLiteDatabase.openOrCreateDatabase(file, null).use { old ->
                entities.forEach { row ->
                    fun resolve(sql: String) = sql.replace("\${TABLE_NAME}", row.getString("tableName"))
                    old.execSQL(resolve(row.getString("createSql")))
                    row.optJSONArray("indices")?.objects()?.forEach { old.execSQL(resolve(it.getString("createSql"))) }
                }
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY, identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42, ?)", arrayOf(schema.getString("identityHash")))
                queries.forEach { (table, query) ->
                    source.query(query).use { cursor ->
                        while (cursor.moveToNext()) {
                            val values: Array<Any?> = (0 until cursor.columnCount).map { index -> when (cursor.getType(index)) {
                                Cursor.FIELD_TYPE_NULL -> null
                                Cursor.FIELD_TYPE_INTEGER -> cursor.getLong(index)
                                Cursor.FIELD_TYPE_FLOAT -> cursor.getDouble(index)
                                Cursor.FIELD_TYPE_BLOB -> cursor.getBlob(index)
                                else -> cursor.getString(index)
                            } }.toTypedArray()
                            val columns = cursor.columnNames.joinToString(",") { "`$it`" }
                            old.execSQL("INSERT INTO `$table` ($columns) VALUES (${values.joinToString(",") { "?" }})", values)
                        }
                    }
                    expected[table] = old.rawQuery(query, null).use(::rows)
                    assertTrue("Fixture table $table must be populated", expected.getValue(table).isNotEmpty())
                }
                old.version = 4
            }
        } finally { fixture.close() }
        val db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addMigrations(MIGRATION_4_5).build()
        try {
            val sql = db.openHelper.readableDatabase
            queries.forEach { (table, query) -> assertEquals(table, expected.getValue(table), sql.query(query).use(::rows)) }
            val owners = LocalOwnerStore(db)
            val guest = owners.ensureGuest(); UUID.fromString(guest.id)
            assertEquals("guest", guest.storageScope)
            assertEquals(OwnerLease("guest", 1), owners.currentLease())
            assertNotNull(db.dao().meal("exact-meal", "guest")!!.items.single().snapshotJson)
            assertTrue(db.dao().meal("tombstone", "guest")!!.meal.deleted)
            assertTrue(db.dao().weight("deleted-weight", "guest")!!.deleted)
            assertEquals(5, sql.version)
            assertFalse(sql.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
            DiaryRepository(db, context).initialize()
            assertEquals(expected.getValue("outbox"), sql.query(queries.getValue("outbox")).use(::rows))
        } finally { db.close(); context.deleteDatabase(name) }
    }

    private fun rows(cursor: Cursor): List<List<String?>> = buildList {
        while (cursor.moveToNext()) add((0 until cursor.columnCount).map { if (cursor.isNull(it)) null else cursor.getString(it) })
    }
}
