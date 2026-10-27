package pl.roseru.kalorie.catalogupdate

import androidx.room.withTransaction
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import pl.roseru.kalorie.core.catalog.*
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.data.CalorieDatabase
import pl.roseru.kalorie.data.CatalogGenerationEntity
import pl.roseru.kalorie.data.CatalogStore
import java.io.File

sealed interface InstalledCatalog {
    data class Ready(val manifest:CatalogManifest):InstalledCatalog
    data class Unreadable(val kind:String,val release:Int):InstalledCatalog
}
sealed interface CatalogCheck {
    data class Available(val manifest:CatalogManifest):CatalogCheck
    data class Current(val local:CatalogManifest,val serverRelease:Int):CatalogCheck
    data object NotPublished:CatalogCheck
    data object NotConfigured:CatalogCheck
    data class RetryAt(val epochMillis:Long):CatalogCheck
}
data class CatalogInstallation(val active:CatalogManifest,val activated:Boolean)

/** Uses the same validated generation store as the bundled package; never touches a diary/outbox. */
class CatalogUpdateRepository internal constructor(private val db:CalorieDatabase,schemaProvider:()->CatalogSchema,
    private val gateway:CatalogDownloadGateway?,private val gate:NetworkAccessGate,private val cache:File,private val retries:CatalogRetryStore,
    private val now:()->Long=System::currentTimeMillis) {
    internal constructor(db:CalorieDatabase,schema:CatalogSchema,gateway:CatalogDownloadGateway?,gate:NetworkAccessGate,
        cache:File,retries:CatalogRetryStore,now:()->Long=System::currentTimeMillis):this(db,{schema},gateway,gate,cache,retries,now)
    private val schema by lazy(schemaProvider)
    private val reader by lazy{CatalogPackageReader(schema,CatalogPackageReader.OFFICIAL_ID,"official")}
    @Volatile private var retryAtMemory=0L
    val configured:Boolean get()=gateway!=null
    val networkState get()=gate.state
    val installed:Flow<List<InstalledCatalog>> = db.catalogDao().activeGenerations().map { rows->
        rows.map { row->
            try {InstalledCatalog.Ready(description(row))}
            catch(error:CancellationException){throw error}
            catch(_:Exception){InstalledCatalog.Unreadable(row.kind,row.release)}
        }
    }.flowOn(Dispatchers.IO)

    /** Read-only provenance for an exact saved release, also available with the network blocked. */
    suspend fun sources(manifest:CatalogManifest,page:Int):CatalogSourcePage=withContext(Dispatchers.IO) {
        require(page>=0)
        val offset=Math.multiplyExact(page,CatalogSourcePage.SIZE)
        require(offset<maxOf(1,manifest.sources))
        db.withTransaction {
            val generation=checkNotNull(db.catalogDao().generation(manifest.packageId,manifest.release))
            check(description(generation).json==manifest.json)
            val entries=db.catalogDao().generationSources(generation.id,CatalogSourcePage.SIZE,offset).map {record->
                val source=StrictJson.read(record.payloadJson.toByteArray(Charsets.UTF_8))
                schema.validate(source,"Source")
                fun optional(name:String)=if(source.isNull(name))null else source.getString(name)
                fun texts(name:String):List<String> {val rows=source.getJSONArray(name);return (0 until rows.length()).map(rows::getString)}
                CatalogSource(source.getString("source_id"),source.getString("document_id"),optional("url"),
                    source.getString("checked_on"),optional("market"),optional("manufacturer"),optional("variant"),source.getString("basis"),
                    source.getString("status")=="verified",texts("missing_data"),texts("notes"))
            }
            check(entries.size==minOf(CatalogSourcePage.SIZE,manifest.sources-offset))
            CatalogSourcePage(manifest,page,entries)
        }
    }

    private fun description(row:CatalogGenerationEntity):CatalogManifest {
        val expected=when {
            row.kind=="demo" && row.packageId==MreCatalogueRules.PACKAGE_ID->MreCatalogueRules.PACKAGE_ID
            row.kind=="demo"->CatalogPackageReader.DEMO_ID
            row.kind=="official"->CatalogPackageReader.OFFICIAL_ID
            else->throw CatalogTransferRejected("catalog_identity")
        }
        check(row.complete && row.packageId==expected)
        return CatalogPackageReader(schema,expected,row.kind).inspect(row.manifestJson.byteInputStream()).also {
            check(it.release==row.release && it.sha256==row.sha256)
        }
    }
    private fun retry(value:String?):CatalogCheck.RetryAt {
        val at=now()
        val delay=pl.roseru.kalorie.session.BootstrapHttpProtocol.retrySeconds(value,at)
        val deadline=Math.addExact(at,Math.multiplyExact(delay,1000))
        retryAtMemory=maxOf(retryAtMemory,deadline)
        retries.deferUntil(retryAtMemory)
        return CatalogCheck.RetryAt(maxOf(retryAtMemory,retries.deadline()))
    }
    suspend fun check():CatalogCheck=withContext(Dispatchers.IO) {
        val client=gateway?:return@withContext CatalogCheck.NotConfigured
        val permit=gate.captureAllowed()
        val deadline=maxOf(retryAtMemory,retries.deadline())
        if(deadline>now())return@withContext CatalogCheck.RetryAt(deadline)
        when(val response=client.manifest(permit)) {
            is CatalogHttpResult.Missing->CatalogCheck.NotPublished
            is CatalogHttpResult.Retry->retry(response.value)
            is CatalogHttpResult.Success->{
                gate.requireCurrent(permit);ensureActive()
                val candidate=reader.inspect(checkNotNull(response.bytes).inputStream())
                db.withTransaction {
                    gate.requireCurrent(permit)
                    val active=db.catalogDao().active(candidate.packageId)
                    val local=active?.let{checkNotNull(db.catalogDao().generationById(it.generationId))}?.let(::description)
                    if(local!=null && local.release>=candidate.release) {
                        if(local.release==candidate.release && local.json!=candidate.json)
                            throw CatalogTransferRejected("release_conflict")
                        CatalogCheck.Current(local,candidate.release)
                    } else CatalogCheck.Available(candidate)
                }
            }
        }
    }
    /** Retry/missing never stages a generation or changes the active release. */
    internal suspend fun download(manifest:CatalogManifest,progress:(Long,Long)->Unit,validating:()->Unit={}):CatalogDownloadResult=withContext(Dispatchers.IO) {
        val client=gateway?:return@withContext CatalogDownloadResult.NotConfigured
        val permit=gate.captureAllowed();ensureActive()
        val deadline=maxOf(retryAtMemory,retries.deadline())
        if(deadline>now())return@withContext CatalogDownloadResult.RetryAt(deadline)
        require(manifest.packageId==CatalogPackageReader.OFFICIAL_ID && manifest.kind=="official")
        check(cache.isDirectory || cache.mkdirs())
        val temporary=File.createTempFile("catalog-",".download",cache)
        try {
            when(val response=client.download(manifest,temporary,permit,progress)) {
                is CatalogHttpResult.Missing->CatalogDownloadResult.Missing
                is CatalogHttpResult.Retry->CatalogDownloadResult.RetryAt(retry(response.value).epochMillis)
                is CatalogHttpResult.Success->{
                    gate.requireCurrent(permit);ensureActive()
                    validating()
                    val value=reader.read(manifest,temporary.inputStream())
                    gate.requireCurrent(permit);ensureActive()
                    val store=CatalogStore(db)
                    val installed=db.withTransaction {
                        // Both stage and activate roll back together on cancellation or failure.
                        currentCoroutineContext().ensureActive()
                        gate.requireCurrent(permit)
                        val staged=store.stage(value)
                        currentCoroutineContext().ensureActive()
                        gate.requireCurrent(permit)
                        val activated=store.activate(staged)
                        val current=checkNotNull(db.catalogDao().active(manifest.packageId))
                        val currentValue=description(checkNotNull(db.catalogDao().generationById(current.generationId)))
                        CatalogInstallation(currentValue,activated)
                    }
                    CatalogDownloadResult.Installed(installed)
                }
            }
        } finally {temporary.delete()}
    }
}

internal sealed interface CatalogDownloadResult {
    data class Installed(val value:CatalogInstallation):CatalogDownloadResult
    data object Missing:CatalogDownloadResult
    data object NotConfigured:CatalogDownloadResult
    data class RetryAt(val epochMillis:Long):CatalogDownloadResult
}
