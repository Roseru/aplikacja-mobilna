package pl.roseru.kalorie.data

import androidx.room.withTransaction
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import pl.roseru.kalorie.core.DietAim
import pl.roseru.kalorie.core.normalizeSearch
import pl.roseru.kalorie.core.sync.*
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

class DiaryProjectionChangedException : IllegalStateException("Kopia wymaga ponownego pobrania; dziennik zachowany")

/** Applies a completed full copy atomically. No pending operation is acknowledged or rewritten. */
class ServerDiaryStore(private val db: CalorieDatabase, private val schema: SyncWireSchema) {
    private val push = MealPushStore(db, schema)
    private val protocol = ServerDiaryProtocol(schema)
    private val records = db.serverDiaryDao()
    private val dao = db.dao()

    suspend fun latest(lease: OwnerLease): ServerDiaryApplication? = db.withTransaction {
        LocalOwnerStore(db).requireCurrent(lease)
        val binding = db.bootstrapDao().binding(lease.storageScope) ?: return@withTransaction null
        records.latest(lease.storageScope)?.takeIf { it.wireContext == CanonicalMealRows.context(binding) }
    }

    suspend fun apply(lease: OwnerLease, expectedRun: String? = null): ServerDiaryApplication = withContext(Dispatchers.IO) {
        val source = db.withTransaction {
            val gate = push.gate(lease)
            if (expectedRun != null && gate.run.id != expectedRun) throw DiaryProjectionChangedException()
            gate to db.snapshotDao().pages(gate.run.id)
        }
        val (gate, pages) = source
        require(pages.map { it.pageIndex } == pages.indices.toList() && pages.size == gate.run.pageCount)
        val copy = protocol.read(gate.binding.syncEpoch, pages.map { ArchivedDiaryPage(it.queryJson, it.responseJson) })
        require(copy.checkpoint == gate.run.checkpoint && copy.serverTime == gate.run.serverTime &&
            copy.timelineRevision.toLong() == gate.run.timelineRevision)
        db.withTransaction {
            if (push.gate(lease) != gate || db.snapshotDao().pages(gate.run.id) != pages) throw DiaryProjectionChangedException()
            val context = CanonicalMealRows.context(gate.binding)
            records.application(gate.run.id)?.let { saved ->
                check(saved.ownerScope == lease.storageScope && saved.wireContext == context)
                return@withTransaction saved // A replay cannot undo an edit made after the first application.
            }
            val previous = records.records(lease.storageScope)
            check(previous.all { it.wireContext == context }) // Epoch recovery is a separate, explicit operation.
            records.latest(lease.storageScope)?.let { old ->
                if (old.wireContext != context || Instant.parse(copy.firstServerTime) < Instant.parse(old.serverTime) ||
                    copy.timelineRevision < old.timelineRevision) throw DiaryProjectionChangedException()
            }
            val known = previous.associateBy { it.entityType to it.entityId }
            val queue = records.unsettled(lease.storageScope)
            val queuedIds = queue.map { it.entityType to it.entityId }.toSet()
            val pendingProfile = queue.any { it.entityType == "profile" }
            val pendingDays = queue.filter { it.entityType == "diary_day" }.map { it.entityId }.toSet()
            val mappedGoals = previous.filter { it.entityType == "goal" }.mapNotNull { it.localId }.toSet()
            val localGoals = records.allGoals(lease.storageScope)
            // Goal versions are immutable. Preserve an entire pending timeline until it is reconciled.
            val holdGoals = queue.any { it.entityType == "goal" } || localGoals.any {
                it.id !in mappedGoals && db.domainSyncDao().local(lease.storageScope, "goal", it.id)?.serverRevision?.let { revision -> revision > 0 } != true
            }
            val incoming = copy.entities.associateBy { it.type to it.id }
            val observations = copy.entities.map { entity ->
                val old = known[entity.type to entity.id]
                if (old != null) {
                    if (entity.revision < old.knownRevision ||
                        ((old.deleted || old.absent) && !entity.deleted) ||
                        (entity.revision == old.knownRevision && !old.absent &&
                            (entity.payload != old.payload || entity.deleted != old.deleted))) throw DiaryProjectionChangedException()
                }
                ServerDiaryRecord(lease.storageScope, entity.type, entity.id, old?.localId, context,
                    entity.revision, entity.deleted, false, entity.payload, gate.run.id, "pending_local")
            } + previous.filter { (it.entityType to it.entityId) !in incoming }.map {
                // Absence in a new full copy means deletion in this epoch, with unknown deletion revision.
                it.copy(deleted = true, absent = true, payload = null, runId = gate.run.id, disposition = "pending_local")
            }
            val order = mapOf("goal" to 0, "profile" to 1, "product_draft" to 2, "meal" to 3, "weight" to 4, "diary_day" to 5)
            val goalOrder = observations.filter { it.entityType == "goal" && !it.deleted }.associate {
                it.entityId to ServerDiaryValues.json(entity(it)).getInt("timeline_base_revision")
            }
            var included = 0; var held = 0
            for (row in observations.sortedWith(compareBy<ServerDiaryRecord> { order.getValue(it.entityType) }
                // Release the retired unique profile before importing its replacement, regardless of UUID order.
                .thenBy { if (it.entityType == "profile" && it.deleted) 0 else 1 }
                .thenBy { if (it.entityType == "goal") goalOrder[it.entityId] ?: -1 else -1 }
                .thenBy { it.entityId })) {
                val old = known[row.entityType to row.entityId]
                val pending = (row.entityType to row.entityId) in queuedIds ||
                    row.localId?.let { (row.entityType to it) in queuedIds } == true ||
                    (row.entityType == "profile" && pendingProfile)
                val localId = if (pending || (row.entityType == "goal" && holdGoals)) null else when (row.entityType) {
                    "meal" -> meal(row, old)
                    "weight" -> weight(row, old)
                    "goal" -> goal(row, old)
                    "profile" -> profile(row, old, copy)
                    "diary_day" -> day(row, old, pendingDays)
                    "product_draft" -> product(row, old)
                    else -> error("Unsupported diary entity")
                }
                // A deleted, never materialized row has no local ID and still counts as included.
                val applied = localId != null || (!pending && row.deleted && old?.localId == null &&
                    !(row.entityType == "goal" && holdGoals) && !existsLocally(row))
                if (applied && row.entityType in PrivateDomainsWire.types && localId != null) {
                    val state = db.domainSyncDao().state(row.ownerScope, row.entityType, row.entityId)
                    if (state != null && (state.wireContext != context || (!row.absent && state.serverRevision > row.knownRevision)))
                        throw DiaryProjectionChangedException()
                    db.domainSyncDao().save(CanonicalDomainState(row.ownerScope, row.entityType, row.entityId, localId,
                        row.payload ?: state?.wirePayload, context, if (row.absent) state?.serverRevision ?: row.knownRevision else row.knownRevision, row.deleted))
                }
                records.save(row.copy(localId = localId ?: old?.localId,
                    disposition = if (applied) "applied" else "pending_local"))
                if (applied) included++ else held++
            }
            val timeline = db.domainSyncDao().timeline(lease.storageScope)
            if (timeline != null && (timeline.wireContext != context || timeline.revision > copy.timelineRevision))
                throw DiaryProjectionChangedException()
            db.domainSyncDao().save(CanonicalGoalTimeline(lease.storageScope, context, copy.timelineRevision))
            val saved = ServerDiaryApplication(gate.run.id, lease.storageScope, context, copy.serverTime,
                copy.timelineRevision, included, held, Instant.now().toString())
            records.insert(saved)
            saved
        }
    }

