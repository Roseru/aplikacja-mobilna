package pl.roseru.kalorie.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.map

private val Context.settings by preferencesDataStore("settings")
enum class ThemeMode(val label: String) { SYSTEM("Zgodny z systemem"), LIGHT("Jasny"), DARK("Ciemny") }
class Preferences(private val context: Context) {
    private val themeKey = stringPreferencesKey("theme")
    val theme = context.settings.data.map { settings -> ThemeMode.entries.firstOrNull { it.name == settings[themeKey] } ?: ThemeMode.SYSTEM }
    suspend fun setTheme(mode: ThemeMode) { context.settings.edit { it[themeKey] = mode.name } }
}
