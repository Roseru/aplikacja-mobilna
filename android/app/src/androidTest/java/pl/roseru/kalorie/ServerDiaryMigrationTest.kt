package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

class ServerDiaryMigrationTest {
    @Test fun actualRoom16MigrationPreservesAllOldColumnsAndRowidsAndSupportsMissingHeight()=runBlocking<Unit> {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val source=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val name="diary-migration-${UUID.randomUUID()}";var target:CalorieDatabase?=null
        try {
            LocalOwnerStore(source).ensureGuest();val lease=LocalOwnerStore(source).currentLease()
            val repo=DiaryRepository(source,context,lease);repo.initialize()
            repo.setProfile("Synthetic",177.125,ActivityClass.LINE,DietAim.MAINTAIN)
            repo.addCustomProduct(CustomProductDraft("Synthetic bar",321.125,null,8.5,null,"Synthetic label"),
                75.125,MealType.SNACK,LocalDate.of(2026,10,21))
            repo.addWeight(81.123456,LocalDate.of(2026,10,21))
            val schema=InstrumentationRegistry.getInstrumentation().context.assets
                .open("pl.roseru.kalorie.data.CalorieDatabase/16.json").use{JSONObject(String(it.readBytes())).getJSONObject("database")}
            val entities=schema.getJSONArray("entities")
            fun dump(query:(String)->android.database.Cursor)=buildMap<String,List<List<String?>>>{
                for(i in 0 until entities.length()) {
                    val e=entities.getJSONObject(i);val fields=e.getJSONArray("fields")
                    val columns="rowid,"+(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                    put(e.getString("tableName"),query("SELECT $columns FROM `${e.getString("tableName")}` ORDER BY rowid").use{c->buildList{
                        while(c.moveToNext())add((0 until c.columnCount).map{column->when{
                            c.isNull(column)->null
                            c.getType(column)==android.database.Cursor.FIELD_TYPE_FLOAT->c.getDouble(column).toString()
                            else->c.getString(column)
                        }})
                    }})
                }
            }
            val values=dump{source.openHelper.readableDatabase.query(it)}
            context.getDatabasePath(name).parentFile!!.mkdirs()
            var before=emptyMap<String,List<List<String?>>>()
            android.database.sqlite.SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name),null).use{old->
                old.execSQL("PRAGMA foreign_keys=OFF")
                for(i in 0 until entities.length()) {
                    val e=entities.getJSONObject(i);val table=e.getString("tableName")
                    old.execSQL(e.getString("createSql").replace("\${TABLE_NAME}",table))
                    val indices=e.optJSONArray("indices")?:JSONArray()
                    for(j in 0 until indices.length())old.execSQL(indices.getJSONObject(j).getString("createSql").replace("\${TABLE_NAME}",table))
                    val fields=e.getJSONArray("fields")
                    val columns="rowid,"+(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                    val marks=(0..fields.length()).joinToString(","){"?"}
                    values.getValue(table).forEach{old.execSQL("INSERT INTO `$table` ($columns) VALUES ($marks)",it.toTypedArray())}
                }
                old.execSQL("UPDATE profiles SET rowid=501")
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(schema.getString("identityHash")));old.version=16
                before=dump{old.rawQuery(it,null)}
            }
            target=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addMigrations(MIGRATION_16_17).addCallback(DATABASE_GUARDS).build()
            val sql=target!!.openHelper.readableDatabase
            assertEquals(17,sql.version);assertEquals(before,dump{sql.query(it)})
            assertFalse(sql.query("PRAGMA foreign_key_check").use{it.moveToFirst()})
            assertTrue(target!!.serverDiaryDao().records(lease.storageScope).isEmpty());assertNull(target!!.serverDiaryDao().latest(lease.storageScope))
            assertFalse(sql.query("SELECT 1 FROM products WHERE wirePayload IS NOT NULL").use{it.moveToFirst()})
            assertEquals(177.125,target!!.dao().currentProfile(lease.storageScope)!!.heightCm!!,0.0)
            sql.execSQL("UPDATE profiles SET heightCm=NULL")
            assertNull(target!!.dao().currentProfile(lease.storageScope)!!.heightCm)
            var immutable=false
            try{sql.execSQL("UPDATE goals SET kcal=1")}catch(_:Exception){immutable=true}
            assertTrue(immutable)
        }finally{target?.close();source.close();context.deleteDatabase(name)}
    }
}
