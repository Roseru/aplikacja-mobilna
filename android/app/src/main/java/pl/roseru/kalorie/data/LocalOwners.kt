package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.room.withTransaction
import java.net.URI
import java.util.UUID

@Entity(tableName = "local_owners", indices = [Index(value = ["storageScope"], unique = true),
    Index(value = ["issuer", "subject"], unique = true)])
data class LocalOwnerEntity(@PrimaryKey val id: String, val storageScope: String, val kind: String,
    val issuer: String?, val subject: String?)

@Entity(tableName = "local_active_owner", foreignKeys = [ForeignKey(entity = LocalOwnerEntity::class,
    parentColumns = ["storageScope"], childColumns = ["storageScope"], onDelete = ForeignKey.RESTRICT)], indices = [Index("storageScope")])
data class LocalActiveOwnerEntity(@PrimaryKey val id: Int = 1, val storageScope: String, val generation: Long)

@Dao interface LocalOwnerDao {
    @Query("SELECT * FROM local_owners WHERE storageScope = :scope") suspend fun byScope(scope: String): LocalOwnerEntity?
    @Query("SELECT * FROM local_owners WHERE id = :id") suspend fun byId(id: String): LocalOwnerEntity?
    @Query("SELECT * FROM local_owners WHERE issuer = :issuer AND subject = :subject") suspend fun byIdentity(issuer: String, subject: String): LocalOwnerEntity?
    @Query("SELECT * FROM local_active_owner WHERE id = 1") suspend fun active(): LocalActiveOwnerEntity?
    @Insert suspend fun insert(owner: LocalOwnerEntity)
    @Upsert suspend fun select(value: LocalActiveOwnerEntity)
}

@ConsistentCopyVisibility
data class OwnerLease internal constructor(val storageScope: String, val generation: Long)
class StaleOwnerException : IllegalStateException("Aktywny właściciel danych uległ zmianie")

/** Local identity metadata only. Registering/selecting a scope does not authenticate an API session. */
class LocalOwnerStore(private val db: CalorieDatabase) {
    private val dao = db.ownerDao()
    suspend fun ensureGuest(): LocalOwnerEntity = db.withTransaction {
        val guest = dao.byScope(DiaryRepository.GUEST) ?: LocalOwnerEntity(UUID.randomUUID().toString(),
            DiaryRepository.GUEST, "guest", null, null).also { dao.insert(it) }
        if (dao.active() == null) dao.select(LocalActiveOwnerEntity(storageScope = guest.storageScope, generation = 1))
        guest
    }
    suspend fun registerIdentity(issuer: String, subject: String): LocalOwnerEntity = db.withTransaction {
        val uri = URI(issuer)
        require(uri.host != null && uri.userInfo == null && uri.rawQuery == null && uri.rawFragment == null)
        require(uri.scheme == "https" || (uri.scheme == "http" && uri.host in listOf("localhost", "127.0.0.1", "[::1]")))
        require(subject.isNotBlank() && subject == subject.trim() && subject.length <= 255 && subject.none { it.isISOControl() })
        ensureGuest()
        dao.byIdentity(issuer, subject) ?: UUID.randomUUID().toString().let { id ->
            LocalOwnerEntity(id, id, "account", issuer, subject).also { dao.insert(it) }
        }
    }
    suspend fun currentLease(): OwnerLease = db.withTransaction {
        ensureGuest()
        val active = checkNotNull(dao.active())
        OwnerLease(active.storageScope, active.generation)
    }
    suspend fun select(ownerId: String): OwnerLease = db.withTransaction {
        ensureGuest()
        val owner = requireNotNull(dao.byId(ownerId))
        val generation = Math.addExact(checkNotNull(dao.active()).generation, 1)
        dao.select(LocalActiveOwnerEntity(storageScope = owner.storageScope, generation = generation))
        OwnerLease(owner.storageScope, generation)
    }
    suspend fun requireCurrent(lease: OwnerLease) {
        val active = dao.active()
        if (active?.storageScope != lease.storageScope || active.generation != lease.generation) throw StaleOwnerException()
    }
}

val MIGRATION_4_5 = object : Migration(4, 5) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS local_owners (id TEXT NOT NULL PRIMARY KEY, storageScope TEXT NOT NULL, kind TEXT NOT NULL, issuer TEXT, subject TEXT)")
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_local_owners_storageScope ON local_owners(storageScope)")
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_local_owners_issuer_subject ON local_owners(issuer, subject)")
        db.execSQL("CREATE TABLE IF NOT EXISTS local_active_owner (id INTEGER NOT NULL PRIMARY KEY, storageScope TEXT NOT NULL, generation INTEGER NOT NULL, FOREIGN KEY(storageScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_local_active_owner_storageScope ON local_active_owner(storageScope)")
        // Keep the legacy alias in all old rows and payloads; only attach a durable guest UUID.
        db.execSQL("INSERT INTO local_owners (id,storageScope,kind,issuer,subject) VALUES (?, 'guest', 'guest', NULL, NULL)", arrayOf(UUID.randomUUID().toString()))
        db.execSQL("INSERT INTO local_active_owner (id,storageScope,generation) VALUES (1, 'guest', 1)")
    }
}
