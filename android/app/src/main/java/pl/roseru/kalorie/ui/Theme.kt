package pl.roseru.kalorie.ui

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val DarkColors = darkColorScheme(
    primary = Color(0xFFBDDF72), onPrimary = Color(0xFF1C290D),
    primaryContainer = Color(0xFF34452B), onPrimaryContainer = Color(0xFFE0F4C2),
    secondary = Color(0xFFADC694), background = Color(0xFF111814), onBackground = Color(0xFFF0F3EC),
    secondaryContainer = Color(0xFF34452B), onSecondaryContainer = Color(0xFFE0F4C2),
    surface = Color(0xFF1B241E), onSurface = Color(0xFFF0F3EC),
    surfaceVariant = Color(0xFF28332B), onSurfaceVariant = Color(0xFFB9C3B7),
    surfaceContainer = Color(0xFF202A23), outline = Color(0xFF596657)
)
private val LightColors = lightColorScheme(
    primary = Color(0xFF577545), onPrimary = Color.White,
    primaryContainer = Color(0xFFE3ECD7), onPrimaryContainer = Color(0xFF243A30),
    secondary = Color(0xFF758C60), background = Color(0xFFF5F4ED), onBackground = Color(0xFF243A30),
    secondaryContainer = Color(0xFFE3ECD7), onSecondaryContainer = Color(0xFF243A30),
    surface = Color.White, onSurface = Color(0xFF243A30),
    surfaceVariant = Color(0xFFEBEEE4), onSurfaceVariant = Color(0xFF626B5E),
    surfaceContainer = Color(0xFFEEF0E8), outline = Color(0xFF89947F)
)

@Composable fun CalorieTheme(dark: Boolean, content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (dark) DarkColors else LightColors, content = content)
}
