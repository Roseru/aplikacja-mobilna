package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.core.Nutrients
import pl.roseru.kalorie.data.GoalEntity

@Preview(name = "A — ciemny", widthDp = 390, showBackground = true)
@Composable private fun DarkPreview() = PreviewContent(true)

@Preview(name = "B — jasny", widthDp = 390, showBackground = true)
@Composable private fun LightPreview() = PreviewContent(false)

@Composable private fun PreviewContent(dark: Boolean) {
    CalorieTheme(dark) {
        Surface(color = MaterialTheme.colorScheme.background) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text("Dziennik", style = MaterialTheme.typography.headlineLarge)
                NutritionCard(Nutrients(2180.0, 140.0, 70.0, 248.0), GoalEntity("preview", "preview", "2026-10-09", 2800.0, 160.0, 90.0, 330.0))
            }
        }
    }
}
