package pl.roseru.kalorie.session

/** Regular debug/release never arms or waits for the validation barrier. */
internal object MealPushObservation {
    const val ENABLED = false
    @Suppress("UNUSED_PARAMETER")
    suspend fun beforeApplyAck(batchId: String, requestHash: String) = Unit
    @Suppress("UNUSED_PARAMETER")
    fun record(requestHash: String, method: String, path: String, status: Int, cacheControl: String?, requestId: String?) = Unit
}
