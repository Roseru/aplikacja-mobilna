package pl.roseru.kalorie.data

import android.content.Context
import pl.roseru.kalorie.core.catalog.*
import java.io.ByteArrayOutputStream

sealed interface MreCatalogueState {
    data object Loading : MreCatalogueState
    data class Ready(val rules: MreCatalogueRules) : MreCatalogueState
    data object Unavailable : MreCatalogueState
}

fun MreCatalogueState.selectionFor(rationJson: String?): MreRationSelection? {
    if (rationJson == null) return null
    val ration = StrictJson.read(rationJson.toByteArray(Charsets.UTF_8))
    if (ration.getString("source_id") != MreCatalogueRules.SOURCE_ID) return null
    return (this as? MreCatalogueState.Ready)?.rules?.forRation(rationJson) ?: throw MreCatalogueException()
}

internal class MreCatalogueAssets(private val context: Context) {
    data class Loaded(val catalog: ValidatedCatalog, val rules: MreCatalogueRules)

    fun read(schema: CatalogSchema): Loaded {
        val root = "catalog/mre2026/"
        val value = CatalogPackageReader(schema, MreCatalogueRules.PACKAGE_ID, "demo").read(
            context.assets.open(root + "manifest.json"), context.assets.open(root + "base-pl.1.json.gz.bin"))
        fun bounded(name: String): ByteArray = context.assets.open(root + name).use { input ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                require(read > 0 && output.size() + read <= 1024 * 1024)
                output.write(buffer, 0, read)
            }
            output.toByteArray()
        }
        return Loaded(value, MreCatalogueRules.read(value, bounded("selection-rules.json"), bounded("source.json")))
    }
}
