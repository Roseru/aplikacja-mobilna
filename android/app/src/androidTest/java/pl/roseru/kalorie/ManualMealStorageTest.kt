package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import java.time.LocalDate
import java.util.UUID
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*

/** Actual public repository/Room path; synthetic binding only, no live API acceptance. */
class ManualMealStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private fun draft()=CustomProductDraft("Ręczny posiłek",100.5,null,0.0,12.25,"Własna etykieta")
    private suspend fun account(db:CalorieDatabase,bootstrap:Boolean=true):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/manual",UUID.randomUUID().toString()).id)
        if(bootstrap){val store=AccountBootstrapStore(db);store.apply(store.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),epoch,1,"2026-10-19T12:00:00Z"))}
        return lease
    }
    private suspend fun rejected(action:suspend()->Unit) {
        var failed=false;try{action()}catch(e:CancellationException){throw e}catch(_:Exception){failed=true}
        assertTrue("Expected atomic refusal; private values suppressed",failed)
    }

    @Test fun privateProductAndManualMealUseOneAtomicWireOperationWithoutPublishingProduct()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val id=UUID.randomUUID().toString();val product=UUID.randomUUID().toString()
            val repo=DiaryRepository(db,context,lease)
            repo.addCustomProduct(draft(),150.5,MealType.LUNCH,LocalDate.now(),id,product)
            val meal=db.dao().meal(id,lease.storageScope)!!;val row=db.dao().canonicalMealOperations(lease.storageScope,id).single()
            val item=meal.items.single();val wire=MealWire.read(meal.meal.wirePayload!!,CanonicalMealRows.schema(context))
            assertEquals(product,item.productId);assertNotNull(item.wirePayload);assertEquals("150.5",item.amountText)
            assertEquals("sync-v1",row.wireFormat);assertEquals("pending",row.status);assertEquals("upsert",row.action)
            assertEquals(wire.canonical,row.payload);assertNull(row.baseRevision);assertFalse(row.attempted)
            assertTrue(wire.json().getJSONArray("items").getJSONObject(0).isNull("product"))
            assertEquals(2,db.dao().operationCount(lease.storageScope)) // local draft plus independent Meal
            repo.addCustomProduct(draft(),150.5,MealType.LUNCH,LocalDate.now(),id,product)
            assertEquals(2,db.dao().operationCount(lease.storageScope))
            assertEquals("Własna etykieta",db.dao().product(product,lease.storageScope)!!.source)
        }finally{db.close()}
    }
    @Test fun guestAndUnlinkedAccountKeepLocalWritesAndOriginalQueueFormat()=runBlocking<Unit> {
        for(linkedAccount in listOf(false,true)) {
            val db=memory()
            try {
                val lease=if(linkedAccount)account(db,false) else LocalOwnerStore(db).let {it.ensureGuest();it.currentLease()}
                val id=UUID.randomUUID().toString();val repo=DiaryRepository(db,context,lease)
                repo.addCustomProduct(draft(),100.0,MealType.SNACK,LocalDate.now(),id)
                val meal=db.dao().meal(id,lease.storageScope)!!
                assertNull(meal.meal.wirePayload);assertNull(meal.items.single().wirePayload)
                assertTrue(db.dao().canonicalMealOperations(lease.storageScope,id).isEmpty())
                assertEquals(2,db.dao().operationCount(lease.storageScope))
            }finally{db.close()}
        }
    }
    @Test fun excessPrecisionAndRecoveryStayLocalWithoutRoundingOrLoss()=runBlocking<Unit> {
        for(recovery in listOf(false,true)) {
            val db=memory()
            try {
                val lease=account(db)
                if(recovery){val b=db.bootstrapDao().binding(lease.storageScope)!!;db.bootstrapDao().update(b.copy(requiresRecovery=true))}
                val id=UUID.randomUUID().toString();val amount=if(recovery)150.0 else 1.0000001
                DiaryRepository(db,context,lease).addCustomProduct(draft(),amount,MealType.LUNCH,LocalDate.now(),id)
                val meal=db.dao().meal(id,lease.storageScope)!!
                assertNull(meal.meal.wirePayload);assertEquals(amount,meal.items.single().grams,0.0)
                assertEquals(2,db.dao().operationCount(lease.storageScope))
            }finally{db.close()}
        }
    }
    @Test fun failedCanonicalQueueInsertRollsBackProductDraftMealAndItemsTogether()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val id=UUID.randomUUID().toString();val product=UUID.randomUUID().toString()
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_manual BEFORE INSERT ON outbox WHEN NEW.wireFormat='sync-v1' BEGIN SELECT RAISE(ABORT,'synthetic write failure'); END")
            rejected{DiaryRepository(db,context,lease).addCustomProduct(draft(),100.0,MealType.DINNER,LocalDate.now(),id,product)}
            assertNull(db.dao().meal(id,lease.storageScope));assertNull(db.dao().product(product,lease.storageScope))
            assertEquals(0,db.dao().operationCount(lease.storageScope))
            assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
        }finally{db.close()}
    }
    @Test fun staleOwnerCannotInsertAnyPartOfTheNewManualMeal()=runBlocking<Unit> {
        val db=memory()
        try {
            val first=account(db);val repo=DiaryRepository(db,context,first);val id=UUID.randomUUID().toString()
            val other=account(db)
            rejected{repo.addCustomProduct(draft(),100.0,MealType.BREAKFAST,LocalDate.now(),id)}
            assertNull(db.dao().meal(id,first.storageScope));assertNull(db.dao().meal(id,other.storageScope))
            assertEquals(0,db.dao().operationCount(first.storageScope));assertEquals(0,db.dao().operationCount(other.storageScope))
        }finally{db.close()}
    }
    @Test fun editRetainsPrivateProductAndItemIdentityAndDeletionNeverSendsUncreatedMeal()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val repo=DiaryRepository(db,context,lease);val id=UUID.randomUUID().toString();val product=UUID.randomUUID().toString()
            repo.addCustomProduct(draft(),100.0,MealType.SNACK,LocalDate.now(),id,product)
            val item=db.dao().meal(id,lease.storageScope)!!.items.single()
            repo.editItem(id,item.id,125.000001,"125.000001")
            val edited=db.dao().meal(id,lease.storageScope)!!
            assertEquals(product,edited.items.single().productId);assertEquals(item.id,edited.items.single().id)
            assertEquals("125.000001",edited.items.single().amountText)
            val pending=db.dao().canonicalMealOperations(lease.storageScope,id).filter{it.status=="pending"}
            assertEquals(1,pending.size);assertEquals(edited.meal.wirePayload,pending.single().payload)
            repo.delete(id)
            assertTrue(db.dao().meal(id,lease.storageScope)!!.meal.deleted)
            assertTrue(db.dao().canonicalMealOperations(lease.storageScope,id).none{it.status=="pending"})
        }finally{db.close()}
    }
    @Test fun existingCatalogueEntryIsNotRecastAsManualOrPublished()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val id=UUID.randomUUID().toString()
            db.dao().seedProducts(listOf(ProductEntity("demo-local","Demo","demo",100.0,null,null,null,100.0,"Demo","Local demo",1)))
            DiaryRepository(db,context,lease).add("demo-local",100.0,MealType.LUNCH,LocalDate.now(),id)
            assertNull(db.dao().meal(id,lease.storageScope)!!.meal.wirePayload)
            assertTrue(db.dao().canonicalMealOperations(lease.storageScope,id).isEmpty())
        }finally{db.close()}
    }
    @Test fun reopeningDatabaseKeepsOneMealAndTheSamePersistedOperation()=runBlocking<Unit> {
        val name="manual-${UUID.randomUUID()}"
        var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        try {
            val lease=account(db);val id=UUID.randomUUID().toString();val product=UUID.randomUUID().toString()
            DiaryRepository(db,context,lease).addCustomProduct(draft(),125.5,MealType.SNACK,LocalDate.now(),id,product)
            val meal=db.dao().meal(id,lease.storageScope);val operation=db.dao().canonicalMealOperations(lease.storageScope,id).single()
            db.close();db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
            val current=LocalOwnerStore(db).currentLease()
            DiaryRepository(db,context,current).addCustomProduct(draft(),125.5,MealType.SNACK,LocalDate.now(),id,product)
            assertEquals(meal,db.dao().meal(id,current.storageScope))
            assertEquals(operation,db.dao().canonicalMealOperations(current.storageScope,id).single())
            assertEquals(2,db.dao().operationCount(current.storageScope))
        }finally{db.close();context.deleteDatabase(name)}
    }
}
