package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.sync.*
import java.net.URLDecoder
import java.util.UUID

class SnapshotRecoveryProtocolTest {
    private fun bytes(name: String) = javaClass.getResourceAsStream("/sync/$name")!!.use { it.readBytes() }
    private val protocol = SnapshotProtocol(SyncWireSchema(SyncWireSchema.FILES.associateWith(::bytes)))
    private val epoch = "00000000-0000-4000-8000-000000000064"
    private fun uuid() = UUID.randomUUID().toString()
    private fun pairs(query: SnapshotQuery) = query.encoded().split('&').map { part ->
        val pieces = part.split('=', limit = 2)
        URLDecoder.decode(pieces[0], "UTF-8") to URLDecoder.decode(pieces[1], "UTF-8")
    }
    private fun page() = JSONObject(String(bytes("sync-pull-response.json"))).put("mode", "snapshot").put("snapshot_token", "opaque+/?=&ż😀")

    @Test fun recoveryIdsUseRepeatedQueryKeysAndRetainTheirExactOrder() {
        val ids = listOf(uuid(), uuid(), uuid())
        val query = protocol.query(epoch, recoveryOperationIds = ids)
        val encoded = pairs(query)
        assertEquals(ids, encoded.filter { it.first == "recovery_operation_ids" }.map { it.second })
        assertEquals(listOf("limit" to "100", "sync_epoch" to epoch), encoded.filter { it.first != "recovery_operation_ids" })
        assertFalse(query.encoded().contains("%5B"))
        assertFalse(query.toString().contains(ids.first()))
    }
    @Test fun omittedAndEmptyIdsPreserveOriginalQueryAndDetachedInputCannotChangeIt() {
        assertEquals(protocol.query(epoch).encoded(), protocol.query(epoch, recoveryOperationIds = emptyList()).encoded())
        val ids = mutableListOf(uuid()); val first = ids.single()
        val query = protocol.query(epoch, recoveryOperationIds = ids)
        ids[0] = uuid(); ids.add(uuid())
        assertEquals(listOf(first), pairs(query).filter { it.first == "recovery_operation_ids" }.map { it.second })
    }
    @Test fun duplicateMalformedAndOverLimitIdsCannotProduceAQuery() {
        val id = uuid()
        for (ids in listOf(listOf(id, id), listOf(""), listOf("not-a-uuid"), (1..101).map { uuid() })) {
            assertThrows(IllegalArgumentException::class.java) { protocol.query(epoch, recoveryOperationIds = ids) }
        }
        assertEquals(100, pairs(protocol.query(epoch, recoveryOperationIds = (1..100).map { uuid() }))
            .count { it.first == "recovery_operation_ids" })
    }
    @Test fun onlyFirstFullSnapshotQueryCanCarryRecoveryIds() {
        val ids = listOf(uuid())
        for ((snapshot, page) in listOf("snapshot" to "page", null to "page", "snapshot" to null)) {
            assertThrows(IllegalArgumentException::class.java) {
                protocol.query(epoch, snapshot = snapshot, page = page, recoveryOperationIds = ids)
            }
        }
        val continuation = protocol.query(epoch, snapshot = "opaque+/?=&ż😀", page = "next")
        val query = pairs(continuation).toMap()
        assertEquals("opaque+/?=&ż😀", query["snapshot_token"])
        assertFalse(query.containsKey("recovery_operation_ids"))
    }
    @Test fun receiptsAndMappingsShareThePageLimitAndMalformedLaterReceiptRejectsPage() {
        val id = uuid(); val source = uuid()
        val value = page().put("entities", JSONArray()).put("recovery_mappings", JSONArray().put(JSONObject()
            .put("source_epoch", source).put("source_entity_id", uuid()).put("target_entity_id", uuid()).put("target_revision", 1)))
            .put("operation_receipts", JSONArray().put(JSONObject().put("source_epoch", source)
                .put("operation_id", id).put("entity_id", uuid()).put("status", "accepted").put("revision", 1).put("code", JSONObject.NULL)))
        val query = protocol.query(epoch, limit = 2, recoveryOperationIds = listOf(id))
        protocol.response(query, value.toString().toByteArray())
        assertThrows(IllegalArgumentException::class.java) {
            protocol.response(protocol.query(epoch, limit = 1, recoveryOperationIds = listOf(id)), value.toString().toByteArray())
        }
        value.getJSONArray("operation_receipts").getJSONObject(0).put("revision", 0)
        var result: SnapshotPage? = null
        assertThrows(IllegalArgumentException::class.java) { result = protocol.response(query, value.toString().toByteArray()) }
        assertNull(result)
    }
    @Test fun duplicateReceiptIdentityCannotBeHiddenByDifferentRevision() {
        val id = uuid(); val source = uuid()
        val receipt = JSONObject().put("source_epoch", source).put("operation_id", id).put("entity_id", uuid())
            .put("status", "accepted").put("revision", 1).put("code", JSONObject.NULL)
        val value = page().put("entities", JSONArray()).put("operation_receipts", JSONArray()
            .put(receipt).put(JSONObject(receipt.toString()).put("revision", 2)))
        assertThrows(IllegalArgumentException::class.java) {
            protocol.response(protocol.query(epoch, recoveryOperationIds = listOf(id)), value.toString().toByteArray())
        }
    }
}