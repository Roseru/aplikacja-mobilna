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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.compose.*
import pl.roseru.kalorie.DiaryEvent
import pl.roseru.kalorie.DiaryViewModel

@Composable fun CalorieApp(model: DiaryViewModel) {
    val ready by model.ready.collectAsStateWithLifecycle()
    val error by model.startupError.collectAsStateWithLifecycle()
    val nav = rememberNavController()
    val snackbar = remember { SnackbarHostState() }
    val backStack by nav.currentBackStackEntryAsState()
    val route = backStack?.destination?.route
    LaunchedEffect(model) {
        model.events.collect { event -> when (event) {
            DiaryEvent.MealSaved -> if (nav.currentDestination?.route in listOf("food", "rations")) nav.popBackStack("diary", false)
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
        bottomBar = {
            if (route !in listOf("food", "rations")) NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
                NavigationBarItem(selected = route == "diary", onClick = { nav.navigate("diary") { popUpTo("diary"); launchSingleTop = true } },
                    icon = { Icon(Icons.AutoMirrored.Outlined.Assignment, contentDescription = null) }, label = { Text("Dziennik") })
                NavigationBarItem(selected = route == "settings", onClick = { nav.navigate("settings") { launchSingleTop = true } },
                    icon = { Icon(Icons.Outlined.Tune, contentDescription = null) }, label = { Text("Ustawienia") })
            }
        }
    ) { padding ->
        NavHost(nav, startDestination = "diary", modifier = Modifier.padding(padding).consumeWindowInsets(padding)) {
            composable("diary") { DiaryScreen(model, onAdd = { nav.navigate("food") }, onSettings = { nav.navigate("settings") { launchSingleTop = true } }) }
            composable("food") { FoodScreen(model, onBack = { nav.popBackStack() }, onRations = { nav.navigate("rations") }) }
            composable("rations") { RationScreen(model, onBack = { nav.popBackStack() }) }
            composable("settings") { SettingsScreen(model) }
        }
    }
    if (route == "settings") BackHandler { nav.popBackStack() }
}
