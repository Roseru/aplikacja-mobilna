package pl.roseru.kalorie.data

import pl.roseru.kalorie.core.normalizeSearch
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.core.catalog.StrictJson

/** Called only inside the same transaction as source ledger and new outbox operation. */
internal class ImportProjection(private val db:CalorieDatabase,private val schema:SyncWireSchema) {
    suspend fun apply(plan:ImportPlan,source:ImportSource,payload:String,binding:AccountBindingEntity,revision:Int) {
        val owner=plan.targetScope;val id=source.localId;val type=source.entityType
        val context=CanonicalMealRows.context(binding)
        when(type) {
            "meal"->{
                val wire=MealWire.read(payload,schema);val old=db.dao().meal(id,owner)
                val row=CanonicalMealRows.meal(id,owner,wire,context,revision,old?.meal?.localRevision ?: 1)
                if(old==null)db.dao().insertMeal(row) else db.dao().updateMeal(row)
                val items=db.localMealItems(owner,id,wire);val ids=items.map {it.id}.toSet()
                old?.items?.filter {it.id !in ids}?.forEach {db.dao().removeItem(it)}
                items.forEach {item->if(old?.items?.any {it.id==item.id}==true)db.dao().updateItem(item) else db.dao().insertItem(item)}
            }
            "weight"->{
                val wire=WeightWire.read(payload,schema);val value=wire.json()
                val old=db.dao().weight(id,owner)
                db.dao().saveWeight(WeightEntity(id,owner,value.getString("local_date"),value.getString("occurred_at"),
                    value.getString("time_zone"),value.getString("weight_kg").toDouble(),localRevision=old?.localRevision ?: 1))
                val state=CanonicalWeightState(id,owner,wire.canonical,context,revision)
                if(db.weightSyncDao().state(owner,id)==null)db.weightSyncDao().insert(state) else db.weightSyncDao().update(state)
            }
            else->{
                val value=StrictJson.read(PrivateDomainsWire.read(type,payload,schema).toByteArray())
                fun number(key:String):Double?=if(value.isNull(key))null else value.getString(key).toDouble()
                when(type) {
                    "profile"->{
                        val current=db.dao().currentProfile(owner);check(current==null || current.id==id)
                        val original=StrictJson.read(source.sourceJson.toByteArray()).getJSONObject("row")
                        db.dao().saveProfile(ProfileEntity(id,owner,value.getString("pseudonym"),number("height_cm"),
                            when(value.getString("activity_class")){"stationary"->"GARRISON";"line"->"LINE";else->"COMMANDO"},
                            original.getString("dietAim"),value.getString("time_zone"),current?.localRevision ?: 1))
                    }
                    "goal"->{
                        val old=db.dao().goalById(owner,id)
                        if(old==null)db.dao().saveGoal(GoalEntity(id,owner,value.getString("effective_from"),checkNotNull(number("energy_kcal")),
                            number("protein_g"),number("fat_g"),number("carbs_g"),Math.addExact(db.dao().goalSequence(owner),1),
                            value.getString("decided_at"),value.getString("time_zone"),value.getString("reason"),
                            if(value.isNull("correction_of"))null else db.localSyncId(owner,"goal",value.getString("correction_of")),
                            if(value.isNull("estimate"))null else StrictJson.canonical(value.getJSONObject("estimate"))))
                        // Existing immutable legacy goal remains byte-for-byte; canonical sidecar owns confirmed audit.
                    }
                    "diary_day"->{
                        val current=db.dao().currentDiaryDay(owner,value.getString("local_date"));check(current==null || current.id==id)
                        db.dao().saveDiaryDay(DiaryDayEntity(id,owner,value.getString("local_date"),value.getBoolean("declared_complete"),current?.localRevision ?: 1))
                    }
                    "product_draft"->{
                        val nutrition=value.getJSONObject("nutrition_per_100");val name=value.getString("name")
                        fun nutrient(key:String):Double?=if(nutrition.isNull(key))null else nutrition.getString(key).toDouble()
                        val pack=value.optJSONObject("package_quantity")
                        val amount=if(pack?.getString("unit")==value.getString("basis_unit"))pack.getString("amount").toDouble() else 100.0
                        val row=ProductEntity(id,name,normalizeSearch(name),nutrient("energy_kcal") ?: 0.0,nutrient("protein_g"),nutrient("fat_g"),nutrient("carbs_g"),
                            amount,"Twoje produkty",value.getString("source_description"),0,owner,wirePayload=payload)
                        val old=db.serverDiaryDao().product(id);check(old==null || old.ownerScope==owner && old.catalogJson==null)
                        if(old==null)db.dao().insertProduct(row) else db.serverDiaryDao().update(row)
                    }
                }
                db.domainSyncDao().save(CanonicalDomainState(owner,type,source.wireId,id,payload,context,revision))
            }
        }
    }
}