    private fun entity(row: ServerDiaryRecord) = ServerDiaryEntity(row.entityId, row.entityType,
        row.knownRevision, row.deleted, row.payload)

    private suspend fun existsLocally(row: ServerDiaryRecord): Boolean = when (row.entityType) {
        "meal" -> records.mealOwner(row.entityId) != null
        "weight" -> dao.weightOwner(row.entityId) != null
        "goal" -> records.goal(row.entityId) != null
        "product_draft" -> records.product(row.entityId) != null
        "profile" -> records.profile(row.localId ?: row.entityId) != null
        "diary_day" -> records.day(row.localId ?: row.entityId) != null
        else -> true
    }

    private suspend fun meal(row: ServerDiaryRecord, old: ServerDiaryRecord?): String? {
        val localId=db.localSyncId(row.ownerScope,"meal",row.entityId)
        val owner = records.mealOwner(localId); check(owner == null || owner == row.ownerScope)
        val current = dao.meal(localId, row.ownerScope)
        if (current != null && (current.meal.wirePayload == null || current.meal.wireContext != row.wireContext)) return null
        if (current != null && current.meal.serverRevision > row.knownRevision) throw DiaryProjectionChangedException()
        if (row.deleted) {
            if (current != null) dao.updateMeal(current.meal.copy(deleted = true,
                serverRevision = if (row.absent) current.meal.serverRevision else row.knownRevision))
            return current?.meal?.id ?: old?.localId
        }
        val wire = MealWire.read(checkNotNull(row.payload), schema)
        val fresh = CanonicalMealRows.meal(localId, row.ownerScope, wire, row.wireContext,
            row.knownRevision, current?.meal?.localRevision ?: 1)
        if (current != null && current.meal.serverRevision == row.knownRevision &&
            (current.meal.wirePayload != wire.canonical || current.meal.deleted)) throw DiaryProjectionChangedException()
        val items = db.localMealItems(row.ownerScope,localId,wire)
        items.forEach { item -> check(dao.itemById(item.id)?.mealId.let { it == null || it == localId }) }
        if (current == null) dao.insertMeal(fresh) else dao.updateMeal(fresh)
        val ids = items.map { it.id }.toSet()
        current?.items?.filter { it.id !in ids }?.forEach { dao.removeItem(it) }
        items.forEach { item ->
            val prior = current?.items?.find { it.id == item.id }
            if (prior == null) dao.insertItem(item) else dao.updateItem(
                if (prior.wirePayload == item.wirePayload) item.copy(productId = prior.productId,
                    rationComponentId = prior.rationComponentId, snapshotJson = prior.snapshotJson) else item)
        }
        return localId
    }

