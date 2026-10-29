package pl.roseru.kalorie.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Assignment
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.compose.*
import pl.roseru.kalorie.DiaryEvent
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.session.*

@Composable fun CalorieApp(model: DiaryViewModel, session: SessionView, actions: SessionActions, photoModel: pl.roseru.kalorie.photo.MealPhotoViewModel, importModel:pl.roseru.kalorie.importing.ImportViewModel?=null,syncStatus:String?=null,
    deviceNetworkModels:DeviceNetworkModels?=null,communityModel:pl.roseru.kalorie.community.CommunityViewModel?=null,
    energyModel:pl.roseru.kalorie.energy.EnergyViewModel?=null,snapshotMaintenanceModel:pl.roseru.kalorie.sync.SnapshotMaintenanceViewModel?=null,
    syncOverviewModel:pl.roseru.kalorie.sync.AccountSyncOverviewViewModel?=null) {
    val ready by model.ready.collectAsStateWithLifecycle()
    val error by model.startupError.collectAsStateWithLifecycle()
    val nav = rememberNavController()
    val snackbar = remember { SnackbarHostState() }
    val backStack by nav.currentBackStackEntryAsState()
    val route = backStack?.destination?.route
    val networkState=deviceNetworkModels?.policy?.state?.collectAsStateWithLifecycle()?.value?.access
    val catalogState=deviceNetworkModels?.catalog?.state?.collectAsStateWithLifecycle()?.value
    val catalogSummary=catalogState?.let { state->
        val saved=state.installed.filterIsInstance<pl.roseru.kalorie.catalogupdate.InstalledCatalog.Ready>()
        when {
            state.localReadFailed || state.installed.any{it is pl.roseru.kalorie.catalogupdate.InstalledCatalog.Unreadable}->"Opis zapisanej bazy jest niedostępny"
            !state.localReadComplete->"Odczytuję wersję zapisanej bazy…"
            saved.isEmpty()->"Nie pobrano jeszcze katalogu"
            else->"Baza: "+saved.joinToString(" · "){
                (if(it.manifest.packageId==pl.roseru.kalorie.core.catalog.MreCatalogueRules.PACKAGE_ID)"MRE 2026" else if(it.manifest.kind=="official")"oficjalna" else "DEMO")+" v${it.manifest.release}"}
        }
    }
    LaunchedEffect(model) {
        model.events.collect { event -> when (event) {
            DiaryEvent.MealSaved -> if (nav.currentDestination?.route in listOf("food", "rations", "custom", "community")) nav.popBackStack("diary", false)
            is DiaryEvent.Message -> snackbar.showSnackbar(event.text)
        } }
    }
    if (!ready) {
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                if (error == null) { CircularProgressIndicator(); Text("Otwieram lokalny dziennik", Modifier.padding(top = 20.dp)) }
                else { Text(error!!); Button(onClick = model::initialize, modifier = Modifier.padding(top = 20.dp)) { Text("Spróbuj ponownie") } }
            }
        }
        return
    }
    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            if(networkState!=null && route in listOf("photo","account","import","achievements","ranking-consent","ranking","nemesis","community"))
                NetworkModeNotice(networkState,onSettings={nav.navigate("settings"){launchSingleTop=true}})
        },
        bottomBar = {
            if (route !in listOf("food", "rations", "custom", "photo", "community", "maintenance", "energy")) NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
                NavigationBarItem(selected = route == "diary", onClick = { nav.navigate("diary") { popUpTo("diary"); launchSingleTop = true } },
                    icon = { Icon(Icons.AutoMirrored.Outlined.Assignment, contentDescription = null) }, label = { Text("Dziennik") }, modifier=Modifier.testTag("open-diary"))
                NavigationBarItem(selected = route == "analytics", onClick = { nav.navigate("analytics") { launchSingleTop = true } },
                    icon = { Icon(Icons.Outlined.BarChart, contentDescription = null) }, label = { Text("Postępy") }, modifier = Modifier.testTag("open-analytics"))
                NavigationBarItem(selected = route == "settings", onClick = { nav.navigate("settings") { launchSingleTop = true } },
                    icon = { Icon(Icons.Outlined.Tune, contentDescription = null) }, label = { Text("Ustawienia") }, modifier=Modifier.testTag("open-settings"))
                NavigationBarItem(selected = route in listOf("profile", "achievements", "ranking-consent", "ranking", "nemesis"), onClick = { nav.navigate("profile") { launchSingleTop = true } },
                    icon = { Icon(Icons.Outlined.PersonOutline, contentDescription = null) }, label = { Text("Profil") }, modifier = Modifier.testTag("open-profile"))
            }
        }
    ) { padding ->
        NavHost(nav, startDestination = "diary", modifier = Modifier.padding(padding).consumeWindowInsets(padding)) {
            composable("diary") { DiaryScreen(model, onAdd = { nav.navigate("food") }, onSettings = { nav.navigate("settings") { launchSingleTop = true } },
                networkState=networkState,catalogSummary=catalogSummary,lastServerCopy=session.snapshot?.completedTime,refusedChanges=session.mealPush?.refused) }
            composable("food") { FoodScreen(model, onBack = { nav.popBackStack() }, onRations = { nav.navigate("rations") }, onCustom = { nav.navigate("custom") }, onPhoto = { nav.navigate("photo") },
                onCommunity=communityModel?.let {{nav.navigate("community")}}) }
            composable("community") {
                communityModel?.let {CommunityScreen(it,model,session,networkState,onBack={nav.popBackStack()},
                    onAccount={nav.navigate("account")},onCustom={nav.navigate("custom")})}
            }
            composable("rations") { RationScreen(model, onBack = { nav.popBackStack() }) }
            composable("photo") {
                val day by model.day.collectAsStateWithLifecycle()
                MealPhotoScreen(photoModel, day.date, onBack = { nav.popBackStack() }, onManual = { nav.navigate("custom") },
                    session = session, onReadCapabilities = actions.readPhotoCapabilities,
                    onUpload = actions.uploadPhoto,onRetryUpload = actions.retryPhotoUpload,
                    onDiscardUpload = actions.discardUnsentPhotoUpload,onReadAnalysis=actions.readPhotoAnalysis,
                    onRestoreAnalysis=actions.restorePhotoAnalysis,onStopAnalysis=actions.stopPhotoAnalysis,onClearAnalysis=actions.clearPhotoAnalysis,
                    onCancelAnalysis=actions.cancelPhotoAnalysis,onRetryCancellation=actions.retryPhotoCancellation,onReleaseCancelled=actions.releaseCancelledPhoto,draftActions=actions.photoDraft)
            }
            composable("custom") { CustomFoodScreen(model, onBack = { nav.popBackStack() }) }
            composable("settings") { SettingsScreen(model,deviceNetworkModels?.catalog,deviceNetworkModels?.policy,
                onCalculator={nav.navigate("maintenance"){launchSingleTop=true}},onEnergy=energyModel?.let {{nav.navigate("energy"){launchSingleTop=true}}},
                snapshotMaintenanceModel=snapshotMaintenanceModel,onAccount={nav.navigate("account"){launchSingleTop=true}}) }
            composable("maintenance") {MaintenanceScreen(model,onBack={nav.popBackStack()})}
            composable("energy") {energyModel?.let {EnergyScreen(it,model,session,networkState,onBack={nav.popBackStack()},onAccount={nav.navigate("account"){launchSingleTop=true}},
                onConsents={nav.navigate("ranking-consent"){launchSingleTop=true}})}}
            composable("profile") { ProfileScreen(model, onAccount = { nav.navigate("account") { launchSingleTop = true } },
                onAchievements = { nav.navigate("achievements") { launchSingleTop = true } },
                onNemesis = { nav.navigate("nemesis") { launchSingleTop = true } }) }
            composable("achievements") { AchievementsScreen(model, session, actions,
                onAccount = { nav.navigate("account") { launchSingleTop = true } }, onBack = { nav.popBackStack() },
                onRanking = { nav.navigate("ranking-consent") { launchSingleTop = true } }) }
            composable("ranking-consent") { RankingConsentScreen(session, actions, onBack = { nav.popBackStack() },
                onAccount = { nav.navigate("account") { launchSingleTop = true } }, onRanking = { nav.navigate("ranking") { launchSingleTop = true } }) }
            composable("ranking") { RankingScreen(session, actions, onBack = { nav.popBackStack() },
                onAccount = { nav.navigate("account") { launchSingleTop = true } }, onConsent = { nav.navigate("ranking-consent") { launchSingleTop = true } }) }
            composable("account") { SessionScreen(session, actions, back = { nav.popBackStack() },
                onImport=importModel?.let { {nav.navigate("import") {launchSingleTop=true}} },syncStatus=syncStatus,
                onSyncOverview=syncOverviewModel?.let {{nav.navigate("sync-overview"){launchSingleTop=true}}},
                backLabel = when (nav.previousBackStackEntry?.destination?.route) {
                    "achievements" -> "Wróć do osiągnięć"; "ranking-consent" -> "Wróć do zgód rankingu"; "ranking" -> "Wróć do rankingu"; "nemesis" -> "Wróć do Nemesis"; else -> "Wróć do profilu"
                }) }
            composable("sync-overview") {
                syncOverviewModel?.let {AccountSyncOverviewScreen(it,session,actions,networkState,snapshotMaintenanceModel,
                    onBack={nav.popBackStack()},onAccount={nav.navigate("account"){launchSingleTop=true}},
                    onSettings={nav.navigate("settings"){launchSingleTop=true}},
                    onImport=importModel?.let {{nav.navigate("import"){launchSingleTop=true}}})}
            }
            composable("import") {
                if(importModel!=null) {
                    LaunchedEffect(importModel,syncStatus) {importModel.refresh()}
                    ImportScreen(importModel,back={nav.popBackStack()},sendOrdinary={session.binding?.lease?.let(actions.synchronizeMeals)},ordinaryConfigured=session.mealPushConfigured,syncStatus=syncStatus)
                } else TextButton(onClick={nav.popBackStack()}) {Text("Wróć do konta")}
            }
            composable("nemesis") { NemesisScreen(session, actions, onBack = { nav.popBackStack() },
                onAccount = { nav.navigate("account") { launchSingleTop = true } }) }
            composable("analytics") { AnalyticsScreen(model, onDay = { date ->
                model.selectDate(date)
                nav.navigate("diary") { popUpTo("diary"); launchSingleTop = true }
            }) }
        }
    }
    if (route in listOf("photo", "settings", "maintenance", "profile", "analytics", "account", "import", "achievements", "ranking-consent", "ranking", "nemesis")) BackHandler { nav.popBackStack() }
}
