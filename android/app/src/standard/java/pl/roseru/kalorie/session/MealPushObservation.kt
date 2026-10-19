package pl.roseru.kalorie.session

/** Regular debug/release never arms or waits for the validation barrier. */
internal object MealPushObservation {
    const val ENABLED = false
    @Suppress("UNUSED_PARAMETER")
    suspend fun beforeApplyAck(batchId: String, requestHash: String) = Unit
}
