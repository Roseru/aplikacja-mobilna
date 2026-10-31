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
    @Test fun initialProfileDefaultsDoNotDecideAGoalButActivityAndAimChangesDo() {
        assertNull(profileGoalCalories(2200.0,null,null,ActivityClass.GARRISON,DietAim.MAINTAIN))
        assertNull(profileGoalCalories(2200.25,ActivityClass.GARRISON,DietAim.MAINTAIN,ActivityClass.GARRISON,DietAim.MAINTAIN))
        assertEquals(2750.0,profileGoalCalories(2200.0,null,null,ActivityClass.LINE,DietAim.MAINTAIN)!!,0.0)
        assertEquals(2200.0,profileGoalCalories(2200.0,null,null,ActivityClass.GARRISON,DietAim.REDUCE)!!,0.0)
        assertEquals(2200.0,profileGoalCalories(2200.0,ActivityClass.LINE,DietAim.MAINTAIN,ActivityClass.LINE,DietAim.REDUCE)!!,0.0)
        assertNull(profileGoalCalories(2200.0,ActivityClass.LINE,DietAim.REDUCE,ActivityClass.LINE,DietAim.REDUCE))
        assertEquals(2640.0,profileGoalCalories(2200.0,ActivityClass.LINE,DietAim.REDUCE,ActivityClass.COMMANDO,DietAim.REDUCE)!!,0.0)
    }
}
