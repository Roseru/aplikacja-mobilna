package pl.roseru.kalorie.core.sync

/** Public protocol identity. Checkpoint/snapshot/page signatures bind this exact scope. */
enum class SyncProtocolScope(val installationId:String,val capability:String?) {
    LEGACY("calorie-app",null),
    ENERGY_V1("calorie-app:energy_estimates_v1","energy_estimates_v1");

    companion object {
        fun parse(value:String):SyncProtocolScope=entries.singleOrNull {it.installationId==value}
            ?:throw IllegalArgumentException("Unsupported synchronization scope")
    }
}
