package pl.roseru.kalorie.catalogupdate

import android.content.Context

/** Public endpoint backoff survives process death; contains no account identifiers. */
internal interface CatalogRetryStore {
    fun deadline():Long
    fun deferUntil(epochMillis:Long)
}
internal class PreferencesCatalogRetryStore(context:Context):CatalogRetryStore {
    companion object {private val writer=Any()}
    private val preferences=context.applicationContext.getSharedPreferences("catalog-download-backoff",Context.MODE_PRIVATE)
    override fun deadline():Long=preferences.getLong("retry-at",0).coerceAtLeast(0)
    override fun deferUntil(epochMillis:Long):Unit=synchronized(writer) {
        require(epochMillis>=0)
        check(preferences.edit().putLong("retry-at",maxOf(deadline(),epochMillis)).commit())
    }
}
