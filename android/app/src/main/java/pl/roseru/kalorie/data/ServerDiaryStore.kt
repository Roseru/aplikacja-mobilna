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
            val localGoals = records.allGoals(lease.storageScope)
            // Goal versions are immutable. Preserve an entire pending timeline until it is reconciled.
            val holdGoals = queue.any { it.entityType == "goal" } || localGoals.any { goal ->
                previous.none { it.entityType == "goal" && it.localId == goal.id }
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
            var included = 0; var held = 0
            for (row in observations.sortedWith(compareBy<ServerDiaryRecord> { order.getValue(it.entityType) }
                .thenBy { if (it.entityType == "goal" && !it.deleted) ServerDiaryValues.json(entity(it)).getInt("timeline_base_revision") else -1 }
                .thenBy { it.entityId })) {
                val old = known[row.entityType to row.entityId]
                val pending = queue.any { it.entityType == row.entityType &&
                    (it.entityId == row.entityId || it.entityId == row.localId || row.entityType == "profile") }
                val localId = if (pending || (row.entityType == "goal" && holdGoals)) null else when (row.entityType) {
                    "meal" -> meal(row, old)
                    "weight" -> weight(row, old)
                    "goal" -> goal(row, old)
                    "profile" -> profile(row, old, copy)
                    "diary_day" -> day(row, old, queue)
                    "product_draft" -> product(row, old)
                    else -> error("Unsupported diary entity")
                }
                // A deleted, never materialized row has no local ID and still counts as included.
                val applied = localId != null || (!pending && row.deleted && old?.localId == null &&
                    !(row.entityType == "goal" && holdGoals) && !existsLocally(row))
                records.save(row.copy(localId = localId ?: old?.localId,
                    disposition = if (applied) "applied" else "pending_local"))
                if (applied) included++ else held++
            }
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
        "profile" -> dao.currentProfile(row.ownerScope) != null
        "diary_day" -> records.day(row.localId ?: row.entityId) != null
        else -> true
    }

    private suspend fun meal(row: ServerDiaryRecord, old: ServerDiaryRecord?): String? {
        val owner = records.mealOwner(row.entityId); check(owner == null || owner == row.ownerScope)
        val current = dao.meal(row.entityId, row.ownerScope)
        if (current != null && (current.meal.wirePayload == null || current.meal.wireContext != row.wireContext)) return null
        if (current != null && current.meal.serverRevision > row.knownRevision) throw DiaryProjectionChangedException()
        if (row.deleted) {
            if (current != null) dao.updateMeal(current.meal.copy(deleted = true,
                serverRevision = if (row.absent) current.meal.serverRevision else row.knownRevision))
            return current?.meal?.id ?: old?.localId
        }
        val wire = MealWire.read(checkNotNull(row.payload), schema)
        val fresh = CanonicalMealRows.meal(row.entityId, row.ownerScope, wire, row.wireContext,
            row.knownRevision, current?.meal?.localRevision ?: 1)
        if (current != null && current.meal.serverRevision == row.knownRevision &&
            (current.meal.wirePayload != wire.canonical || current.meal.deleted)) throw DiaryProjectionChangedException()
        val items = CanonicalMealRows.items(row.entityId, wire)
        items.forEach { item -> check(dao.itemById(item.id)?.mealId.let { it == null || it == row.entityId }) }
        if (current == null) dao.insertMeal(fresh) else dao.updateMeal(fresh)
        val ids = items.map { it.id }.toSet()
        current?.items?.filter { it.id !in ids }?.forEach { dao.removeItem(it) }
        items.forEach { item ->
            val prior = current?.items?.find { it.id == item.id }
            if (prior == null) dao.insertItem(item) else dao.updateItem(
                if (prior.wirePayload == item.wirePayload) item.copy(productId = prior.productId,
                    rationComponentId = prior.rationComponentId, snapshotJson = prior.snapshotJson) else item)
        }
        return row.entityId
    }

    private suspend fun weight(row: ServerDiaryRecord, old: ServerDiaryRecord?): String? {
        val owner = dao.weightOwner(row.entityId); check(owner == null || owner == row.ownerScope)
        val current = dao.weight(row.entityId, row.ownerScope)
        val state = db.weightSyncDao().state(row.ownerScope, row.entityId)
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
        dao.saveWeight(WeightEntity(row.entityId, row.ownerScope, value.getString("local_date"),
            value.getString("occurred_at"), value.getString("time_zone"), value.getString("weight_kg").toDouble(),
            localRevision = current?.localRevision ?: 1))
        val fresh = CanonicalWeightState(row.entityId, row.ownerScope, wire.canonical, row.wireContext, row.knownRevision)
        if (state == null) db.weightSyncDao().insert(fresh) else db.weightSyncDao().update(fresh)
        return row.entityId
    }

    private suspend fun goal(row: ServerDiaryRecord, old: ServerDiaryRecord?): String? {
        val current = records.goal(row.entityId); check(current == null || current.ownerScope == row.ownerScope)
        if (row.deleted) return current?.id ?: old?.localId // Filter via sidecar; never mutate an immutable goal.
        val value = ServerDiaryValues.json(entity(row))
        val fresh = GoalEntity(row.entityId, row.ownerScope, value.getString("effective_from"),
            checkNotNull(ServerDiaryValues.decimal(value, "energy_kcal")), ServerDiaryValues.decimal(value, "protein_g"),
            ServerDiaryValues.decimal(value, "fat_g"), ServerDiaryValues.decimal(value, "carbs_g"),
            Math.addExact(value.getInt("timeline_base_revision"), 1), value.getString("decided_at"),
            value.getString("time_zone"), value.getString("reason"),
            if (value.isNull("correction_of")) null else value.getString("correction_of"))
        if (current == null) dao.saveGoal(fresh) else if (current != fresh) throw DiaryProjectionChangedException()
        return row.entityId
    }

    private suspend fun profile(row: ServerDiaryRecord, old: ServerDiaryRecord?, copy: ServerDiarySnapshot): String? {
        val current = dao.currentProfile(row.ownerScope)
        if (current != null && old?.localId != current.id) return null
        if (row.deleted) { current?.let { records.delete(it) }; return current?.id ?: old?.localId }
        val collision = records.profile(row.entityId); check(collision == null || collision.ownerScope == row.ownerScope)
        val value = ServerDiaryValues.json(entity(row)); val zone = value.getString("time_zone")
        val today = LocalDate.now(ZoneId.of(zone)).toString()
        val goal = copy.entities.filter { it.type == "goal" && !it.deleted }
            .map { ServerDiaryValues.json(it) }.filter { it.getString("effective_from") <= today }
            .maxWithOrNull(compareBy({ it.getString("effective_from") }, { it.getInt("timeline_base_revision") }))
        val aim = goal?.let(ServerDiaryValues::aim)?.name ?: current?.dietAim ?: DietAim.MAINTAIN.name
        val localId = current?.id ?: row.entityId
        dao.saveProfile(ProfileEntity(localId, row.ownerScope, value.getString("pseudonym"),
            ServerDiaryValues.decimal(value, "height_cm"), ServerDiaryValues.activity(value).name, aim,
            zone, current?.localRevision ?: 1))
        return localId
    }

    private suspend fun day(row: ServerDiaryRecord, old: ServerDiaryRecord?, queue: List<OutboxEntity>): String? {
        if (row.deleted) {
            val current = records.day(old?.localId ?: row.entityId)
            check(current == null || current.ownerScope == row.ownerScope)
            if (current != null && old?.localId != current.id) return null
            current?.let { dao.saveDiaryDay(it.copy(declaredComplete = false)) }
            return current?.id ?: old?.localId
        }
        val value = ServerDiaryValues.json(entity(row)); val date = value.getString("local_date")
        val current = dao.currentDiaryDay(row.ownerScope, date)
        if (current != null && (old?.localId != current.id ||
                queue.any { it.entityType == "diary_day" && it.entityId == current.id })) return null
        val collision = records.day(row.entityId); check(collision == null || collision.ownerScope == row.ownerScope)
        val id = current?.id ?: row.entityId
        dao.saveDiaryDay(DiaryDayEntity(id, row.ownerScope, date, value.getBoolean("declared_complete"), current?.localRevision ?: 1))
        return id
    }

    private suspend fun product(row: ServerDiaryRecord, old: ServerDiaryRecord?): String? {
        val current = records.product(row.entityId)
        check(current == null || (current.ownerScope == row.ownerScope && current.catalogJson == null))
        if (current != null && old?.localId != current.id) return null
        if (row.deleted) { current?.let { records.delete(it) }; return current?.id ?: old?.localId }
        val value = ServerDiaryValues.json(entity(row)); val nutrition = value.getJSONObject("nutrition_per_100")
        val name = value.getString("name")
        val pack = value.optJSONObject("package_quantity")
        val defaultAmount = if (pack?.getString("unit") == value.getString("basis_unit")) pack.getString("amount").toDouble() else 100.0
        // REAL is a search projection only; exact wirePayload owns all nutrition, including null energy.
        val fresh = ProductEntity(row.entityId, name, normalizeSearch(name), ServerDiaryValues.decimal(nutrition, "energy_kcal") ?: 0.0,
            ServerDiaryValues.decimal(nutrition, "protein_g"), ServerDiaryValues.decimal(nutrition, "fat_g"),
            ServerDiaryValues.decimal(nutrition, "carbs_g"), defaultAmount, "Twoje produkty", value.getString("source_description"),
            0, row.ownerScope, wirePayload = row.payload)
        if (current == null) dao.insertProduct(fresh) else records.update(fresh)
        return row.entityId
    }
}
