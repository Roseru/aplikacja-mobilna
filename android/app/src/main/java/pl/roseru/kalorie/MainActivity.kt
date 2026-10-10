package pl.roseru.kalorie

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.*
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import pl.roseru.kalorie.data.ThemeMode
import pl.roseru.kalorie.ui.CalorieApp
import pl.roseru.kalorie.ui.CalorieTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val app = application as CalorieApplication
        setContent {
            val model: DiaryViewModel = viewModel(factory = viewModelFactory {
                initializer { DiaryViewModel(app.repository, app.preferences, createSavedStateHandle()) }
            })
            val mode by model.theme.collectAsStateWithLifecycle()
            val dark = when (mode) { ThemeMode.SYSTEM -> isSystemInDarkTheme(); ThemeMode.LIGHT -> false; ThemeMode.DARK -> true }
            SideEffect {
                val style = if (dark) SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
                    else SystemBarStyle.light(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT)
                enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
            }
            CalorieTheme(dark) { CalorieApp(model) }
        }
    }
}
