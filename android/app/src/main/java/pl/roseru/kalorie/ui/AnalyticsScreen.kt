package pl.roseru.kalorie.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.outlined.KeyboardArrowRight
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.core.*
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

private val shortDate = DateTimeFormatter.ofPattern("d.MM", Locale.forLanguageTag("pl-PL"))
private val fullDate = DateTimeFormatter.ofPattern("d.MM.yyyy", Locale.forLanguageTag("pl-PL"))
private val metricLabels = listOf("Kalorie", "Białko", "Tłuszcze", "Węglowodany")
private val metricChips = listOf("kcal", "B", "T", "W")
private fun BigDecimal.display(scale: Int = 1): String = setScale(scale, RoundingMode.HALF_UP).toPlainString().replace('.', ',')
private fun FieldAggregate.label(unit: String) = (if (complete) "" else "≥ ") + display.replace('.', ',') + " $unit" +
    (if (complete) "" else " · brak danych: $missingCount")

@Composable fun AnalyticsScreen(model: DiaryViewModel, onDay: (LocalDate) -> Unit) {
    val window by model.analyticsWindow.collectAsStateWithLifecycle()
    val result by model.analytics.collectAsStateWithLifecycle()
    var metric by rememberSaveable { mutableIntStateOf(0) }
    val current = result?.takeIf { it.window == window }
    LazyColumn(Modifier.fillMaxSize().testTag("analytics-content"), contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item {
            Text("Postępy", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
            Text("Twoje spożycie, cele i pomiary wagi", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AnalyticsPeriod.entries.forEach { period ->
                    FilterChip(selected = window.period == period, onClick = { model.setAnalyticsPeriod(period) },
                        label = { Text("${period.days} dni") }, modifier = Modifier.weight(1f).testTag("period-${period.days}"))
                }
            }
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                IconButton(onClick = { model.moveAnalyticsWindow(-1) }, modifier = Modifier.testTag("analytics-previous")) {
                    Icon(Icons.AutoMirrored.Outlined.KeyboardArrowLeft, "Poprzedni okres")
                }
                Text("${window.start.format(fullDate)} – ${window.end.format(fullDate)}", style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.testTag("analytics-range"))
                IconButton(onClick = { model.moveAnalyticsWindow(1) }, enabled = window.end < LocalDate.now()) {
                    Icon(Icons.AutoMirrored.Outlined.KeyboardArrowRight, "Następny okres")
                }
            }
            if (window.end < LocalDate.now()) TextButton(onClick = model::analyticsToday) { Text("Do dzisiaj") }
        }
        item {
            Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(14.dp)) {
                Row(Modifier.padding(14.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Icon(Icons.Outlined.CloudOff, null)
                    Text("Dane z tego urządzenia · synchronizacja jeszcze nie jest podłączona.", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        if (current == null) {
            item { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) { CircularProgressIndicator() } }
        } else {
            item { PeriodSummary(current) }
            item { NutritionChartCard(current, metric, onMetric = { metric = it }) }
            item { WeightChartCard(current) }
            item {
                SectionTitle("Historia dni")
                Text("Dotknij dnia, aby otworzyć jego dziennik. Brak wpisów nie oznacza zerowego spożycia.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            items(current.days.asReversed(), key = { it.date.toString() }) { day -> HistoryDay(day, onDay) }
        }
    }
}

@Composable private fun PeriodSummary(result: AnalyticsResult) {
    Card(modifier = Modifier.testTag("analytics-loaded-${result.window.end}-${result.window.period.days}"),
        shape = RoundedCornerShape(20.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Podsumowanie okresu", style = MaterialTheme.typography.titleMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                SummaryValue("Kompletne dni", "${result.completeDays} / ${result.window.period.days}", Modifier.weight(1f).testTag("complete-days"))
                SummaryValue("Dni w celu", "${result.daysInGoal} / ${result.daysWithGoal}", Modifier.weight(1f).testTag("days-in-goal"))
            }
            val energy = result.averages[0]
            SummaryValue("Średnie spożycie", energy.value?.let { "${it.display(0)} kcal" } ?: "Brak kompletnych dni",
                Modifier.testTag("average-kcal"))
            Text("Średnia z ${energy.dayCount} kompletnych dni. Wpisy: ${result.daysWithEntries} / ${result.window.period.days} dni.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Dzień w celu: kompletny dziennik i ±10% celu obowiązującego tego dnia. Bez celu nie oceniamy wyniku.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
@Composable private fun SummaryValue(label: String, value: String, modifier: Modifier = Modifier) {
    Column(modifier) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
    }
}

@Composable private fun NutritionChartCard(result: AnalyticsResult, metric: Int, onMetric: (Int) -> Unit) {
    val unit = if (metric == 0) "kcal" else "g"
    val primary = MaterialTheme.colorScheme.primary
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    val outline = MaterialTheme.colorScheme.outline
    val average = result.averages[metric]
    val maximum = result.days.maxOfOrNull { maxOf(it.total?.asExact()?.fields()?.get(metric)?.knownSum?.toDouble() ?: 0.0,
        if (metric == 0) it.goal?.toDouble() ?: 0.0 else 0.0) }?.takeIf { it > 0 } ?: 1.0
    Card(shape = RoundedCornerShape(20.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            SectionTitle("${metricLabels[metric]} w kolejnych dniach")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                metricChips.forEachIndexed { index, label -> FilterChip(selected = metric == index, onClick = { onMetric(index) },
                    label = { Text(label) }, modifier = Modifier.testTag("metric-$index")) }
            }
            Text("Średnia: ${average.value?.let { it.display(if (metric == 0) 0 else 1) + " $unit" } ?: "brak danych"} · ${average.dayCount} dni",
                style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("metric-average"))
            Text("Skala: 0 – ${BigDecimal.valueOf(maximum).display(if (metric == 0) 0 else 1)} $unit", style = MaterialTheme.typography.labelSmall)
            Canvas(Modifier.fillMaxWidth().height(140.dp).testTag("nutrition-chart").semantics {
                contentDescription = "Wykres: ${metricLabels[metric]}. Szczegółowe wartości i braki w historii dni poniżej."
            }) {
                val bottom = size.height - 5.dp.toPx()
                val step = size.width / result.days.size
                val barWidth = (step * .6f).coerceAtLeast(1f)
                drawLine(outline, Offset(0f, bottom), Offset(size.width, bottom), 1.dp.toPx())
                result.days.forEachIndexed { index, day ->
                    val x = step * (index + .5f)
                    val field = day.total?.asExact()?.fields()?.get(metric)
                    if (field == null) {
                        drawCircle(muted, 1.5.dp.toPx(), Offset(x, bottom))
                    } else {
                        val height = (field.knownSum.toDouble() / maximum * (bottom - 4.dp.toPx())).toFloat()
                        if (height <= .5f) {
                            drawLine(if (field.complete && day.status == AnalyticsDayStatus.COMPLETE) primary else muted,
                                Offset(x - barWidth / 2, bottom - 2.dp.toPx()), Offset(x + barWidth / 2, bottom - 2.dp.toPx()), 2.dp.toPx())
                        } else {
                            val position = Offset(x - barWidth / 2, bottom - height)
                            val dimensions = Size(barWidth, height)
                            if (field.complete && day.status == AnalyticsDayStatus.COMPLETE) drawRect(primary, position, dimensions)
                            else drawRect(muted, position, dimensions, style = Stroke(width = 1.dp.toPx()))
                        }
                    }
                    if (metric == 0 && day.goal != null) {
                        val y = bottom - (day.goal.toDouble() / maximum * (bottom - 4.dp.toPx())).toFloat()
                        drawLine(outline, Offset(index * step, y), Offset((index + 1) * step, y), 1.dp.toPx(),
                            pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx())))
                    }
                }
            }
            ChartDates(result.window)
            Text("Pełny słupek: kompletny dzień. Obrys: wpisy niepełne. Kropka: brak wpisów." +
                if (metric == 0) " Kreskowana linia: cel dnia." else "",
                style = MaterialTheme.typography.bodySmall, color = muted)
            Text("Średnia obejmuje wyłącznie kompletne dni ze znaną wartością wybranego składnika.",
                style = MaterialTheme.typography.bodySmall, color = muted)
        }
    }
}

@Composable private fun WeightChartCard(result: AnalyticsResult) {
    val points = result.days.mapIndexedNotNull { index, day -> day.weight?.let { index to it } }
    val primary = MaterialTheme.colorScheme.primary
    val outline = MaterialTheme.colorScheme.outline
    val low = points.minOfOrNull { it.second.kg.toDouble() } ?: 0.0
    val high = points.maxOfOrNull { it.second.kg.toDouble() } ?: 1.0
    val padding = maxOf(.5, (high - low) * .1)
    Card(shape = RoundedCornerShape(20.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            SectionTitle("Masa ciała")
            Text("${result.weightCount} pomiarów · ${points.size} dni z pomiarem", modifier = Modifier.testTag("weight-count"))
            val change = result.weightChange
            Text(if (change == null) "Do zmiany masy potrzeba pomiarów z dwóch dni." else
                "Zmiana: ${if (change > BigDecimal.ZERO) "+" else ""}${change.display()} kg · ${points.first().second.date.format(shortDate)} – ${points.last().second.date.format(shortDate)}",
                modifier = Modifier.testTag("weight-change"), style = MaterialTheme.typography.bodyMedium)
            if (points.isEmpty()) Text("Brak pomiarów w wybranym okresie.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            else {
                Text("Skala: ${BigDecimal.valueOf(low - padding).display()} – ${BigDecimal.valueOf(high + padding).display()} kg",
                    style = MaterialTheme.typography.labelSmall)
                Canvas(Modifier.fillMaxWidth().height(120.dp).testTag("weight-chart").semantics {
                    contentDescription = "Wykres rzeczywistych pomiarów wagi: ${points.size} dni. Bez uzupełniania brakujących pomiarów."
                }) {
                    val bottom = size.height - 6.dp.toPx()
                    drawLine(outline, Offset(0f, bottom), Offset(size.width, bottom), 1.dp.toPx())
                    points.forEach { (index, point) ->
                        val x = size.width * (index + .5f) / result.days.size
                        val y = bottom - ((point.kg.toDouble() - low + padding) / (high - low + 2 * padding) * (bottom - 6.dp.toPx())).toFloat()
                        drawCircle(primary, 4.dp.toPx(), Offset(x, y))
                    }
                }
                ChartDates(result.window)
            }
            Text("Pokazujemy ostatni rzeczywisty pomiar każdego dnia. Zmiana dotyczy pierwszego i ostatniego z tych dni; nie uzupełniamy przerw.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
@Composable private fun ChartDates(window: AnalyticsWindow) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(window.start.format(shortDate), style = MaterialTheme.typography.labelSmall)
        Text(window.end.format(shortDate), style = MaterialTheme.typography.labelSmall)
    }
}

@Composable private fun HistoryDay(day: AnalyticsDay, onDay: (LocalDate) -> Unit) {
    Card(Modifier.fillMaxWidth().testTag("history-${day.date}").clickable(onClickLabel = "Otwórz dziennik ${day.date.format(fullDate)}") { onDay(day.date) },
        shape = RoundedCornerShape(16.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(day.date.format(fullDate), fontWeight = FontWeight.SemiBold)
                Text(day.status.label, style = MaterialTheme.typography.labelMedium)
            }
            Text(day.total?.energyText()?.let { "$it kcal" } ?: "Brak danych o spożyciu")
            Text("Cel: ${day.goal?.let { it.display(0) + " kcal" } ?: "nie ustawiono"}" +
                when (day.inGoal) { true -> " · W celu"; false -> " · Poza celem"; null -> " · Bez oceny" },
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (day.total != null) {
                val fields = day.total.asExact().fields()
                Text("B: ${fields[1].label("g")}\nT: ${fields[2].label("g")}\nW: ${fields[3].label("g")}", style = MaterialTheme.typography.bodySmall)
                if (!fields[0].complete) Text("Brak kcal dla ${fields[0].missingCount} pozycji.", style = MaterialTheme.typography.bodySmall)
            }
            Text(day.weight?.let { "Waga: ${it.kg.display()} kg · pomiary: ${day.weightCount}" } ?: "Brak pomiaru wagi",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
