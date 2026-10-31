package pl.roseru.kalorie.core.sync

import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.energy.EnergyProtocol
import pl.roseru.kalorie.energy.EnergySchema
import pl.roseru.kalorie.energy.EnergyVersion
import java.time.Instant

/** Incremental change log, folded over one already applied, same-scope server copy.
 * Repeated entity IDs are ordered revisions here, unlike ambiguous full-snapshot duplicates.
 * A change never acknowledges a local outbox operation or makes absence mean deletion.
 */
internal class IncrementalDiaryProtocol(private val schema:SyncWireSchema,private val energySchema:EnergySchema) {
    fun response(query:SnapshotQuery,bytes:ByteArray):SnapshotPage {
        require(query.protocolScope==SyncProtocolScope.ENERGY_V1)
        val request=query.json()
        require(request.has("checkpoint") && !request.has("snapshot_token") && !request.has("recovery_operation_ids"))
        val value=energySchema.read(bytes,"EnergyPullResponse",SnapshotProtocol.MAX_BYTES)
        require(value.getString("mode")=="incremental" && value.getString("sync_epoch")==request.getString("sync_epoch") &&
            value.isNull("snapshot_token") && value.getJSONArray("operation_receipts").length()==0)
        require(SnapshotProtocol.IDENTITIES.keys.sumOf {value.getJSONArray(it).length()}<=request.getInt("limit"))
        if(!value.isNull("page_token"))require(value.getString("page_token")!=request.optString("page_token"))
        return SnapshotPage(StrictJson.canonical(value),query.protocolScope)
    }

    fun read(epoch:String,pages:List<ArchivedDiaryPage>,base:ServerDiarySnapshot,checkpoint:String):ServerDiarySnapshot=try {
        require(base.epoch==epoch && base.checkpoint==checkpoint && base.protocolScope==SyncProtocolScope.ENERGY_V1 && pages.size in 1..2000)
        val snapshots=SnapshotProtocol(schema,energySchema)
        val first=StrictJson.read(pages.first().query.toByteArray(Charsets.UTF_8))
        schema.validate(pages.first().query.toByteArray(Charsets.UTF_8),"PullRequest")
        val limit=first.getInt("limit")
        var expected=snapshots.incrementalQuery(epoch,checkpoint,limit)
        val queries=mutableSetOf<String>()
        val entities=base.entities.associateBy {it.id}.toMutableMap()
        require(entities.size==base.entities.size)
        val versions=base.energyVersions.associateBy {it.id}.toMutableMap()
        val revisionIds=base.energyVersions.associate {it.revision to it.id}.toMutableMap()
        require(versions.size==base.energyVersions.size && revisionIds.size==versions.size)
        val mappingIds=mutableSetOf<String>();val mappings=mutableListOf<String>()
        var bytesCount=0L;var itemCount=0
        var timeline:Int?=null;var firstTime:String?=null;var lastTime:String?=null;var finalCheckpoint:String?=null
        for((index,page) in pages.withIndex()) {
            schema.validate(page.query.toByteArray(Charsets.UTF_8),"PullRequest")
            val query=StrictJson.canonical(StrictJson.read(page.query.toByteArray(Charsets.UTF_8)))
            require(query==expected.canonical && queries.add(query))
            val bytes=page.response.toByteArray(Charsets.UTF_8)
            bytesCount=Math.addExact(bytesCount,bytes.size.toLong())
            require(bytesCount<=64L*1_048_576)
            val value=response(expected,bytes).json()
            val revision=value.getLong("goal_timeline_revision")
            require(revision in base.timelineRevision.toLong()..Int.MAX_VALUE.toLong())
            if(timeline==null)timeline=revision.toInt()else require(timeline==revision.toInt())
            val time=value.getString("server_time")
            require(Instant.parse(time)>=Instant.parse(lastTime?:base.serverTime))
            if(firstTime==null)firstTime=time
            lastTime=time
            itemCount=Math.addExact(itemCount,SnapshotProtocol.IDENTITIES.keys.sumOf {value.getJSONArray(it).length()})
            require(itemCount<=100_000)
            val rows=value.getJSONArray("entities")
            for(i in 0 until rows.length()) {
                val row=rows.getJSONObject(i);val id=row.getString("entity_id");val type=row.getString("entity_type")
                if(type=="energy_estimate") {
                    val version=EnergyProtocol(energySchema).version(row)
                    versions[id]?.let {require(it.wire==version.wire)}
                    revisionIds[version.revision]?.let {require(it==id)}
                    versions[id]=version;revisionIds[version.revision]=id
                    continue
                }
                val deleted=row.getBoolean("deleted")
                val payload=if(deleted)null else StrictJson.canonical(row.getJSONObject("payload"))
                if(payload!=null)when(type) {
                    "meal"->MealWire.read(payload,schema)
                    "weight"->WeightWire.read(payload,schema)
                    "profile","goal","diary_day","product_draft"->ServerDiaryValues.validate(type,payload)
                    else->error("Unsupported incremental entity")
                }
                val entityRevision=row.getLong("revision")
                require(entityRevision in 1..Int.MAX_VALUE.toLong())
                val next=ServerDiaryEntity(id,type,entityRevision.toInt(),deleted,payload)
                entities[id]?.let {old->
                    require(old.type==type && entityRevision>=old.revision && (!old.deleted || deleted))
                    if(entityRevision==old.revision.toLong())require(old.deleted==deleted && old.payload==payload)
                }
                entities[id]=next
            }
            val mapRows=value.getJSONArray("recovery_mappings")
            for(i in 0 until mapRows.length()) {
                val row=mapRows.getJSONObject(i)
                require(mappingIds.add(row.getString("source_epoch")+":"+row.getString("source_entity_id")))
                mappings+=StrictJson.canonical(row)
            }
            if(index==pages.lastIndex) {
                require(value.isNull("page_token") && !value.isNull("checkpoint"))
                finalCheckpoint=value.getString("checkpoint")
            }else {
                require(!value.isNull("page_token") && value.isNull("checkpoint"))
                expected=snapshots.incrementalQuery(epoch,checkpoint,limit,value.getString("page_token"))
            }
        }
        require(entities.size.toLong()+versions.size<=100_000)
        ServerDiaryValues.validateSnapshot(entities.values.toList(),checkNotNull(timeline))
        for(version in versions.values)version.supersedes?.let {id->require(versions[id]?.let {it.revision<version.revision}==true)}
        ServerDiarySnapshot(epoch,checkNotNull(finalCheckpoint),checkNotNull(lastTime),checkNotNull(firstTime),
            checkNotNull(timeline),entities.values.toList(),mappings,energyVersions=versions.values.toList(),protocolScope=SyncProtocolScope.ENERGY_V1)
    }catch(_:Exception){throw SyncWireException()}
}
