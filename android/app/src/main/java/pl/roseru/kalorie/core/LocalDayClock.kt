package pl.roseru.kalorie.core

import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flow
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/** Calendar days follow the current device zone, including daylight-saving changes. */
class LocalDayClock(private val now: () -> Instant = { Instant.now() },
    private val zone: () -> ZoneId = { ZoneId.systemDefault() },
    private val pause: suspend (Long) -> Unit = { delay(it) }) {
    fun today(): LocalDate = now().atZone(zone()).toLocalDate()
    fun untilNextDayMillis(): Long {
        val current = now().atZone(zone())
        return Duration.between(current.toInstant(), current.toLocalDate().plusDays(1).atStartOfDay(current.zone).toInstant())
            .toMillis().coerceAtLeast(1)
    }
    fun dates() = flow {
        while (true) {
            emit(today())
            // Also notice manual clock/zone changes without waiting for the old midnight.
            pause(untilNextDayMillis().coerceAtMost(60_000))
        }
    }.distinctUntilChanged()
}
