package pl.roseru.kalorie.session

/** Compiled into debug/release instead of the validation implementation. */
internal object ApiReadObservation {
    const val ENABLED = false
    @Suppress("UNUSED_PARAMETER")
    fun record(method: String, path: String, status: Int, cacheControl: String?, requestId: String?) = Unit
}
