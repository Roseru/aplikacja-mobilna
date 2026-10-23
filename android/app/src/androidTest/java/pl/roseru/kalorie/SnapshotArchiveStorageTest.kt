package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.data.*
import java.util.UUID

class SnapshotArchiveStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val epoch="55555555-5555-4555-8555-555555555555"
    @Test fun repeatedSuccessfulFullCopiesDoNotStopAtNinth()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val owners=LocalOwnerStore(db);owners.ensureGuest()
            val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/archive",UUID.randomUUID().toString()).id)
            val boot=AccountBootstrapStore(db)
            boot.apply(boot.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),epoch,1,"2026-10-23T12:00:00Z"))
            val snapshots=ServerSnapshotStore(db,SnapshotProtocol(CanonicalMealRows.schema(context)))
            repeat(12) {index->
                val request=snapshots.begin(lease)
                val page=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-snapshot-$index")
                    .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-checkpoint-$index").put("server_time","2026-10-23T12:00:00Z")
                    .put("goal_timeline_revision",0).put("entities",JSONArray()).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
                assertNull(snapshots.apply(request,page.toString().toByteArray()))
                assertEquals(request.runId,snapshots.active(lease)!!.id)
            }
            assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
        } finally {db.close()}
    }
}