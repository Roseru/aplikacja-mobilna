package pl.roseru.kalorie.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.core.ActivityClass

/** Decorative silhouettes; the adjacent text names each activity. */
@Composable internal fun SoldierIcon(activity: ActivityClass) {
    val uniform = MaterialTheme.colorScheme.primary
    val detail = MaterialTheme.colorScheme.onSurface
    val face = Color(0xFFE0B78E)
    Canvas(Modifier.size(40.dp)) {
        scale(size.width / 48f, size.height / 48f, pivot = Offset.Zero) {
            fun line(x1: Float, y1: Float, x2: Float, y2: Float, color: Color = uniform, width: Float = 4f) =
                drawLine(color, Offset(x1, y1), Offset(x2, y2), width)
            val headX = if (activity == ActivityClass.GARRISON) 18f else 24f
            drawCircle(face, 5f, Offset(headX, 11f))
            drawArc(uniform, 180f, 180f, true, Offset(headX - 6f, 3f), Size(12f, 11f))
            line(headX - 6f, 8f, headX + 7f, 8f, uniform, 2f)
            when (activity) {
                ActivityClass.GARRISON -> {
                    line(17f, 18f, 17f, 29f, width = 9f)
                    line(19f, 20f, 28f, 24f)
                    line(17f, 29f, 27f, 31f)
                    line(27f, 31f, 28f, 42f)
                    line(28f, 42f, 34f, 42f, detail, 3f)
                    line(8f, 18f, 8f, 33f, detail, 2f)
                    line(8f, 33f, 24f, 33f, detail, 2f)
                    line(10f, 33f, 10f, 43f, detail, 2f)
                    line(29f, 29f, 43f, 29f, detail, 2f)
                    line(40f, 29f, 40f, 43f, detail, 2f)
                    drawRect(face, Offset(31f, 20f), Size(6f, 7f))
                    drawCircle(face, 2f, Offset(38f, 23f), style = Stroke(1.5f))
                    line(33f, 17f, 34f, 14f, detail, 1f)
                }
                ActivityClass.LINE -> {
                    drawRoundRect(detail, Offset(13f, 17f), Size(8f, 15f), androidx.compose.ui.geometry.CornerRadius(3f))
                    line(25f, 18f, 24f, 29f, width = 10f)
                    line(25f, 20f, 33f, 26f)
                    line(33f, 26f, 38f, 22f, face, 3f)
                    line(23f, 30f, 16f, 41f)
                    line(26f, 30f, 33f, 37f)
                    line(33f, 37f, 30f, 43f)
                    line(13f, 43f, 18f, 43f, detail, 3f)
                    line(28f, 44f, 34f, 44f, detail, 3f)
                }
                ActivityClass.COMMANDO -> {
                    drawRect(detail, Offset(18f, 9f), Size(12f, 3f))
                    line(24f, 18f, 24f, 29f, width = 12f)
                    drawRect(detail, Offset(20f, 19f), Size(8f, 9f))
                    line(19f, 20f, 14f, 27f)
                    line(29f, 20f, 33f, 28f)
                    line(14f, 27f, 34f, 27f, detail, 3f)
                    line(34f, 27f, 41f, 25f, detail, 2f)
                    line(21f, 30f, 18f, 42f)
                    line(27f, 30f, 31f, 42f)
                    line(15f, 44f, 21f, 44f, detail, 3f)
                    line(29f, 44f, 35f, 44f, detail, 3f)
                }
            }
        }
    }
}
