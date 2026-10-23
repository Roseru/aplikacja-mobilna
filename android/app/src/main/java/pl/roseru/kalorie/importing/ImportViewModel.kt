package pl.roseru.kalorie.importing

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.PrivateDomainsWire
import pl.roseru.kalorie.core.sync.SyncWireSchema
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.sync.*

/** Every action carries the lease captured by this owner-scoped ViewModel. No credentials in saved state. */
class ImportViewModel(private val db:CalorieDatabase,private val schema:SyncWireSchema,
    private val lease:OwnerLease,private val executor:ReconciliationStepExecutor,private val saved:SavedStateHandle):ViewModel() {
    private val imports=LegacyImportStore(db,schema)
    private val reconciliation=ReconciliationStore(db,schema)
    private val mutex=Mutex()
    private val mutable=MutableStateFlow(ImportUiState())
    val state=mutable.asStateFlow()
    init { action { reload() } }
    private suspend fun binding():AccountBindingEntity {
        LocalOwnerStore(db).requireCurrent(lease)
        return checkNotNull(db.bootstrapDao().binding(lease.storageScope))
    }
    private fun action(block:suspend ()->Unit) {viewModelScope.launch {
        if(!mutex.tryLock())return@launch
        mutable.value=mutable.value.copy(busy=true,message=null)
        try {block()} catch(cancelled:CancellationException){throw cancelled}
        catch(_:StaleOwnerException){mutable.value=mutable.value.copy(message="Konto zmieniło się. Otwórz ten ekran ponownie.")}
        catch(_:Exception){mutable.value=mutable.value.copy(message="Nie udało się wykonać tej decyzji. Dane pozostają zapisane. Odśwież podsumowanie i sprawdź brakujące informacje.")}
        finally {mutable.value=mutable.value.copy(busy=false);mutex.unlock()}
    }}
    fun refresh()=action {reload()}
    fun previewGuest()=preview("guest")
    fun previewOwn()=preview(lease.storageScope)
    private fun preview(source:String)=action {
        val context=binding()
        val progress=if(context.requiresRecovery)reconciliation.begin(lease,context) else imports.preview(lease,source)
        saved["import.plan"]=progress.planId;reload()
    }
    fun selectPlan(id:String)=action {saved["import.plan"]=id;reload()}
    fun approve(consented:Boolean)=action {
        require(consented)
        val progress=checkNotNull(mutable.value.plan);val context=binding()
        if(mutable.value.recovery)reconciliation.approve(lease,context,progress.planId,progress.account,progress.issuer,progress.subject)
        else imports.approve(lease,progress.planId,progress.account,progress.issuer,progress.subject)
        reload()
    }
    fun resume()=action {
        val id=checkNotNull(mutable.value.plan).planId
        repeat(100) {
            val before=imports.status(lease,id)
            if(before.pending==0 && before.waiting==0){reload();return@action}
            val after=imports.resume(lease,id)
            if(after.queued==before.queued && after.acknowledged==before.acknowledged && after.pending==before.pending && after.waiting==before.waiting) {
                reload();return@action
            }
            if(after.pending==0 && after.waiting==0){reload();return@action}
        }
        reload()
    }
    fun keep(row:ImportDecisionRow)=choose(row,if(mutable.value.recovery)"preserve_local" else "keep_local")
    fun separateCopy(row:ImportDecisionRow)=choose(row,"new_identity")
    fun acceptServer(row:ImportDecisionRow)=choose(row,"accept_server")
    fun replay(row:ImportDecisionRow)=choose(row,"replay_original")
    fun recreate(row:ImportDecisionRow)=choose(row,"recreate_missing")
    private fun choose(row:ImportDecisionRow,choice:String)=action {
        saveDecision(row,JSONObject().put("choice",choice).toString());reload()
    }
    fun correct(row:ImportDecisionRow,values:Map<String,String>,standaloneGoal:Boolean)=action {
        saveDecision(row,checkNotNull(row.form).choice(values,standaloneGoal));reload()
    }
    fun resolveMapped(row:ImportDecisionRow)=action {
        val target=checkNotNull(row.mapped)
        val choice=JSONObject().put("choice","resolve_existing").put("target_id",target.id)
        if(row.source.entityType=="goal")choice.put("payload",StrictJson.read(target.payload.toByteArray()))
        saveDecision(row,choice.toString());reload()
    }
    fun newGoal(row:ImportDecisionRow,values:Map<String,String>)=action {
        require(row.source.entityType=="goal")
        val context=binding();val plan=checkNotNull(mutable.value.plan)
        val copy=reconciliation.latestUiCopy(lease,context,plan.planId)
        val payload=JSONObject()
        for(key in listOf("effective_from","decided_at","time_zone","goal_type","energy_kcal","activity_class"))
            payload.put(key,values.getValue(key).trim().also {require(it.isNotEmpty())})
        for(key in listOf("protein_g","fat_g","carbs_g"))payload.put(key,values[key]?.trim()?.takeIf {it.isNotEmpty()} ?: JSONObject.NULL)
        payload.put("timeline_base_revision",copy.timelineRevision).put("reason","user_decision")
            .put("estimate",JSONObject.NULL).put("correction_of",JSONObject.NULL)
        val validated=PrivateDomainsWire.read("goal",StrictJson.canonical(payload),schema)
        saveDecision(row,JSONObject().put("choice","new_goal_decision").put("payload",StrictJson.read(validated.toByteArray())).toString())
        reload()
    }
    private suspend fun saveDecision(row:ImportDecisionRow,json:String) {
        val plan=checkNotNull(mutable.value.plan);val context=binding()
        require(row.source.planId==plan.planId)
        if(mutable.value.recovery) {
            val proof=reconciliation.latestCopy(lease,context,plan.planId)
            if(proof.first.id!=row.proofRunId)throw ImportContextChangedException()
            reconciliation.decide(lease,context,plan.planId,row.source.entityType,row.source.sourceId,row.source.sourceHash,json)
        }
        else imports.decide(lease,plan.planId,row.source.entityType,row.source.sourceId,row.source.sourceHash,json)
    }
    fun downloadProof()=network(ReconciliationStep.FULL_SNAPSHOT_RECEIPTS)
    fun sendApproved()=network(ReconciliationStep.PUSH_APPROVED)
    private fun network(step:ReconciliationStep)=action {
        val plan=checkNotNull(mutable.value.plan);val context=binding()
        val persisted=checkNotNull(db.importDao().plan(plan.planId))
        if(persisted.targetScope!=lease.storageScope || persisted.targetAccountId!=context.accountId ||
            persisted.wireContext!=CanonicalMealRows.context(context))throw ImportContextChangedException()
        val result=executor.runReconciliationStep(lease,context,plan.planId,step)
        reload()
        mutable.value=mutable.value.copy(message=when(result) {
            is SyncStepResult.Completed->"Etap zapisany. Sprawdź postęp i pozostałe decyzje."
            SyncStepResult.Busy->"Synchronizacja już trwa. Odśwież podsumowanie za chwilę."
            is SyncStepResult.RetryAt->"Serwer poprosił o przerwę. Spróbuj po ${java.time.Instant.ofEpochMilli(result.epochMillis)}."
            SyncStepResult.LoginRequired->"Zaloguj się ponownie na to konto, aby kontynuować."
            SyncStepResult.StaleContext->"Konto lub epoka synchronizacji zmieniły się. Otwórz aktualne podsumowanie."
            SyncStepResult.TransientFailure->"Brak połączenia lub chwilowy błąd. Możesz wznowić ten sam zapisany etap."
            SyncStepResult.NotConfigured->"Połączenie synchronizacji nie jest skonfigurowane."
            is SyncStepResult.ReconciliationRequired->"Pobierz aktualną kopię i sprawdź decyzje przed dalszą synchronizacją."
        })
    }
    fun finish()=action {
        val id=checkNotNull(mutable.value.plan).planId
        reconciliation.finish(lease,binding(),id);reload()
        mutable.value=mutable.value.copy(message="Uzgodnienie zakończone. Dziennik jest gotowy do synchronizacji.")
    }
    fun more(){mutable.value=mutable.value.copy(visible=mutable.value.visible+25)}
    private suspend fun reload() {
        val context=binding()
        val plans=db.importDao().plans(lease.storageScope).filter {it.wireContext==CanonicalMealRows.context(context)}
        val selected=plans.firstOrNull {it.id==saved.get<String>("import.plan")} ?: plans.firstOrNull()
        if(selected==null){mutable.value=mutable.value.copy(requiresRecovery=context.requiresRecovery,plan=null,rows=emptyList(),plans=emptyList());return}
        saved["import.plan"]=selected.id
        val recovery=selected.kind !in setOf("guest","legacy")
        val progress=if(recovery)reconciliation.status(lease,context,selected.id) else imports.status(lease,selected.id)
        val evidence=db.importDao().evidence(selected.id)
        val verified=if(recovery && reconciliation.groupsComplete(selected)) {
            try {reconciliation.latestCopy(lease,context,selected.id)}
            catch(cancelled:CancellationException){throw cancelled}
            catch(_:Exception){null}
        } else null
        val rows=db.importDao().sources(selected.id).filter {it.state in setOf("decision","pending_snapshot")}.map {source->
            val root=StrictJson.read(source.sourceJson.toByteArray())
            val copy=verified?.second
            val mapping=copy?.mappings?.map {StrictJson.read(it.toByteArray())}?.firstOrNull {
                it.optString("source_epoch")==source.sourceEpoch && it.optString("source_entity_id")==root.optString("wire_id")}
            val serverId=mapping?.getString("target_entity_id") ?: root.optString("wire_id",source.wireId)
            val entity=copy?.entities?.singleOrNull {it.type==source.entityType && it.id==serverId}
            val target=if(mapping!=null && entity!=null && !entity.deleted && entity.payload!=null)
                ImportMappedTarget(entity.id,entity.payload) else null
            var formFailure=false
            val form=if(recovery)null else try {LegacyImportForm.from(source)}
                catch(_:Exception){formFailure=true;null}
            ImportDecisionRow(source,source.decisionCode ?: "decision_required",form,target,
                source.sourceEpoch!=null && source.sourceEpoch==context.syncEpoch,
                local=ImportComparison.local(source),
                server=if(copy==null)ImportComparisonSide(ImportSideState.UNVERIFIED)
                    else ImportComparison.server(source.entityType,entity?.payload,entity?.deleted==true),
                proofRunId=verified?.first?.id,formFailure=formFailure)
        }
        mutable.value=mutable.value.copy(plan=progress,requiresRecovery=context.requiresRecovery,recovery=recovery,
            approved=selected.approvedAt!=null,rows=rows,proofGroups=if(recovery)reconciliation.groups(selected).size else 0,
            provedGroups=evidence.filter {it.kind=="receipt_group"}.map {it.identity}.distinct().size,plans=plans.map {ImportPlanChoice(it.id,it.kind,it.createdAt,it.state)})
    }
}

data class ImportMappedTarget(val id:String,val payload:String)
data class ImportDecisionRow(val source:ImportSource,val code:String,val form:LegacyImportForm?,val mapped:ImportMappedTarget?,val sameEpoch:Boolean,
    val local:ImportComparisonSide?=null,val server:ImportComparisonSide=ImportComparisonSide(ImportSideState.UNVERIFIED),
    val proofRunId:String?=null,val formFailure:Boolean=false)
data class ImportPlanChoice(val id:String,val kind:String,val date:String,val state:String)
data class ImportUiState(val plan:ImportProgress?=null,val approved:Boolean=false,val recovery:Boolean=false,
    val requiresRecovery:Boolean=false,val rows:List<ImportDecisionRow> = emptyList(),val plans:List<ImportPlanChoice> = emptyList(),
    val visible:Int=25,val busy:Boolean=false,val message:String?=null,val proofGroups:Int=0,val provedGroups:Int=0)

/** The store's validated copy; no new publication or unguarded raw parsing in UI. */
private suspend fun ReconciliationStore.latestUiCopy(lease:OwnerLease,context:AccountBindingEntity,id:String)=latestCopy(lease,context,id).second