package pl.roseru.kalorie

import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import java.time.*
import java.util.UUID

class AchievementStorageTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val today = LocalDate.of(2026, 10, 12)
    private fun clock(at: Instant = Instant.parse("2026-10-12T12:00:00Z")) = LocalDayClock({ at }, { ZoneOffset.UTC })
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun preview(db: CalorieDatabase, owner: String = "guest", clock: LocalDayClock = clock()) =
        (AchievementRepository(db, clock).observe(owner).first { it is AchievementState.Ready } as AchievementState.Ready).preview
    private fun AchievementPreview.badge(code: AchievementCode) = badges.single { it.code == code }
    private suspend fun day(db: CalorieDatabase, date: LocalDate, id: String, owner: String = "guest", deleted: Boolean = false) {
        db.dao().insertMeal(MealEntity(id, owner, date.toString(), date.atTime(12, 0).toInstant(ZoneOffset.UTC).toString(), "UTC", "LUNCH", deleted = deleted))
        db.dao().insertItem(MealItemEntity("$id-item", id, "source", "Synthetic", 100.0, 2000.0, null, null, null))
        db.dao().saveDiaryDay(DiaryDayEntity("$id-day", owner, date.toString(), true, 1))
    }

    @Test fun fullHistoryKeepsOldWitnessAndExcludesOtherOwnerAndTombstonesWithoutQueueWrites() = runBlocking<Unit> {
        val db = memory()
        try {
            val old = (10L downTo 1L).map { today.minusYears(1).minusDays(it) }
            old.forEachIndexed { index, date -> day(db, date, "old-$index") }
            (10L downTo 1L).forEach { day(db, today.minusDays(it), "other-$it", "other") }
            day(db, today.minusDays(1), "deleted", deleted = true)
            day(db, today.plusDays(1), "future")
            db.dao().saveGoal(GoalEntity("goal", "guest", "2020-01-01", 2000.0, null, null, null))
            val result = preview(db)
            assertEquals(old, result.badge(AchievementCode.COMPLETE_STREAK).witness)
            assertEquals(old, result.badge(AchievementCode.IN_GOAL_STREAK).witness)
            assertEquals(0, db.dao().operationCount("guest"))
            assertEquals(emptyList<LocalDate>(), preview(db, "empty-owner").badge(AchievementCode.COMPLETE_STREAK).witness)
            assertEquals(0, preview(db, "other").badge(AchievementCode.IN_GOAL_STREAK).progress)
        } finally { db.close() }
    }

    @Test fun liveCorrectionRevokesWitnessAndRestartPreservesRecalculatedResultAndQueue() = runBlocking<Unit> {
        val name = "achievement-${UUID.randomUUID()}.db"
        var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        try {
            val dates = (10L downTo 1L).map(today::minusDays)
            dates.forEachIndexed { index, date -> day(db, date, "day-$index") }
            val states = Channel<AchievementPreview>(Channel.UNLIMITED)
            val job = launch { AchievementRepository(db, clock()).observe("guest").filterIsInstance<AchievementState.Ready>().collect { states.send(it.preview) } }
            suspend fun awaitState(check: (AchievementPreview) -> Boolean) = withTimeout(15_000) {
                var state = states.receive(); while (!check(state)) state = states.receive(); state
            }
            try {
                awaitState { it.badge(AchievementCode.COMPLETE_STREAK).satisfied }
                val declaration = db.dao().currentDiaryDay("guest", dates[4].toString())!!
                db.dao().saveDiaryDay(declaration.copy(declaredComplete = false, localRevision = 2))
                assertEquals(5, awaitState { !it.badge(AchievementCode.COMPLETE_STREAK).satisfied }.badge(AchievementCode.COMPLETE_STREAK).progress)
                db.dao().saveDiaryDay(declaration.copy(localRevision = 3))
                awaitState { it.badge(AchievementCode.COMPLETE_STREAK).satisfied }
                val meal = db.dao().meal("day-4", "guest")!!
                db.dao().updateMeal(meal.meal.copy(deleted = true))
                awaitState { !it.badge(AchievementCode.COMPLETE_STREAK).satisfied }
            } finally { job.cancelAndJoin(); states.close() }
            db.close(); db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            assertFalse(preview(db).badge(AchievementCode.COMPLETE_STREAK).satisfied)
            assertEquals(0, db.dao().operationCount("guest"))
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun clockTickMaturesSourceZoneEvenWhenDeviceCalendarDateDoesNotChange() = runBlocking<Unit> {
        val db = memory()
        var at = Instant.parse("2026-10-12T09:59:59Z")
        val tick = Channel<Unit>(Channel.UNLIMITED)
        val testClock = LocalDayClock({ at }, { ZoneOffset.UTC }, { tick.receive() })
        try {
            db.dao().saveWeight(WeightEntity("one", "guest", today.toString(), at.toString(), "Pacific/Kiritimati", 80.0))
            val states = Channel<AchievementPreview>(Channel.UNLIMITED)
            val job = launch { AchievementRepository(db, testClock).observe("guest").filterIsInstance<AchievementState.Ready>().collect { states.send(it.preview) } }
            suspend fun next(check: (AchievementPreview) -> Boolean) = withTimeout(15_000) {
                var state = states.receive(); while (!check(state)) state = states.receive(); state
            }
            try {
                next { it.badge(AchievementCode.WEIGHT_DAYS).progress == 0 }
                at = Instant.parse("2026-10-12T10:00:00Z"); tick.send(Unit)
                val mature = next { it.badge(AchievementCode.WEIGHT_DAYS).progress == 1 }
                assertEquals(today, mature.asOf.atZone(ZoneOffset.UTC).toLocalDate())
                val point = db.dao().weight("one", "guest")!!
                db.dao().saveWeight(point.copy(deleted = true))
                next { it.badge(AchievementCode.WEIGHT_DAYS).progress == 0 }
            } finally { job.cancelAndJoin(); states.close() }
        } finally { db.close(); tick.close() }
    }

    @Test fun rationPositionIsImmutableAcrossQuantityEditsCatalogueChangesAndReopen() = runBlocking<Unit> {
        val name = "ration-achievement-${UUID.randomUUID()}.db"
        var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        try {
            val repo = DiaryRepository(db, context).apply { initialize() }
            val ration = db.dao().rations().first().single { it.ration.id == "demo-ration-a" }
            val part = ration.components.minBy { it.position }
            val date = today.minusDays(1)
            repo.addRation(ration.ration.id, mapOf(part.id to 50.0), MealType.LUNCH, date, "ration")
            val first = db.dao().meal("ration", "guest")!!.items.single()
            assertEquals(1, first.rationComponentPosition)
            db.openHelper.writableDatabase.execSQL("UPDATE ration_components SET position = 99 WHERE id = ?", arrayOf(part.id))
            repo.editItem("ration", first.id, 25.0)
            assertEquals(1, db.dao().meal("ration", "guest")!!.items.single().rationComponentPosition)
            db.openHelper.readableDatabase.query("SELECT payload FROM outbox WHERE entityId = 'ration' AND action = 'update'").use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals(1, JSONObject(cursor.getString(0)).getJSONArray("items").getJSONObject(0).getInt("ration_component_position"))
            }
            assertEquals(1, preview(db).badge(AchievementCode.RATION_DAYS).progress)
            db.close(); db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            assertEquals(1, preview(db).badge(AchievementCode.RATION_DAYS).progress)
            DiaryRepository(db, context).delete("ration")
            assertEquals(0, preview(db).badge(AchievementCode.RATION_DAYS).progress)
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun malformedLocalSourceShowsUnavailableInsteadOfInventingZeroProgress() = runBlocking<Unit> {
        val db = memory()
        try {
            db.dao().saveWeight(WeightEntity("broken", "guest", "broken-date", "2026-10-12T10:00:00Z", "UTC", 80.0))
            assertEquals(AchievementState.Unavailable, AchievementRepository(db, clock()).observe("guest").first { it != AchievementState.Loading })
            db.dao().saveWeight(db.dao().weight("broken", "guest")!!.copy(localDate = today.minusDays(1).toString()))
            assertEquals(1, preview(db).badge(AchievementCode.WEIGHT_DAYS).progress)
        } finally { db.close() }
    }

    @Test fun actualRoomSevenMigrationPreservesAllColumnsInTwentyTwoTablesAndLeavesLegacyPositionUnknown() = runBlocking<Unit> {
        val name = "achievement-migration-${UUID.randomUUID()}.db"
        val schema = JSONObject(InstrumentationRegistry.getInstrumentation().context.assets
            .open("pl.roseru.kalorie.data.CalorieDatabase/7.json").bufferedReader().use { it.readText() }).getJSONObject("database")
        val entities = schema.getJSONArray("entities")
        val queries = (0 until entities.length()).associate { index ->
            val row = entities.getJSONObject(index); val fields = row.getJSONArray("fields")
            row.getString("tableName") to "SELECT " + (0 until fields.length()).joinToString(",") { "`${fields.getJSONObject(it).getString("columnName")}`" } +
                " FROM `${row.getString("tableName")}` ORDER BY 1,2"
        }
        val expected = mutableMapOf<String, List<List<String?>>>()
        val fixture = memory()
        try {
            DiaryRepository(fixture, context).apply { initialize(); add("basic-banana", 100.0, MealType.LUNCH, today.minusDays(1), "keep") }
            fixture.dao().insertMeal(MealEntity("legacy", "guest", today.minusDays(1).toString(), "2026-10-11T12:00:00Z", "UTC", "LUNCH", rationId = "demo-ration-a"))
            fixture.dao().insertItem(MealItemEntity("legacy-item", "legacy", "demo-ration-meat", "Konserwa", 50.0, 273.0, 16.0, 22.0, 2.7, "demo-a-meat"))
            val file = context.getDatabasePath(name); file.parentFile!!.mkdirs()
            SQLiteDatabase.openOrCreateDatabase(file, null).use { old ->
                for (index in 0 until entities.length()) {
                    val row = entities.getJSONObject(index); val table = row.getString("tableName")
                    fun resolve(sql: String) = sql.replace("\${TABLE_NAME}", table)
                    old.execSQL(resolve(row.getString("createSql")))
                    row.optJSONArray("indices")?.let { indices -> for (j in 0 until indices.length()) old.execSQL(resolve(indices.getJSONObject(j).getString("createSql"))) }
                    fixture.openHelper.readableDatabase.query(queries.getValue(table)).use { cursor ->
                        while (cursor.moveToNext()) {
                            val values: Array<Any?> = (0 until cursor.columnCount).map { column -> when (cursor.getType(column)) {
                                Cursor.FIELD_TYPE_NULL -> null; Cursor.FIELD_TYPE_INTEGER -> cursor.getLong(column)
                                Cursor.FIELD_TYPE_FLOAT -> cursor.getDouble(column); else -> cursor.getString(column)
                            } }.toTypedArray()
                            old.execSQL("INSERT INTO `$table` (${cursor.columnNames.joinToString(",") { "`$it`" }}) VALUES (${values.joinToString(",") { "?" }})", values)
                        }
                    }
                    expected[table] = old.rawQuery(queries.getValue(table), null).use(::rows)
                }
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY, identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42, ?)", arrayOf(schema.getString("identityHash")))
                old.version = 7
            }
        } finally { fixture.close() }
        val migrated = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addMigrations(MIGRATION_7_8, pl.roseru.kalorie.photo.MIGRATION_8_9, pl.roseru.kalorie.photo.MIGRATION_9_10, pl.roseru.kalorie.data.MIGRATION_10_11, pl.roseru.kalorie.data.MIGRATION_11_12, pl.roseru.kalorie.photo.MIGRATION_12_13, pl.roseru.kalorie.data.MIGRATION_13_14, pl.roseru.kalorie.data.MIGRATION_14_15, pl.roseru.kalorie.data.MIGRATION_15_16, pl.roseru.kalorie.data.MIGRATION_16_17, pl.roseru.kalorie.data.MIGRATION_17_18, pl.roseru.kalorie.data.MIGRATION_18_19, pl.roseru.kalorie.data.MIGRATION_19_20, pl.roseru.kalorie.data.MIGRATION_20_21, pl.roseru.kalorie.data.MIGRATION_21_22, pl.roseru.kalorie.data.MIGRATION_22_23, pl.roseru.kalorie.data.MIGRATION_23_24, pl.roseru.kalorie.energy.MIGRATION_24_25, pl.roseru.kalorie.data.MIGRATION_25_26).addCallback(DATABASE_GUARDS).build()
        try {
            assertEquals(22, expected.size)
            queries.forEach { (table, query) -> assertEquals(table, expected.getValue(table), migrated.openHelper.readableDatabase.query(query).use(::rows)) }
            assertEquals(26,migrated.openHelper.readableDatabase.version)
            assertNull(migrated.dao().meal("legacy", "guest")!!.items.single().rationComponentPosition)
            assertEquals(1, preview(migrated).legacyRationMeals)
            assertEquals(0, preview(migrated).badge(AchievementCode.RATION_DAYS).progress)
            assertFalse(migrated.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
        } finally { migrated.close(); context.deleteDatabase(name) }
    }

    private fun rows(cursor: Cursor): List<List<String?>> = buildList {
        while (cursor.moveToNext()) add((0 until cursor.columnCount).map { if (cursor.isNull(it)) null else cursor.getString(it) })
    }
}
