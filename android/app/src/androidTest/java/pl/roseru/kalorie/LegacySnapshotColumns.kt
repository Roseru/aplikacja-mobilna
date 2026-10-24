package pl.roseru.kalorie

import android.database.Cursor
import org.junit.Assert.assertTrue

/** Historical migration fixtures had no estimate column. Assert its new NULL, then compare every old field. */
internal fun legacySnapshotColumns(cursor: Cursor): List<Int> {
    val added=cursor.getColumnIndex("estimateJson")
    if(added>=0)assertTrue("An old fixture must not acquire a fabricated estimate",cursor.isNull(added))
    return (0 until cursor.columnCount).filter {it!=added}
}
