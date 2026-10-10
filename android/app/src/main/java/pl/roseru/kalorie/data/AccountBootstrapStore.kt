package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.withTransaction
import pl.roseru.kalorie.core.BootstrapResponse
import java.util.UUID

@Entity(tableName = "account_bindings", foreignKeys = [ForeignKey(entity = LocalOwnerEntity::class,
    parentColumns = ["storageScope"], childColumns = ["ownerScope"], onDelete = ForeignKey.RESTRICT)],
    indices = [Index(value = ["accountId"], unique = true)])
data class AccountBindingEntity(@PrimaryKey val ownerScope: String, val accountId: String,
    val accountGeneration: Int, val syncEpoch: String, val serverTime: String,
    val contextRevision: Long, val requiresRecovery: Boolean)

@Entity(tableName = "bootstrap_attempts", foreignKeys = [ForeignKey(entity = LocalOwnerEntity::class,
    parentColumns = ["storageScope"], childColumns = ["ownerScope"], onDelete = ForeignKey.RESTRICT)],
    indices = [Index(value = ["operationId"], unique = true)])
data class BootstrapAttemptEntity(@PrimaryKey val ownerScope: String, val operationId: String,
    val leaseGeneration: Long, val responseJson: String?)

@Dao interface AccountBootstrapDao {
    @Query("SELECT * FROM account_bindings WHERE ownerScope = :owner") suspend fun binding(owner: String): AccountBindingEntity?
    @Query("SELECT * FROM bootstrap_attempts WHERE ownerScope = :owner") suspend fun attempt(owner: String): BootstrapAttemptEntity?
    @Insert suspend fun insert(binding: AccountBindingEntity)
    @Update suspend fun update(binding: AccountBindingEntity)
    @Insert suspend fun insert(attempt: BootstrapAttemptEntity)
    @Update suspend fun update(attempt: BootstrapAttemptEntity)
}

@ConsistentCopyVisibility
data class BootstrapRequest internal constructor(val lease: OwnerLease, val operationId: String)
class BootstrapConflictException : IllegalStateException("Odpowiedź bootstrap jest niezgodna z zapisanym kontem lub żądaniem")
class BootstrapRecoveryRequiredException : IllegalStateException("Zmiana kontekstu serwera wymaga uzgodnienia synchronizacji")

/** Durable protocol state only. Caller must supply a confirmed OIDC session; this store does not authenticate. */
class AccountBootstrapStore(private val db: CalorieDatabase) {
    private val owners = LocalOwnerStore(db)
    private val dao = db.bootstrapDao()
    suspend fun begin(lease: OwnerLease): BootstrapRequest = db.withTransaction {
        owners.requireCurrent(lease)
        require(db.ownerDao().byScope(lease.storageScope)?.kind == "account")
        val pending = dao.attempt(lease.storageScope)
        val attempt = if (pending?.leaseGeneration == lease.generation && pending.responseJson == null) pending
        else BootstrapAttemptEntity(lease.storageScope, UUID.randomUUID().toString(), lease.generation, null).also {
            if (pending == null) dao.insert(it) else dao.update(it)
        }
        BootstrapRequest(lease, attempt.operationId)
    }
    /** E3's epoch/generation conflict requires a new key; keep the previous binding and private data. */
    suspend fun renew(request: BootstrapRequest): BootstrapRequest = db.withTransaction {
        owners.requireCurrent(request.lease)
        val old = dao.attempt(request.lease.storageScope)
        if (old?.operationId != request.operationId || old.leaseGeneration != request.lease.generation || old.responseJson != null)
            throw BootstrapConflictException()
        val next = old.copy(operationId = UUID.randomUUID().toString())
        dao.update(next)
        BootstrapRequest(request.lease, next.operationId)
    }
    suspend fun apply(request: BootstrapRequest, response: BootstrapResponse): AccountBindingEntity = db.withTransaction {
        owners.requireCurrent(request.lease)
        val owner = request.lease.storageScope
        val attempt = dao.attempt(owner)
        if (attempt?.operationId != request.operationId || attempt.leaseGeneration != request.lease.generation) throw BootstrapConflictException()
        val canonical = response.canonical()
        val old = dao.binding(owner)
        if (attempt.responseJson != null) {
            if (attempt.responseJson != canonical) throw BootstrapConflictException()
            return@withTransaction checkNotNull(old)
        }
        if (old != null && (old.accountId != response.accountId ||
            (old.syncEpoch == response.syncEpoch && old.accountGeneration > response.accountGeneration))) throw BootstrapConflictException()
        val changed = old != null && (old.syncEpoch != response.syncEpoch || old.accountGeneration != response.accountGeneration)
        val binding = AccountBindingEntity(owner, response.accountId, response.accountGeneration, response.syncEpoch, response.serverTime,
            if (changed) Math.addExact(old!!.contextRevision, 1) else old?.contextRevision ?: 1,
            old?.requiresRecovery == true || changed)
        // A conflict on accountId must abort instead of being mistaken for a primary-key upsert.
        if (old == null) dao.insert(binding) else dao.update(binding)
        dao.update(attempt.copy(responseJson = canonical))
        binding
    }
    /** A future worker must check this inside its write transaction and again before sending. */
    suspend fun requireReady(lease: OwnerLease, contextRevision: Long): AccountBindingEntity = db.withTransaction {
        owners.requireCurrent(lease)
        val binding = checkNotNull(dao.binding(lease.storageScope))
        if (binding.contextRevision != contextRevision || binding.requiresRecovery) throw BootstrapRecoveryRequiredException()
        binding
    }
}