    private suspend fun weight(row: ServerDiaryRecord, old: ServerDiaryRecord?): String? {
        val localId=db.localSyncId(row.ownerScope,"weight",row.entityId)
        val owner = dao.weightOwner(localId); check(owner == null || owner == row.ownerScope)
        val current = dao.weight(localId, row.ownerScope)
        val state = db.weightSyncDao().state(row.ownerScope, localId)
        if (current != null && (state == null || state.wireContext != row.wireContext)) return null
        if (state != null && state.serverRevision > row.knownRevision) throw DiaryProjectionChangedException()
        if (row.deleted) {
            if (current != null) {
                dao.saveWeight(current.copy(deleted = true))
                if (!row.absent) db.weightSyncDao().update(checkNotNull(state).copy(serverRevision = row.knownRevision))
            }
            return current?.id ?: old?.localId
        }
        val wire = WeightWire.read(checkNotNull(row.payload), schema); val value = wire.json()
        if (state != null && state.serverRevision == row.knownRevision &&
            (state.wirePayload != wire.canonical || current?.deleted == true)) throw DiaryProjectionChangedException()
        dao.saveWeight(WeightEntity(localId, row.ownerScope, value.getString("local_date"),
            value.getString("occurred_at"), value.getString("time_zone"), value.getString("weight_kg").toDouble(),
            localRevision = current?.localRevision ?: 1))
        val fresh = CanonicalWeightState(localId, row.ownerScope, wire.canonical, row.wireContext, row.knownRevision)
        if (state == null) db.weightSyncDao().insert(fresh) else db.weightSyncDao().update(fresh)
        return localId
    }

    private suspend fun goal(row: ServerDiaryRecord, old: ServerDiaryRecord?): String? {
        val localId=db.localSyncId(row.ownerScope,"goal",row.entityId)
        val current = records.goal(localId); check(current == null || current.ownerScope == row.ownerScope)
        if (row.deleted) return current?.id ?: old?.localId // Filter via sidecar; never mutate an immutable goal.
        val value = ServerDiaryValues.json(entity(row))
        val fresh = GoalEntity(localId, row.ownerScope, value.getString("effective_from"),
            checkNotNull(ServerDiaryValues.decimal(value, "energy_kcal")), ServerDiaryValues.decimal(value, "protein_g"),
            ServerDiaryValues.decimal(value, "fat_g"), ServerDiaryValues.decimal(value, "carbs_g"),
            Math.addExact(value.getInt("timeline_base_revision"), 1), value.getString("decided_at"),
            value.getString("time_zone"), value.getString("reason"),
            if (value.isNull("correction_of")) null else db.localSyncId(row.ownerScope,"goal",value.getString("correction_of")))
        if (current == null) dao.saveGoal(fresh) else if (current != fresh) {
            val state = db.domainSyncDao().state(row.ownerScope, "goal", row.entityId)
            // localSequence is local ordering; the exact canonical payload owns the server axis base.
            if (state?.wireContext != row.wireContext || state.wirePayload != row.payload ||
                (current != fresh.copy(localSequence = current.localSequence) && db.importDao().local(row.ownerScope,"goal",localId)==null)) throw DiaryProjectionChangedException()
        }
        return localId
    }

