package pl.roseru.kalorie

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.*
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import pl.roseru.kalorie.data.DiaryRepository
import pl.roseru.kalorie.session.SessionActions
import pl.roseru.kalorie.session.PhotoDraftActions
import pl.roseru.kalorie.data.ThemeMode
import pl.roseru.kalorie.ui.CalorieApp
import pl.roseru.kalorie.ui.CalorieTheme

class MainActivity : ComponentActivity() {
    private val ownerModels: OwnerViewModels by viewModels()
    private val login = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val app = application as CalorieApplication
        // Queue behind Application's startup so a restored PKCE callback sees
        // the saved session record; the controller serializes them with its mutex.
        app.sessionScope.launch(Dispatchers.Main) { app.sessions.completeLogin(result.data) }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val app = application as CalorieApplication
        setContent {
            val session by app.sessions.view.collectAsStateWithLifecycle()
            val binding = session.binding
            if (binding == null) {
                ownerModels.clearOwner()
                CalorieTheme(isSystemInDarkTheme()) {
                    androidx.compose.material3.Surface {
                        androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.padding(24.dp)) {
                            androidx.compose.material3.Text(session.message ?: "Otwieram lokalny dziennik")
                            if (session.message != null) androidx.compose.material3.Button(onClick = { app.sessionScope.launch { app.sessions.start() } }) {
                                androidx.compose.material3.Text("Spróbuj ponownie")
                            }
                        }
                    }
                }
                return@setContent
            }
            val ownerKey = "${binding.lease.storageScope}:${binding.lease.generation}"
            key(ownerKey) {
            val store = ownerModels.forOwner(ownerKey)
            val model: DiaryViewModel = viewModel(viewModelStoreOwner = store, key = ownerKey,
                extras = defaultViewModelCreationExtras, factory = viewModelFactory {
                initializer { DiaryViewModel(DiaryRepository(app.database, app, binding.lease), app.preferences, createSavedStateHandle()) }
            })
            val photoModel: pl.roseru.kalorie.photo.MealPhotoViewModel = viewModel(viewModelStoreOwner = store, key = "$ownerKey:photo",
                extras = defaultViewModelCreationExtras, factory = viewModelFactory {
                initializer { pl.roseru.kalorie.photo.MealPhotoViewModel(app,
                    pl.roseru.kalorie.photo.MealPhotoStore(app, app.database, binding.lease), createSavedStateHandle()) }
            })
            val mode by model.theme.collectAsStateWithLifecycle()
            val dark = when (mode) { ThemeMode.SYSTEM -> isSystemInDarkTheme(); ThemeMode.LIGHT -> false; ThemeMode.DARK -> true }
            SideEffect {
                val style = if (dark) SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
                    else SystemBarStyle.light(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT)
                enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
            }
            val actions = SessionActions(
                login = { app.sessionScope.launch { app.sessions.beginLogin()?.let { intent ->
                    try { login.launch(intent) } catch (_: Exception) { app.sessions.cancelLogin() }
                } } },
                logout = { app.sessionScope.launch { app.sessions.logout() } },
                refresh = { app.sessionScope.launch { app.sessions.refresh() } },
                cancel = { app.sessionScope.launch { app.sessions.cancelLogin() } },
                bootstrap = { app.sessionScope.launch { app.sessions.bootstrap() } },
                readProfile = { app.sessionScope.launch { app.sessions.readProfile() } },
                downloadSnapshot = { app.sessionScope.launch { app.sessions.downloadSnapshot() } },
                readMotivation = { app.sessionScope.launch { app.sessions.readMotivation() } },
                readRankingConsents = { app.sessionScope.launch { app.sessions.readRankingConsents() } },
                confirmRankingConsent = { id, enabled -> app.sessionScope.launch { app.sessions.confirmRankingConsent(id, enabled) } },
                retryRankingConsent = { app.sessionScope.launch { app.sessions.retryRankingConsent() } },
                readRanking = { app.sessionScope.launch { app.sessions.readRanking() } },
                nextRankingPage = { app.sessionScope.launch { app.sessions.nextRankingPage() } },
                retryRankingPage = { app.sessionScope.launch { app.sessions.retryRankingPage() } },
                clearRanking = { app.sessionScope.launch { app.sessions.clearRankingPreview() } },
                readNemesis = { app.sessionScope.launch { app.sessions.readNemesis() } },
                readNemesisChallenge = { id -> app.sessionScope.launch { app.sessions.readNemesisChallenge(id) } },
                nextNemesisPage = { app.sessionScope.launch { app.sessions.nextNemesisPage() } },
                retryNemesis = { app.sessionScope.launch { app.sessions.retryNemesis() } },
                clearNemesis = { app.sessionScope.launch { app.sessions.clearNemesisPreview() } },
                issueNemesisCode = { app.sessionScope.launch { app.sessions.issueNemesisCode() } },
                revokeNemesisCode = { app.sessionScope.launch { app.sessions.revokeNemesisCode() } },
                createNemesis = { code,days,zone,weight,deficit,ack -> app.sessionScope.launch { app.sessions.createNemesis(code,days,zone,weight,deficit,ack) } },
                acceptNemesis = { id,ack,weight,deficit -> app.sessionScope.launch { app.sessions.acceptNemesis(id,ack,weight,deficit) } },
                cancelNemesis = { id -> app.sessionScope.launch { app.sessions.cancelNemesis(id) } },
                retryNemesisMutation = { app.sessionScope.launch { app.sessions.retryNemesisMutation() } },
                readPhotoCapabilities = { app.sessionScope.launch { app.sessions.readPhotoCapabilities() } },
                uploadPhoto = { id,consent,accepted -> app.sessionScope.launch { app.sessions.uploadPhoto(binding.lease,id,consent,accepted) } },
                retryPhotoUpload = { app.sessionScope.launch { app.sessions.retryPhotoUpload(binding.lease) } },
                discardUnsentPhotoUpload = { app.sessionScope.launch { app.sessions.discardUnsentPhotoUpload(binding.lease) } },
                readPhotoAnalysis = { app.sessionScope.launch { app.sessions.readPhotoAnalysis(binding.lease) } },
                restorePhotoAnalysis = { app.sessionScope.launch { app.sessions.loadPhotoAnalysis(binding.lease) } },
                stopPhotoAnalysis = { app.sessionScope.launch { app.sessions.stopPhotoAnalysis(binding.lease) } },
                clearPhotoAnalysis = { app.sessionScope.launch { app.sessions.stopPhotoAnalysis(binding.lease,clearPreview=true) } },
                cancelPhotoAnalysis = { id,revision -> app.sessionScope.launch { app.sessions.cancelPhotoAnalysis(binding.lease,id,revision) } },
                retryPhotoCancellation = { id -> app.sessionScope.launch { app.sessions.retryPhotoCancellation(binding.lease,id) } },
                releaseCancelledPhoto = { id -> app.sessionScope.launch { app.sessions.releaseCancelledPhoto(binding.lease,id) } },
                photoDraft = PhotoDraftActions(
                    start={id,revision,date->app.sessionScope.launch {app.sessions.startPhotoMealDraft(binding.lease,id,revision,date)}},
                    replace={id,revision,item,input->app.sessionScope.launch {app.sessions.replacePhotoMealDraftItem(binding.lease,id,revision,item,input)}},
                    add={id,revision,input->app.sessionScope.launch {app.sessions.addPhotoMealDraftItem(binding.lease,id,revision,input)}},
                    remove={id,revision,item->app.sessionScope.launch {app.sessions.removePhotoMealDraftItem(binding.lease,id,revision,item)}},
                    rename={id,revision,title->app.sessionScope.launch {app.sessions.renamePhotoMealDraft(binding.lease,id,revision,title)}},
                    discard={id,revision->app.sessionScope.launch {app.sessions.discardPhotoMealDraft(binding.lease,id,revision)}},
                    confirm={id,revision,edit->app.sessionScope.launch {app.sessions.confirmPhotoMeal(binding.lease,id,revision,edit)}},
                    retryConfirmation={id->app.sessionScope.launch {app.sessions.retryPhotoConfirmation(binding.lease,id)}}))
            CalorieTheme(dark) { CalorieApp(model, session, actions, photoModel) }
            }
        }
    }
}

/** Retained across rotation, cleared before handing a new lease to any diary screen. */
class OwnerViewModels : ViewModel() {
    private var ownerKey: String? = null
    private val store = ViewModelStore()
    private val owner = object : ViewModelStoreOwner { override val viewModelStore = store }
    fun forOwner(key: String): ViewModelStoreOwner {
        if (ownerKey != key) { store.clear(); ownerKey = key }
        return owner
    }
    fun clearOwner() { store.clear(); ownerKey = null }
    override fun onCleared() = clearOwner()
}
