package pl.roseru.kalorie.data

import androidx.room.withTransaction
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.energy.EnergyProtocol
import pl.roseru.kalorie.energy.EnergySchema
import java.time.Instant
import java.util.Collections

/** Entity-only view of a real current proof; it makes no claim about recovery receipts/mappings. */
internal class ServerDiaryEntitiesProof(val gate:MealPushGate,entities:List<ServerDiaryEntity>) {
    val entities:List<ServerDiaryEntity> = Collections.unmodifiableList(entities.toList())
    val timelineRevision:Int = Math.toIntExact(checkNotNull(gate.run.timelineRevision))
    override fun toString()="ServerDiaryEntitiesProof(redacted)"
}

/** Read only. A committed incremental result is not its historical base.
 * Its canonical rows have already been validated and committed atomically by ServerDiaryStore.
 * Recheck that exact application's witnesses and frozen current archive, without re-applying it
 * or inventing full pages. Older raw bases may have been compacted; their real metadata and
 * applications remain the provenance witnesses, including the actual starting checkpoint.
 */
internal class ServerDiaryProof(private val db:CalorieDatabase,private val schema:SyncWireSchema,
    private val energySchema:EnergySchema?) {
    suspend fun active(lease:OwnerLease):ServerDiaryEntitiesProof=db.withTransaction {
        val gate=MealPushStore(db,schema).gate(lease)
        check(!gate.binding.requiresRecovery)
        val run=gate.run
        val scope=SyncProtocolScope.parse(run.protocolScope)
        val pages=db.snapshotDao().pages(run.id)
        require(run.pageCount in 1..2000 && pages.size==run.pageCount &&
            pages.map {it.pageIndex}==pages.indices.toList())
        require(run.byteCount in 0..64L*1_048_576 && run.itemCount in 0..100_000)
        require(pages.sumOf {it.responseJson.toByteArray(Charsets.UTF_8).size.toLong()}==run.byteCount)
        require(run.nextPage==null && run.checkpoint!=null && run.serverTime!=null && run.timelineRevision!=null)
        val first=StrictJson.read(pages.first().queryJson.toByteArray())
        schema.validate(pages.first().queryJson.toByteArray(),"PullRequest")
        require(first.getInt("limit")==run.limit)
        if(scope==SyncProtocolScope.ENERGY_V1)checkNotNull(energySchema)
        val context=CanonicalMealRows.context(gate.binding)
        val witnesses=mutableMapOf<String,ServerSnapshotRun>()
        suspend fun witness(id:String):ServerSnapshotRun {
            witnesses[id]?.let {return it}
            val source=checkNotNull(db.snapshotDao().run(id))
            val application=checkNotNull(db.serverDiaryDao().application(id))
            check(source.state=="complete" && source.ownerScope==lease.storageScope &&
                source.accountId==gate.binding.accountId && source.accountGeneration==gate.binding.accountGeneration &&
                source.syncEpoch==gate.binding.syncEpoch && source.contextRevision==gate.binding.contextRevision &&
                source.protocolScope==run.protocolScope && source.checkpoint!=null &&
                application.ownerScope==lease.storageScope && application.wireContext==context &&
                application.serverTime==source.serverTime && application.timelineRevision.toLong()==source.timelineRevision &&
                application.timelineRevision.toLong()<=checkNotNull(run.timelineRevision) &&
                Instant.parse(application.serverTime)<=Instant.parse(run.serverTime))
            witnesses[id]=source
            return source
        }
        if(scope==SyncProtocolScope.ENERGY_V1) {
            check(db.serverDiaryDao().latest(lease.storageScope)?.runId==run.id)
            witness(run.id)
        }
        if(run.readMode=="snapshot") {
            check(run.baseRunId==null && run.startingCheckpoint==null)
            val copy=ServerDiaryProtocol(schema,energySchema).read(gate.binding.syncEpoch,
                pages.map {ArchivedDiaryPage(it.queryJson,it.responseJson)},scope)
            require(copy.checkpoint==run.checkpoint && copy.serverTime==run.serverTime &&
                copy.timelineRevision.toLong()==run.timelineRevision)
            val count=pages.sumOf {page->val value=StrictJson.read(page.responseJson.toByteArray())
                SnapshotProtocol.IDENTITIES.keys.sumOf {value.getJSONArray(it).length()}}
            require(count==run.itemCount)
            return@withTransaction ServerDiaryEntitiesProof(gate,copy.entities)
        }
        check(run.readMode=="incremental" && scope==SyncProtocolScope.ENERGY_V1 && run.snapshotToken==null)
        // The application already validated the historical base. Check this actual immediate
        // base/checkpoint witness, not an unbounded replay/walk of years of compacted history.
        val base=witness(checkNotNull(run.baseRunId))
        check(base.id!=run.id && base.checkpoint==run.startingCheckpoint &&
            checkNotNull(base.timelineRevision)<=checkNotNull(run.timelineRevision) &&
            Instant.parse(base.serverTime)<=Instant.parse(run.serverTime))
        val rows=db.serverDiaryDao().records(lease.storageScope)
        check(rows.all {it.wireContext==context && it.knownRevision>0 && it.runId==run.id})
        val entities=rows.map {row->
            ServerDiaryEntity(row.entityId,row.entityType,row.knownRevision,row.deleted||row.absent,row.payload)}
        check(entities.size<=100_000 && entities.map {it.id}.toSet().size==entities.size)
        ServerDiaryValues.validateSnapshot(entities,Math.toIntExact(checkNotNull(run.timelineRevision)))
        val shadow=rows.associateBy {it.entityId}
        val energy=EnergyProtocol(checkNotNull(energySchema))
        val versions=db.canonicalEnergyDao().all(lease.storageScope,context).map {row->
            witness(row.sourceRunId)
            energy.version(StrictJson.read(row.wire.toByteArray())).also {
                check(it.id==row.entityId && it.revision==row.revision)
            }
        }
        check(entities.size.toLong()+versions.size<=100_000 &&
            versions.map {it.id}.toSet().size==versions.size &&
            versions.map {it.revision}.toSet().size==versions.size)
        val byEnergy=versions.associateBy {it.id}
        for(version in versions)version.supersedes?.let {id->check(byEnergy[id]?.let {it.revision<version.revision}==true)}
        val protocol=SnapshotProtocol(schema,energySchema)
        val limit=first.getInt("limit")
        var expected=protocol.incrementalQuery(run.syncEpoch,checkNotNull(run.startingCheckpoint),limit)
        val queries=mutableSetOf<String>();val mappings=mutableSetOf<String>()
        data class Change(val type:String,val revision:Long,val deleted:Boolean,val payloadHash:String?)
        val changes=mutableMapOf<String,Change>()
        var itemCount=0;var time=checkNotNull(base.serverTime)
        for((index,page) in pages.withIndex()) {
            require(StrictJson.canonical(StrictJson.read(page.queryJson.toByteArray()))==expected.canonical &&
                queries.add(expected.canonical))
            val value=protocol.response(expected,page.responseJson.toByteArray()).json()
            require(value.getLong("goal_timeline_revision")==run.timelineRevision &&
                value.getLong("goal_timeline_revision")>=checkNotNull(base.timelineRevision))
            val nextTime=value.getString("server_time");require(Instant.parse(nextTime)>=Instant.parse(time));time=nextTime
            itemCount=Math.addExact(itemCount,SnapshotProtocol.IDENTITIES.keys.sumOf {value.getJSONArray(it).length()})
            require(itemCount<=100_000)
            val changed=value.getJSONArray("entities")
            for(i in 0 until changed.length()) {
                val row=changed.getJSONObject(i);val id=row.getString("entity_id");val type=row.getString("entity_type")
                if(type=="energy_estimate") {
                    require(byEnergy[id]?.wire==energy.version(row).wire)
                }else {
                    val payload=if(row.getBoolean("deleted"))null else StrictJson.canonical(row.getJSONObject("payload"))
                    if(payload!=null)when(type) {
                        "meal"->MealWire.read(payload,schema)
                        "weight"->WeightWire.read(payload,schema)
                        "profile","goal","diary_day","product_draft"->ServerDiaryValues.validate(type,payload)
                        else->error("Unsupported incremental entity")
                    }
                    val change=Change(type,row.getLong("revision"),row.getBoolean("deleted"),payload?.let {LegacyImportStore.digest(it)})
                    changes[id]?.let {old->require(old.type==type && old.revision<=change.revision &&
                        (!old.deleted || change.deleted) && (old.revision!=change.revision || old==change))}
                    val current=checkNotNull(shadow[id])
                    require(current.entityType==type && current.knownRevision>=change.revision)
                    if(current.knownRevision.toLong()==change.revision)require(!current.absent &&
                        current.deleted==change.deleted && current.payload==payload)
                    changes[id]=change
                }
            }
            val mapRows=value.getJSONArray("recovery_mappings")
            for(i in 0 until mapRows.length()) {val row=mapRows.getJSONObject(i)
                require(mappings.add(row.getString("source_epoch")+":"+row.getString("source_entity_id")))}
            if(index==pages.lastIndex)require(value.isNull("page_token") && value.getString("checkpoint")==run.checkpoint)
            else {
                require(!value.isNull("page_token") && value.isNull("checkpoint"))
                expected=protocol.incrementalQuery(run.syncEpoch,checkNotNull(run.startingCheckpoint),limit,value.getString("page_token"))
            }
        }
        require(itemCount==run.itemCount && time==run.serverTime)
        for((id,change) in changes)require(shadow.getValue(id).knownRevision.toLong()==change.revision)
        ServerDiaryEntitiesProof(gate,entities)
    }
}
