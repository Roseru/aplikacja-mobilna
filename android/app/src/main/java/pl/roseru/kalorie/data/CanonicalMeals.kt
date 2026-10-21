package pl.roseru.kalorie.data

import androidx.room.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.time.Instant
import java.util.UUID

@Entity(tableName="photo_materializations",primaryKeys=["ownerScope","analysisId"],foreignKeys=[
    ForeignKey(entity=LocalOwnerEntity::class,parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT),
    ForeignKey(entity=MealEntity::class,parentColumns=["id"],childColumns=["mealId"],onDelete=ForeignKey.RESTRICT)],
    indices=[Index(value=["mealId"],unique=true)])
data class PhotoMaterialization(val ownerScope:String,val analysisId:String,val mealId:String,val sourceOperationId:String,
    val sourcePhotoId:String,val confirmationKey:String,val receiptJson:String,val snapshotJson:String,val provenanceJson:String,
    val wireContext:String,val firstOutboxId:String,val createdAt:String) {
    override fun toString()="PhotoMaterialization(redacted)"
}
@Dao interface PhotoMaterializationDao {
    @Query("SELECT * FROM photo_materializations WHERE ownerScope=:owner AND analysisId=:id") suspend fun get(owner:String,id:String):PhotoMaterialization?
    @Insert suspend fun insert(row:PhotoMaterialization)
}

internal object CanonicalMealRows {
    fun context(binding:AccountBindingEntity)=StrictJson.canonical(JSONObject().put("account_id",binding.accountId)
        .put("generation",binding.accountGeneration).put("sync_epoch",binding.syncEpoch).put("context_revision",binding.contextRevision))
    fun context(account:String,generation:Int,epoch:String,revision:Long)=context(AccountBindingEntity("",account,generation,epoch,"",revision,false))
    fun schema(context:android.content.Context)=SyncWireSchema(SyncWireSchema.FILES.associateWith {context.assets.open("sync/$it").use {stream->stream.readBytes()}})
    fun meal(id:String,owner:String,wire:MealWire,context:String,serverRevision:Int=0,localRevision:Int=1,deleted:Boolean=false):MealEntity {
        val value=wire.json();val ration=value.optJSONObject("ration")
        return MealEntity(id,owner,value.getString("local_date"),value.getString("occurred_at"),value.getString("time_zone"),
            if(value.isNull("meal_type"))"UNSPECIFIED" else value.getString("meal_type").uppercase(java.util.Locale.ROOT),
            serverRevision,localRevision,deleted,ration?.getString("ration_id"),ration?.getString("name"),wire.canonical,context)
    }
    fun items(mealId:String,wire:MealWire):List<MealItemEntity> {
        val rows=wire.json().getJSONArray("items")
        return (0 until rows.length()).map {i->
            val row=rows.getJSONObject(i);val p=MealWire.portion(row)
            MealItemEntity(row.getString("item_id"),mealId,row.optJSONObject("product")?.getString("product_id"),row.getString("name"),
                p.amount.toDouble(),p.per100.energy?.toDouble(),p.per100.protein?.toDouble(),p.per100.fat?.toDouble(),p.per100.carbs?.toDouble(),
                rationComponentPosition=if(row.isNull("ration_component_position"))null else row.getInt("ration_component_position"),wirePayload=StrictJson.canonical(row))
        }
    }
}

/** Local edits remain possible during recovery. Never reinterpret a legacy outbox row as wire JSON. */
internal class CanonicalMealEditor(private val db:CalorieDatabase,private val context:android.content.Context,private val lease:OwnerLease) {
    suspend fun change(id:String,itemId:String?=null,amount:String?=null,remove:Boolean=false):Boolean=withContext(Dispatchers.IO) {
        val dao=db.dao();val owners=LocalOwnerStore(db)
        val source=db.withTransaction {
            owners.requireCurrent(lease)
            val current=dao.meal(id,lease.storageScope)?:return@withTransaction null
            if(current.meal.wirePayload==null)return@withTransaction null
            Triple(current,dao.canonicalMealOperations(lease.storageScope,id),db.bootstrapDao().binding(lease.storageScope))
        }?:return@withContext false
        val (current,queued,binding)=source
        if(current.meal.deleted){require(itemId==null);return@withContext true}
        val schema=CanonicalMealRows.schema(context)
        val original=MealWire.read(checkNotNull(current.meal.wirePayload),schema)
        val next=if(itemId==null)null else if(remove)original.without(itemId,schema) else original.withAmount(itemId,checkNotNull(amount),schema)
        val deleted=next==null;val wire=next?:original
        val wireContext=checkNotNull(current.meal.wireContext)
        val contextCurrent=binding!=null && !binding.requiresRecovery && wireContext==CanonicalMealRows.context(binding)
        val inFlight=queued.any {it.attempted}
        val base=current.meal.serverRevision.takeIf {it>0}
        val status=if(!contextCurrent)"waiting_recovery" else if(inFlight)"waiting_revision" else if(deleted && base==null)"local_only" else "pending"
        val epoch=StrictJson.read(wireContext.toByteArray(Charsets.UTF_8)).getString("sync_epoch")
        val operationId=UUID.randomUUID().toString()
        val payload=if(deleted)null else wire.canonical
        val operation=if(status=="pending")MealWire.operation(operationId,id,epoch,base,payload,schema) else null
        val meal=CanonicalMealRows.meal(id,lease.storageScope,wire,wireContext,current.meal.serverRevision,Math.addExact(current.meal.localRevision,1),deleted)
        val items=if(deleted)current.items else CanonicalMealRows.items(id,wire)
        val outbox=OutboxEntity(operationId,lease.storageScope,"meal",id,if(deleted)"delete" else "upsert",base,payload?:"null",Instant.now().toString(),status,"sync-v1",operation,wireContext)
        db.withTransaction {
            owners.requireCurrent(lease)
            check(dao.meal(id,lease.storageScope)==current && dao.canonicalMealOperations(lease.storageScope,id)==queued && db.bootstrapDao().binding(lease.storageScope)==binding)
            dao.updateMeal(meal)
            if(!deleted) {
                val ids=items.map {it.id}.toSet();current.items.filter {it.id !in ids}.forEach {dao.removeItem(it)}
                items.forEach {dao.updateItem(it)}
            }
            queued.filter {!it.attempted}.forEach {dao.updateOperation(it.copy(status="superseded"))}
            dao.enqueue(outbox)
        }
        true
    }
}