    private suspend fun profile(row: ServerDiaryRecord, old: ServerDiaryRecord?, copy: ServerDiarySnapshot): String? {
        if (row.deleted) {
            // An old tombstone does not address the owner's different, live profile.
            val canonical = db.domainSyncDao().state(row.ownerScope, "profile", row.entityId)
            check(canonical == null || canonical.wireContext == row.wireContext)
            val target = records.profile(old?.localId ?: canonical?.localId ?: row.entityId)
            check(target == null || target.ownerScope == row.ownerScope)
            if (target != null && old?.localId != target.id && canonical?.localId != target.id) return null
            target?.let { records.delete(it) }
            return target?.id ?: old?.localId
        }
        val current = dao.currentProfile(row.ownerScope)
        if (current != null && old?.localId != current.id &&
            db.domainSyncDao().state(row.ownerScope, "profile", row.entityId)?.localId != current.id) return null
        val collision = records.profile(db.localSyncId(row.ownerScope,"profile",row.entityId)); check(collision == null || collision.ownerScope == row.ownerScope)
        val value = ServerDiaryValues.json(entity(row)); val zone = value.getString("time_zone")
        val today = LocalDate.now(ZoneId.of(zone)).toString()
        val goal = copy.entities.filter { it.type == "goal" && !it.deleted }
            .map { ServerDiaryValues.json(it) }.filter { it.getString("effective_from") <= today }
            .maxWithOrNull(compareBy({ it.getString("effective_from") }, { it.getInt("timeline_base_revision") }))
        val aim = goal?.let(ServerDiaryValues::aim)?.name ?: current?.dietAim ?: DietAim.MAINTAIN.name
        val localId = current?.id ?: db.localSyncId(row.ownerScope,"profile",row.entityId)
        dao.saveProfile(ProfileEntity(localId, row.ownerScope, value.getString("pseudonym"),
            ServerDiaryValues.decimal(value, "height_cm"), ServerDiaryValues.activity(value).name, aim,
            zone, current?.localRevision ?: 1))
        return localId
    }

    private suspend fun day(row: ServerDiaryRecord, old: ServerDiaryRecord?, pendingDays: Set<String>): String? {
        if (row.deleted) {
            val canonical = db.domainSyncDao().state(row.ownerScope, "diary_day", row.entityId)
            check(canonical == null || canonical.wireContext == row.wireContext)
            val current = records.day(old?.localId ?: canonical?.localId ?: row.entityId)
            check(current == null || current.ownerScope == row.ownerScope)
            if (current != null && old?.localId != current.id && canonical?.localId != current.id) return null
            current?.let { dao.saveDiaryDay(it.copy(declaredComplete = false)) }
            return current?.id ?: old?.localId
        }
        val value = ServerDiaryValues.json(entity(row)); val date = value.getString("local_date")
        val current = dao.currentDiaryDay(row.ownerScope, date)
        if (current != null && ((old?.localId != current.id &&
                db.domainSyncDao().state(row.ownerScope, "diary_day", row.entityId)?.localId != current.id) || current.id in pendingDays)) return null
        val collision = records.day(db.localSyncId(row.ownerScope,"diary_day",row.entityId)); check(collision == null || collision.ownerScope == row.ownerScope)
        val id = current?.id ?: db.localSyncId(row.ownerScope,"diary_day",row.entityId)
        dao.saveDiaryDay(DiaryDayEntity(id, row.ownerScope, date, value.getBoolean("declared_complete"), current?.localRevision ?: 1))
        return id
    }

    private suspend fun product(row: ServerDiaryRecord, old: ServerDiaryRecord?): String? {
        val localId=db.localSyncId(row.ownerScope,"product_draft",row.entityId)
        val current = records.product(localId)
        check(current == null || (current.ownerScope == row.ownerScope && current.catalogJson == null))
        if (current != null && old?.localId != current.id &&
            db.domainSyncDao().state(row.ownerScope, "product_draft", row.entityId)?.localId != current.id) return null
        if (row.deleted) { current?.let { records.delete(it) }; return current?.id ?: old?.localId }
        val value = ServerDiaryValues.json(entity(row)); val nutrition = value.getJSONObject("nutrition_per_100")
        val name = value.getString("name")
        val pack = value.optJSONObject("package_quantity")
        val defaultAmount = if (pack?.getString("unit") == value.getString("basis_unit")) pack.getString("amount").toDouble() else 100.0
        // REAL is a search projection only; exact wirePayload owns all nutrition, including null energy.
        val fresh = ProductEntity(localId, name, normalizeSearch(name), ServerDiaryValues.decimal(nutrition, "energy_kcal") ?: 0.0,
            ServerDiaryValues.decimal(nutrition, "protein_g"), ServerDiaryValues.decimal(nutrition, "fat_g"),
            ServerDiaryValues.decimal(nutrition, "carbs_g"), defaultAmount, "Twoje produkty", value.getString("source_description"),
            0, row.ownerScope, wirePayload = row.payload)
        if (current == null) dao.insertProduct(fresh) else records.update(fresh)
        return localId
    }
}
