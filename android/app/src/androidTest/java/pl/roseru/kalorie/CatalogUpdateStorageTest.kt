package pl.roseru.kalorie

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.catalogupdate.*
import pl.roseru.kalorie.core.MealType
import pl.roseru.kalorie.core.catalog.*
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.data.*
import java.io.File
import java.time.LocalDate
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class CatalogUpdateStorageTest {
    private val context=ApplicationProvider.getApplicationContext<Context>()
    private inner class Fixture(sourceCount:Int=1) {
        val name="catalog-download-test-${UUID.randomUUID()}.db"
        var db=open()
        val gate=CatalogUpdateFixtures.Gate().apply{allow()}
        val data=CatalogUpdateFixtures.official(context,sourceCount=sourceCount)
        val gateway=CatalogUpdateFixtures.Gateway(data)
        val preferences=CatalogUpdateFixtures.PreferenceContext(context)
        val cache=File(context.cacheDir,"catalog-download-test-${UUID.randomUUID()}")
        var clock=1_900_000_000_000L
        fun open()=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        fun repository(network:NetworkAccessGate=gate)=CatalogUpdateRepository(db,CatalogUpdateFixtures.schema(context),gateway,network,cache,
            PreferencesCatalogRetryStore(preferences),{clock})
        suspend fun seedDiary() {
            val owners=LocalOwnerStore(db);owners.ensureGuest()
            val diary=DiaryRepository(db,context,owners.currentLease());diary.initialize()
            val product=db.dao().products().first().first{it.catalogJson!=null}
            diary.add(product.id,150.0,MealType.LUNCH,LocalDate.of(2026,10,20),UUID.randomUUID().toString(),"150")
        }
        fun close(){db.close();context.deleteDatabase(name);preferences.clear();cache.deleteRecursively()}
    }
    private suspend inline fun<reified E:Throwable> rejected(noinline action:suspend()->Unit):E {
        try{action()}catch(error:Throwable){if(error is E)return error;throw error}
        throw AssertionError("Expected ${E::class.java.simpleName}")
    }

    @Test fun validatedPublicInstallSurvivesRestartAndSourcesRemainReadableOfflineWithoutDiaryChanges()=runBlocking<Unit> {
        val f=Fixture(sourceCount=7)
        try {
            f.seedDiary();val before=CatalogUpdateFixtures.privateRows(f.db)
            val repo=f.repository()
            val available=repo.check() as CatalogCheck.Available
            assertEquals(CatalogPackageReader.OFFICIAL_ID,available.manifest.packageId)
            val result=repo.download(available.manifest,progress={_,_->}) as CatalogDownloadResult.Installed
            assertTrue(result.value.activated)
            assertEquals(1,f.db.catalogDao().active(CatalogPackageReader.OFFICIAL_ID)!!.release)
            assertNotNull(f.db.catalogDao().active(CatalogPackageReader.DEMO_ID))
            assertEquals(before,CatalogUpdateFixtures.privateRows(f.db))
            assertTrue(f.cache.listFiles().orEmpty().isEmpty())
            f.db.close();f.db=f.open();f.gate.block()
            val restored=f.repository()
            val saved=restored.installed.first().filterIsInstance<InstalledCatalog.Ready>().single{it.manifest.kind=="official"}.manifest
            assertEquals(available.manifest.sha256,saved.sha256)
            val first=restored.sources(saved,0);val last=restored.sources(saved,1)
            assertEquals(5,first.entries.size);assertTrue(first.hasNext);assertFalse(first.hasPrevious)
            assertEquals(2,last.entries.size);assertFalse(last.hasNext);assertTrue(last.hasPrevious)
            assertTrue((first.entries+last.entries).all{it.verified && it.checkedOn=="2026-10-23" && it.notes.single().contains("Synthetic fixture")})
            assertEquals(7,(first.entries+last.entries).map{it.id}.toSet().size)
            assertEquals(1,f.gateway.checks.get());assertEquals(1,f.gateway.downloads.get())
            assertEquals(before,CatalogUpdateFixtures.privateRows(f.db))
        }finally{f.close()}
    }

    @Test fun closedGatePartialCancellationAndHashMismatchPreserveThePreviousCatalogueAndQueue()=runBlocking<Unit> {
        val f=Fixture()
        try {
            f.seedDiary();val before=CatalogUpdateFixtures.privateRows(f.db)
            rejected<NetworkAccessDenied>{f.repository(ClosedNetworkAccessGate).check()}
            assertEquals(0,f.gateway.checks.get())
            val repo=f.repository();val available=repo.check() as CatalogCheck.Available
            val partial=CompletableDeferred<Unit>()
            f.gateway.onDownload={file,_->file.writeBytes(f.data.gzip.copyOf(f.data.gzip.size/2));partial.complete(Unit);awaitCancellation()}
            val running=launch{repo.download(available.manifest,progress={_,_->})}
            withTimeout(10_000){partial.await()};running.cancelAndJoin()
            assertTrue(f.cache.listFiles().orEmpty().isEmpty())
            assertNull(f.db.catalogDao().generation(CatalogPackageReader.OFFICIAL_ID,1))
            f.gateway.onDownload={_,_->}
            f.gateway.bytes=f.data.gzip.copyOf().also{it[it.lastIndex]=(it.last().toInt() xor 1).toByte()}
            val failure=rejected<CatalogError>{repo.download(available.manifest,progress={_,_->})}
            assertEquals("hash_mismatch",failure.code)
            assertNull(f.db.catalogDao().active(CatalogPackageReader.OFFICIAL_ID))
            assertNotNull(f.db.catalogDao().active(CatalogPackageReader.DEMO_ID))
            assertEquals(before,CatalogUpdateFixtures.privateRows(f.db))
            assertTrue(f.cache.listFiles().orEmpty().isEmpty())
        }finally{f.close()}
    }

    @Test fun blockedThenAllowedDuringACompletedTransferCannotReuseItsOldPermit()=runBlocking<Unit> {
        val f=Fixture()
        try {
            f.seedDiary();val before=CatalogUpdateFixtures.privateRows(f.db)
            val repo=f.repository();val selected=(repo.check() as CatalogCheck.Available).manifest
            f.gateway.onDownload={_,permit->f.gate.requireCurrent(permit);f.gate.block();f.gate.allow(2)}
            val failure=rejected<NetworkAccessDenied>{repo.download(selected,progress={_,_->})}
            assertEquals(NetworkDenial.STALE_PERMIT,failure.reason)
            assertTrue(f.gate.state.value is NetworkAccessState.Allowed)
            assertNull(f.db.catalogDao().generation(CatalogPackageReader.OFFICIAL_ID,1))
            assertEquals(before,CatalogUpdateFixtures.privateRows(f.db))
            assertTrue(f.cache.listFiles().orEmpty().isEmpty())
        }finally{f.close()}
    }

    @Test fun retryAfterSurvivesRepositoryAndPreferenceStoreRecreationWithoutAnotherRequest()=runBlocking<Unit> {
        val f=Fixture()
        try {
            f.gateway.response=CatalogHttpResult.Retry("120")
            val first=f.repository().check() as CatalogCheck.RetryAt
            assertEquals(f.clock+120_000,first.epochMillis)
            val restored=f.repository()
            assertEquals(first.epochMillis,(restored.check() as CatalogCheck.RetryAt).epochMillis)
            assertEquals(1,f.gateway.checks.get())
            f.clock=first.epochMillis+1;f.gateway.response=null
            assertTrue(restored.check() is CatalogCheck.Available)
            assertEquals(2,f.gateway.checks.get())
        }finally{f.close()}
    }

    @Test fun newerConcurrentReleaseWinsWithoutDowngradeOrPrivateWrites()=runBlocking<Unit> {
        val f=Fixture()
        try {
            f.seedDiary();val before=CatalogUpdateFixtures.privateRows(f.db)
            val repo=f.repository();val selected=(repo.check() as CatalogCheck.Available).manifest
            val newer=CatalogUpdateFixtures.official(context,release=2)
            f.gateway.onDownload={_,_->
                val value=CatalogPackageReader(CatalogUpdateFixtures.schema(context),CatalogPackageReader.OFFICIAL_ID,"official")
                    .read(newer.manifest.inputStream(),newer.gzip.inputStream())
                assertTrue(CatalogStore(f.db).import(value))
            }
            val result=repo.download(selected,progress={_,_->}) as CatalogDownloadResult.Installed
            assertFalse(result.value.activated);assertEquals(2,result.value.active.release)
            val checked=repo.check() as CatalogCheck.Current
            assertEquals(2,checked.local.release);assertEquals(1,checked.serverRelease)
            assertEquals(2,f.db.catalogDao().active(CatalogPackageReader.OFFICIAL_ID)!!.release)
            assertEquals(before,CatalogUpdateFixtures.privateRows(f.db))
        }finally{f.close()}
    }
}
