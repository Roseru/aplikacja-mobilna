package pl.roseru.kalorie.core

import java.math.BigDecimal

fun completeDiary(declared: Boolean, itemCount: Int, total: Nutrients): Boolean =
    declared && itemCount > 0 && total.asExact().energy.let { it.complete && it.knownSum > BigDecimal.ZERO }
