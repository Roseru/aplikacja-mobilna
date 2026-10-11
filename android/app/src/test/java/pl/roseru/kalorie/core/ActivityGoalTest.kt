package pl.roseru.kalorie.core

import org.junit.Assert.*
import org.junit.Test

class ActivityGoalTest {
    @Test fun modesScaleCurrentGoalAndCanReturnToOffice() {
        val line = activityCalorieGoal(2800.0, ActivityClass.GARRISON, ActivityClass.LINE)
        val commando = activityCalorieGoal(line, ActivityClass.LINE, ActivityClass.COMMANDO)
        assertEquals(3500.0, line, 0.0)
        assertEquals(4200.0, commando, 0.0)
        assertEquals(2800.0, activityCalorieGoal(commando, ActivityClass.COMMANDO, ActivityClass.GARRISON), 0.0)
        assertEquals(3600.0, activityCalorieGoal(3000.0, ActivityClass.LINE, ActivityClass.COMMANDO), 0.0)
        assertEquals(2800.25, activityCalorieGoal(2800.25, ActivityClass.LINE, ActivityClass.LINE), 0.0)
        assertEquals(2501.0, activityCalorieGoal(2000.4, ActivityClass.GARRISON, ActivityClass.LINE), 0.0)
    }

    @Test fun invalidAndOverflowTargetsAreRejected() {
        for (value in listOf(0.0, -1.0, Double.NaN, Double.POSITIVE_INFINITY, 20_001.0, 20_000.0)) {
            try { activityCalorieGoal(value, ActivityClass.GARRISON, ActivityClass.COMMANDO); fail("Accepted $value") }
            catch (_: IllegalArgumentException) { }
        }
    }
}
