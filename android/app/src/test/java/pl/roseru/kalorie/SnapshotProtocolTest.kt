package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.sync.*
import java.net.URLDecoder

class SnapshotProtocolTest {
    private fun bytes(name: String) = javaClass.getResourceAsStream("/sync/$name")!!.use { it.readBytes() }
    private val protocol = SnapshotProtocol(SyncWireSchema(SyncWireSchema.FILES.associateWith(::bytes)))
    private val epoch = "00000000-0000-4000-8000-000000000064"
    private fun page() = JSONObject(String(bytes("sync-pull-response.json"))).put("mode", "snapshot").put("snapshot_token", "snapshot+/?=&ż")
    private fun read(value: JSONObject, query: SnapshotQuery = protocol.query(epoch)) = protocol.response(query, value.toString().toByteArray())
    @Test fun fullSnapshotContinuationAndFinalCheckpointHaveSeparateQueries() {
        val start = protocol.query(epoch)
        read(page().put("page_token", "next").put("checkpoint", JSONObject.NULL), start)
        val continuation = protocol.query(epoch, snapshot = "snapshot+/?=&ż", page = "next")
        read(page(), continuation)
        val pairs = continuation.encoded().split('&').associate { part ->
            val pieces = part.split('=', limit = 2); pieces[0] to URLDecoder.decode(pieces[1], "UTF-8") }
        assertEquals(setOf("sync_epoch", "limit", "snapshot_token", "page_token"), pairs.keys)
        assertEquals("snapshot+/?=&ż", pairs["snapshot_token"])
        assertFalse(continuation.toString().contains("snapshot+"))
    }
    @Test fun wrongModeEpochTokenAndRepeatedNextTokenAreRejected() {
        assertThrows(IllegalArgumentException::class.java) { read(page().put("mode", "incremental").put("snapshot_token", JSONObject.NULL)) }
        assertThrows(IllegalArgumentException::class.java) { read(page().put("sync_epoch", "a1111111-1111-4111-8111-111111111111")) }
        val query = protocol.query(epoch, snapshot = "other", page = "next")
        assertThrows(IllegalArgumentException::class.java) { read(page(), query) }
        assertThrows(IllegalArgumentException::class.java) { read(page().put("snapshot_token", "other").put("page_token", "next").put("checkpoint", JSONObject.NULL), query) }
    }
    @Test fun aggregateLimitAndDuplicateEntitiesAreRejected() {
        val value = page(); val entity = value.getJSONArray("entities").getJSONObject(0)
        value.getJSONArray("entities").put(entity)
        assertThrows(IllegalArgumentException::class.java) { read(value) }
        entity.put("entity_id", "a1111111-1111-4111-8111-111111111111")
        val two = page(); two.getJSONArray("entities").put(entity)
        assertThrows(IllegalArgumentException::class.java) { read(two, protocol.query(epoch, 1)) }
    }
    @Test fun syncErrorObjectCannotBeConfusedWithBootstrapErrorArray() {
        val value = JSONObject().put("code", "snapshot_expired").put("message", "fixture").put("details", JSONObject())
            .put("request_id", "a1111111-1111-4111-8111-111111111111")
        assertEquals("snapshot_expired", protocol.errorCode(value.toString().toByteArray()))
        value.put("details", JSONArray())
        assertThrows(IllegalArgumentException::class.java) { protocol.errorCode(value.toString().toByteArray()) }
    }
    @Test fun unpairedTokensAndOversizedResponsesAreRejected() {
        assertThrows(IllegalArgumentException::class.java) { protocol.query(epoch, page = "next") }
        assertThrows(IllegalArgumentException::class.java) { protocol.query(epoch, snapshot = "snap") }
        assertThrows(IllegalArgumentException::class.java) { protocol.query(epoch, 501) }
        assertThrows(IllegalArgumentException::class.java) { protocol.response(protocol.query(epoch), ByteArray(SnapshotProtocol.MAX_BYTES + 1)) }
    }
}
