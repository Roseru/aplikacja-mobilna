package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import pl.roseru.kalorie.core.Nutrients
import pl.roseru.kalorie.core.decimal
import pl.roseru.kalorie.data.GoalEntity
import kotlin.math.roundToInt

@Composable fun NutritionCard(total: Nutrients, goal: GoalEntity?) {
    val limit = goal?.kcal ?: 2800.0
    val percent = (total.kcal / limit * 100).roundToInt()
    Card(shape = RoundedCornerShape(22.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Dzienne spożycie", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
                    Text(total.kcal.roundToInt().toString(), modifier = Modifier.testTag("daily-kcal"), fontSize = 40.sp, fontWeight = FontWeight.Bold)
                    Text("kcal z ${limit.roundToInt()}", style = MaterialTheme.typography.bodyLarge)
                    Text(if (total.kcal <= limit) "Pozostało ${(limit - total.kcal).roundToInt()} kcal" else "Ponad cel ${(total.kcal - limit).roundToInt()} kcal",
                        modifier = Modifier.padding(top = 8.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Box(Modifier.size(102.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(progress = { (total.kcal / limit).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxSize(), strokeWidth = 8.dp,
                        trackColor = MaterialTheme.colorScheme.surfaceVariant)
                    Text("$percent%", fontSize = 23.sp, fontWeight = FontWeight.SemiBold)
                }
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = .2f))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Macro("Białko", total.protein, goal?.protein, MaterialTheme.colorScheme.primary, Modifier.weight(1f))
                Macro("Tłuszcze", total.fat, goal?.fat, Color(0xFFD0A83D), Modifier.weight(1f))
                Macro("Węglowodany", total.carbs, goal?.carbs, Color(0xFF76A5CD), Modifier.weight(1f))
            }
        }
    }
}

@Composable private fun Macro(label: String, amount: Double?, goal: Double?, color: Color, modifier: Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(label, fontSize = 12.sp, fontWeight = FontWeight.Medium)
        LinearProgressIndicator(progress = { if (amount != null && goal != null && goal > 0) (amount / goal).toFloat().coerceIn(0f, 1f) else 0f },
            color = color, trackColor = MaterialTheme.colorScheme.surfaceVariant, modifier = Modifier.fillMaxWidth())
        Text(if (amount == null) "Brak danych" else "${decimal(amount)}${goal?.let { " / ${decimal(it)}" } ?: ""} g", fontSize = 12.sp)
    }
}

@Composable fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, modifier, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
}
