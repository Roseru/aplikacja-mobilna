package pl.roseru.kalorie.photo

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import androidx.core.graphics.scale
import androidx.core.graphics.createBitmap
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.security.MessageDigest
import kotlin.math.roundToInt

internal class PreparedMealPhoto(private val encoded: ByteArray, val width: Int, val height: Int) {
    val sha256 = MessageDigest.getInstance("SHA-256").digest(encoded).joinToString("") { "%02x".format(it) }
    val size get() = encoded.size
    fun bytes() = encoded.copyOf()
    override fun toString() = "PreparedMealPhoto(redacted)"
}

/** Local preparation only; no provider, network, source URI or EXIF is retained. */
internal object MealPhotoPreparation {
    const val INPUT_BYTES = 20 * 1024 * 1024
    const val OUTPUT_BYTES = 5 * 1024 * 1024
    const val LONG_SIDE = 1600

    fun prepare(input: InputStream): PreparedMealPhoto {
        val raw = bounded(input, INPUT_BYTES)
        require(!animated(raw)) { "Animated image" }
        val bounds = BitmapFactory.Options().also { it.inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(raw, 0, raw.size, bounds)
        require(bounds.outWidth in 1..16000 && bounds.outHeight in 1..16000)
        require(bounds.outWidth.toLong() * bounds.outHeight <= 64_000_000)
        require(bounds.outMimeType in setOf("image/jpeg", "image/png", "image/webp", "image/heif", "image/heic", "image/avif"))
        val orientation = ExifInterface(ByteArrayInputStream(raw)).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= LONG_SIDE) sample *= 2
        val decoded = requireNotNull(BitmapFactory.decodeByteArray(raw, 0, raw.size,
            BitmapFactory.Options().also { it.inSampleSize = sample; it.inPreferredConfig = Bitmap.Config.ARGB_8888 }))
        var oriented: Bitmap? = null
        var scaled: Bitmap? = null
        var rgb: Bitmap? = null
        try {
            oriented = Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, orientationMatrix(orientation), true)
            val ratio = minOf(1.0, LONG_SIDE.toDouble() / maxOf(oriented.width, oriented.height))
            scaled = oriented.scale((oriented.width * ratio).roundToInt().coerceAtLeast(1),
                (oriented.height * ratio).roundToInt().coerceAtLeast(1), true)
            val flattened = createBitmap(scaled.width, scaled.height, Bitmap.Config.ARGB_8888)
            rgb = flattened
            Canvas(flattened).apply { drawColor(Color.WHITE); drawBitmap(scaled, 0f, 0f, null) }
            val encoded = ByteArrayOutputStream().also { check(flattened.compress(Bitmap.CompressFormat.JPEG, 90, it)) }.toByteArray()
            require(encoded.size in 1..OUTPUT_BYTES)
            return PreparedMealPhoto(encoded, flattened.width, flattened.height)
        } finally {
            listOfNotNull(decoded, oriented, scaled, rgb).distinct().forEach { it.recycle() }
        }
    }

    private fun orientationMatrix(value: Int) = Matrix().also { matrix ->
        val values = when (value) {
            2 -> floatArrayOf(-1f,0f,0f, 0f,1f,0f, 0f,0f,1f)
            3 -> floatArrayOf(-1f,0f,0f, 0f,-1f,0f, 0f,0f,1f)
            4 -> floatArrayOf(1f,0f,0f, 0f,-1f,0f, 0f,0f,1f)
            5 -> floatArrayOf(0f,1f,0f, 1f,0f,0f, 0f,0f,1f)
            6 -> floatArrayOf(0f,-1f,0f, 1f,0f,0f, 0f,0f,1f)
            7 -> floatArrayOf(0f,-1f,0f, -1f,0f,0f, 0f,0f,1f)
            8 -> floatArrayOf(0f,1f,0f, -1f,0f,0f, 0f,0f,1f)
            else -> floatArrayOf(1f,0f,0f, 0f,1f,0f, 0f,0f,1f)
        }
        matrix.setValues(values)
    }

    internal fun bounded(input: InputStream, maximum: Int): ByteArray {
        val output = ByteArrayOutputStream()
        val buffer = ByteArray(8192)
        while (true) {
            val read = input.read(buffer)
            if (read == -1) break
            require(read > 0 && output.size().toLong() + read <= maximum)
            output.write(buffer, 0, read)
        }
        return output.toByteArray()
    }

    private fun animated(bytes: ByteArray): Boolean {
        fun text(start: Int, count: Int) = String(bytes, start, count, Charsets.US_ASCII)
        if (bytes.size >= 12 && text(0,4) == "RIFF" && text(8,4) == "WEBP") {
            var offset = 12
            while (offset + 8 <= bytes.size) {
                if (text(offset,4) in setOf("ANIM", "ANMF")) return true
                val size = (0..3).sumOf { (bytes[offset+4+it].toLong() and 255) shl (it * 8) }
                val next = offset.toLong() + 8 + size + (size and 1)
                require(next <= bytes.size && next > offset)
                offset = next.toInt()
            }
        }
        if (bytes.size >= 8 && bytes.take(8) == listOf(137,80,78,71,13,10,26,10).map(Int::toByte)) {
            var offset = 8
            while (offset + 12 <= bytes.size) {
                if (text(offset+4,4) == "acTL") return true
                val size = (0..3).sumOf { (bytes[offset+it].toLong() and 255) shl ((3-it) * 8) }
                val next = offset.toLong() + 12 + size
                require(next <= bytes.size && next > offset)
                offset = next.toInt()
            }
        }
        return false
    }
}
