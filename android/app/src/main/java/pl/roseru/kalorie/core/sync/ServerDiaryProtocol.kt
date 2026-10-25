package pl.roseru.kalorie.core.sync

import pl.roseru.kalorie.core.catalog.StrictJson
import java.util.Collections
import pl.roseru.kalorie.energy.EnergySchema
import pl.roseru.kalorie.energy.EnergyProtocol
import pl.roseru.kalorie.energy.EnergyVersion

/** Input from a completed archive, captured together with its account binding by Room. */
internal class ArchivedDiaryPage(val query: String, val response: String) {
    override fun toString() = "ArchivedDiaryPage(redacted)"
}

internal class ServerDiaryEntity(val id: String, val type: String, val revision: Int,
    val deleted: Boolean, val payload: String?) {
    override fun toString() = "ServerDiaryEntity(redacted)"
}

/** A full validated copy is a read source, never proof that a pending operation was accepted. */
internal class ServerDiarySnapshot(val epoch: String, val checkpoint: String,
    val serverTime: String, val firstServerTime: String, val timelineRevision: Int,
    entities: List<ServerDiaryEntity>, val mappings:List<String> = emptyList(), val receipts:List<String> = emptyList(),
    energyVersions:List<EnergyVersion> = emptyList(),val protocolScope:SyncProtocolScope=SyncProtocolScope.LEGACY) {
    val entities: List<ServerDiaryEntity> = Collections.unmodifiableList(entities.toList())
    val energyVersions:List<EnergyVersion> = Collections.unmodifiableList(energyVersions.toList())
    override fun toString() = "ServerDiarySnapshot(redacted)"
}

/** Validate the entire immutable archive before constructing any local diary mutations.
 * Ownership, recovery, active-run and later-local-edit fences belong to the Room commit.
 */
internal class ServerDiaryProtocol(private val schema: SyncWireSchema,private val energySchema:EnergySchema?=null) {
    private val snapshots = SnapshotProtocol(schema,energySchema)

    fun read(epoch: String, pages: List<ArchivedDiaryPage>,scope:SyncProtocolScope=SyncProtocolScope.LEGACY): ServerDiarySnapshot = safe {
        require(pages.size in 1..2000)
        var totalBytes = 0L
        var totalRecords = 0
        val firstBytes = pages.first().query.toByteArray(Charsets.UTF_8)
        schema.validate(firstBytes, "PullRequest")
        val firstQuery = StrictJson.read(firstBytes)
        val limit = firstQuery.getInt("limit")
        val recoveryIds=firstQuery.optJSONArray("recovery_operation_ids")?.let {rows ->
            (0 until rows.length()).map {rows.getString(it)} } ?: emptyList()
        var expected = snapshots.query(epoch, limit, recoveryOperationIds=recoveryIds,scope=scope)
        val seenQueries = mutableSetOf<String>()
        val identities = SnapshotProtocol.IDENTITIES.mapValues { mutableSetOf<String>() }
        val entities = mutableListOf<ServerDiaryEntity>()
        val energyVersions=mutableListOf<EnergyVersion>()
        val mappings=mutableListOf<String>(); val receipts=mutableListOf<String>()
        var timeline: Int? = null
        var firstTime: String? = null
        var lastTime: String? = null
        var checkpoint: String? = null
        for ((index, archived) in pages.withIndex()) {
            val queryBytes = archived.query.toByteArray(Charsets.UTF_8)
            schema.validate(queryBytes, "PullRequest")
            val query = StrictJson.canonical(StrictJson.read(queryBytes))
            // This also excludes incremental cursors and an archive that starts midway.
            require(query == expected.canonical && seenQueries.add(query))
            val bytes = archived.response.toByteArray(Charsets.UTF_8)
            totalBytes = Math.addExact(totalBytes, bytes.size.toLong())
            require(totalBytes <= 64L * 1_048_576)
            val value = snapshots.response(expected, bytes).json()
            val revision = value.getLong("goal_timeline_revision")
            require(revision in 0..Int.MAX_VALUE.toLong())
            if (timeline == null) timeline = revision.toInt() else require(timeline == revision.toInt())
            if (firstTime == null) firstTime = value.getString("server_time")
            lastTime = value.getString("server_time")
            for ((field, keys) in SnapshotProtocol.IDENTITIES) {
                val rows = value.getJSONArray(field)
                totalRecords = Math.addExact(totalRecords, rows.length())
                require(totalRecords <= 100_000)
                for (i in 0 until rows.length()) {
                    val row = rows.getJSONObject(i)
                    val identity = keys.joinToString(":") { row.getString(it) }
                    require(identities.getValue(field).add(identity))
                    if(field=="recovery_mappings")mappings+=StrictJson.canonical(row)
                    if(field=="operation_receipts") {
                        require(row.getString("operation_id") in recoveryIds)
                        receipts+=StrictJson.canonical(row)
                    }
                    if (field != "entities") continue // Typed evidence is separate; no ACK here.
                    val type = row.getString("entity_type")
                    if(type=="energy_estimate") {
                        require(scope==SyncProtocolScope.ENERGY_V1)
                        energyVersions+=EnergyProtocol(checkNotNull(energySchema)).version(row)
                        continue
                    }
                    val deleted = row.getBoolean("deleted")
                    val payload = if (deleted) null else StrictJson.canonical(row.getJSONObject("payload"))
                    if (payload != null) when (type) {
                        "meal" -> MealWire.read(payload, schema)
                        "weight" -> WeightWire.read(payload, schema)
                        "profile", "goal", "diary_day", "product_draft" -> ServerDiaryValues.validate(type, payload)
                        else -> error("Unsupported diary entity")
                    }
                    val entityRevision = row.getLong("revision")
                    require(entityRevision in 1..Int.MAX_VALUE.toLong())
                    entities += ServerDiaryEntity(row.getString("entity_id"), type, entityRevision.toInt(), deleted, payload)
                }
            }
            val complete = value.isNull("page_token")
            if (index == pages.lastIndex) {
                require(complete && !value.isNull("checkpoint"))
                checkpoint = value.getString("checkpoint")
            } else {
                require(!complete && value.isNull("checkpoint"))
                expected = snapshots.query(epoch, limit, value.getString("snapshot_token"), value.getString("page_token"),scope=scope)
            }
        }
        ServerDiaryValues.validateSnapshot(entities, checkNotNull(timeline))
        require(energyVersions.map {it.revision}.distinct().size==energyVersions.size)
        val byId=energyVersions.associateBy {it.id}
        for(version in energyVersions)version.supersedes?.let {id->
            require(byId[id]?.let {it.revision<version.revision}==true)
        }
        ServerDiarySnapshot(epoch, checkNotNull(checkpoint), checkNotNull(lastTime), checkNotNull(firstTime),
            checkNotNull(timeline), entities, mappings.toList(), receipts.toList(),energyVersions,scope)
    }

    private inline fun <T> safe(action: () -> T): T = try { action() }
        catch (_: Exception) { throw SyncWireException() }
}
