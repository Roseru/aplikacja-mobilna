package pl.roseru.kalorie

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.*
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

data class DayState(val date: LocalDate = LocalDate.now(), val meals: List<MealWithItems> = emptyList(), val goal: GoalEntity? = null, val status: DiaryDayEntity? = null) {
    val totals: Nutrients get() = meals.flatMap { it.items }.map { it.consumed() }.total()
    val complete: Boolean get() = status?.declaredComplete == true && meals.isNotEmpty() && totals.kcal > 0
}
sealed interface DiaryEvent {
    data object MealSaved : DiaryEvent
    data class Message(val text: String) : DiaryEvent
}

@OptIn(ExperimentalCoroutinesApi::class)
class DiaryViewModel(private val repository: DiaryRepository, private val preferences: Preferences, saved: SavedStateHandle) : ViewModel() {
    private val dateText = saved.getStateFlow("date", LocalDate.now().toString())
    private val savedState = saved
    val ready = MutableStateFlow(false)
    val startupError = MutableStateFlow<String?>(null)
    val busy = MutableStateFlow(false)
    val weightSaveVersion = MutableStateFlow(0)
    private val channel = Channel<DiaryEvent>(Channel.BUFFERED)
    val events = channel.receiveAsFlow()
    private val policy = SharingStarted.WhileSubscribed(5000)
    val theme = preferences.theme.stateIn(viewModelScope, policy, ThemeMode.SYSTEM)
    val products = repository.dao.products().stateIn(viewModelScope, policy, emptyList())
    val rations = repository.dao.rations().stateIn(viewModelScope, policy, emptyList())
    val profile = repository.dao.profile(DiaryRepository.GUEST).stateIn(viewModelScope, policy, null)
    val weights = repository.dao.weights(DiaryRepository.GUEST).stateIn(viewModelScope, policy, emptyList())
    val recent = repository.dao.recent(DiaryRepository.GUEST).stateIn(viewModelScope, policy, emptyList())
    val pending = repository.dao.pending(DiaryRepository.GUEST).stateIn(viewModelScope, policy, 0)
    val todayGoal = repository.dao.goal(DiaryRepository.GUEST, LocalDate.now().toString()).stateIn(viewModelScope, policy, null)
    val day = dateText.flatMapLatest { text ->
        combine(repository.dao.day(DiaryRepository.GUEST, text), repository.dao.goal(DiaryRepository.GUEST, text),
            repository.dao.diaryDay(DiaryRepository.GUEST, text)) { meals, goal, status -> DayState(LocalDate.parse(text), meals, goal, status) }
    }.stateIn(viewModelScope, policy, DayState())

    init { initialize() }
    fun initialize() {
        startupError.value = null
        viewModelScope.launch {
            try { repository.initialize(); ready.value = true }
            catch (error: CancellationException) { throw error }
            catch (_: Exception) { startupError.value = "Nie udało się otworzyć lokalnego dziennika. Spróbuj ponownie." }
        }
    }
    fun changeDay(days: Long) { savedState["date"] = LocalDate.parse(dateText.value).plusDays(days).toString() }
    fun today() { savedState["date"] = LocalDate.now().toString() }
    fun selectDate(date: LocalDate) { savedState["date"] = date.toString() }
    fun setTheme(theme: ThemeMode) { viewModelScope.launch { preferences.setTheme(theme) } }
    fun add(productId: String, grams: Double, type: MealType) {
        val date = LocalDate.parse(dateText.value)
        val id = UUID.randomUUID().toString()
        mutate { repository.add(productId, grams, type, date, id); channel.send(DiaryEvent.MealSaved) }
    }
    fun edit(id: String, grams: Double) = mutate { repository.edit(id, grams) }
    fun addRation(rationId: String, quantities: Map<String, Double>, type: MealType) {
        val date = LocalDate.parse(dateText.value)
        val id = UUID.randomUUID().toString()
        mutate { repository.addRation(rationId, quantities, type, date, id); channel.send(DiaryEvent.MealSaved) }
    }
    fun editItem(mealId: String, itemId: String, grams: Double) = mutate { repository.editItem(mealId, itemId, grams) }
    fun removeItem(mealId: String, itemId: String) = mutate { repository.removeItem(mealId, itemId) }
    fun addCustom(draft: CustomProductDraft, grams: Double, type: MealType) {
        val date = LocalDate.parse(dateText.value)
        val mealId = UUID.randomUUID().toString()
        val productId = UUID.randomUUID().toString()
        mutate { repository.addCustomProduct(draft, grams, type, date, mealId, productId); channel.send(DiaryEvent.MealSaved) }
    }
    fun setProfile(nickname: String, height: Double, activity: ActivityClass, aim: DietAim) = mutate {
        repository.setProfile(nickname, height, activity, aim); channel.send(DiaryEvent.Message("Profil zapisany na urządzeniu."))
    }
    fun addWeight(kg: Double, date: LocalDate) = mutate {
        repository.addWeight(kg, date)
        weightSaveVersion.value += 1
        channel.send(DiaryEvent.Message("Pomiar wagi zapisany."))
    }
    fun editWeight(id: String, kg: Double) = mutate { repository.editWeight(id, kg) }
    fun deleteWeight(id: String) = mutate { repository.deleteWeight(id) }
    fun setDayComplete(declared: Boolean) {
        val date = LocalDate.parse(dateText.value)
        mutate { repository.setDayComplete(date, declared) }
    }
    fun delete(id: String) = mutate { repository.delete(id) }
    fun setGoal(kcal: Double, protein: Double?, fat: Double?, carbs: Double?) = mutate {
        repository.setGoal(kcal, protein, fat, carbs)
        channel.send(DiaryEvent.Message("Cel zapisany. Obowiązuje od dzisiaj."))
    }
    private fun mutate(action: suspend () -> Unit) {
        if (busy.value) return
        busy.value = true
        viewModelScope.launch {
            try { action() }
            catch (error: CancellationException) { throw error }
            catch (_: Exception) { channel.send(DiaryEvent.Message("Nie udało się zapisać zmiany. Dane pozostają na urządzeniu. Spróbuj ponownie.")) }
            finally { busy.value = false }
        }
    }
}
