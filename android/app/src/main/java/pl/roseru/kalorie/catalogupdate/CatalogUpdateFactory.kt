package pl.roseru.kalorie.catalogupdate

import android.content.Context
import org.json.JSONObject
import pl.roseru.kalorie.R
import pl.roseru.kalorie.core.catalog.CatalogSchema
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.data.CalorieDatabase
import java.io.File

object CatalogUpdateFactory {
    /** Explicit dependencies prevent a catalogue transport from bypassing the application policy. */
    fun repository(context:Context,database:CalorieDatabase,gate:NetworkAccessGate,connections:PolicyConnectionFactory):CatalogUpdateRepository {
        val app=context.applicationContext
        fun schema(file:String)=app.assets.open("catalog/e2/$file").bufferedReader(Charsets.UTF_8).use{JSONObject(it.readText())}
        val endpoint=app.getString(R.string.api_base_url)
        val gateway=endpoint.takeIf{it.isNotEmpty()}?.let {
            try {HttpsCatalogDownloadGateway(it,gate,connections::open)}catch(_:Exception){null}
        }
        return CatalogUpdateRepository(database,{CatalogSchema(schema("common.schema.json"),schema("catalog.schema.json"))},gateway,gate,
            File(app.cacheDir,"catalog-downloads"),PreferencesCatalogRetryStore(app))
    }
}
