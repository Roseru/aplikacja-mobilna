package pl.roseru.kalorie

import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import java.math.BigDecimal
import java.time.Instant

class MaintenanceEstimateTest {
    private val stamp=Instant.parse("2026-10-24T12:00:00.123456Z")
    private fun estimate(variant:EquationVariant=EquationVariant.PLUS_5,activity:ActivityClass=ActivityClass.GARRISON)=
        MaintenanceEstimate.calculate(MaintenanceInput(30,BigDecimal("180"),BigDecimal("80"),variant,activity),stamp)

    @Test fun bothEquationVariantsAndAllThreePalClassesMatchFixedContractExamples() {
        val expected=listOf("2670","3204","3916","2421","2905.2","3550.8")
        val results=EquationVariant.entries.flatMap {variant->ActivityClass.entries.map {activity->
            MaintenanceEstimate.canonical(estimate(variant,activity).maintenance)
        }}
        assertEquals(expected,results)
        assertEquals("1780",MaintenanceEstimate.canonical(estimate().resting))
        assertEquals("1614",MaintenanceEstimate.canonical(estimate(EquationVariant.MINUS_161).resting))
    }
    @Test fun sixPlaceInputsKeepExactComputedPrecisionAndOnlyTheDisplayedGoalIsRounded() {
        val value=MaintenanceEstimate.calculate(MaintenanceInput(18,BigDecimal("180.000001"),BigDecimal("80.000001"),
            EquationVariant.PLUS_5,ActivityClass.GARRISON),stamp)
        assertEquals("2760.000024375",MaintenanceEstimate.canonical(value.maintenance))
        assertEquals("2760",value.suggestedGoal.toPlainString())
        assertEquals("2760.000024375",value.json().getString("maintenance_kcal"))
        assertEquals(BigDecimal("180.125"),MaintenanceEstimate.inputDecimal("180,125"))
        for(text in listOf("NaN","Infinity","1e2","-80","180.1234567"))assertNull(MaintenanceEstimate.inputDecimal(text))
    }
    @Test fun wireAuditIsSelfConsistentAndRejectsChangedFormulaInputsAndUnknownFields() {
        val value=estimate();assertEquals(value,MaintenanceEstimate.read(value.stored()))
        assertEquals(stamp,value.estimatedAt)
        for(key in listOf("resting_kcal","maintenance_kcal","pal")) {
            val forged=value.json().put(key,"123")
            assertThrows(IllegalArgumentException::class.java){MaintenanceEstimate.read(forged.toString())}
        }
        assertThrows(IllegalArgumentException::class.java){MaintenanceEstimate.read(value.json().put("extra",true).toString())}
        assertThrows(IllegalArgumentException::class.java){MaintenanceEstimate.read(value.json().put("estimated_at","2026-10-24T12:00:00+00:00").toString())}
        assertEquals("MaintenanceEstimate(redacted)",value.toString())
    }
    @Test fun outsideV1AndNonPositiveRestingValuesCannotBeSavedAsAnEstimate() {
        for(age in listOf(0,17,121))assertThrows(IllegalArgumentException::class.java){
            MaintenanceInput(age,BigDecimal("180"),BigDecimal("80"),EquationVariant.PLUS_5,ActivityClass.LINE)
        }
        assertThrows(IllegalArgumentException::class.java){MaintenanceInput(30,BigDecimal("300.000001"),BigDecimal("80"),EquationVariant.PLUS_5,ActivityClass.LINE)}
        assertThrows(IllegalArgumentException::class.java){MaintenanceInput(30,BigDecimal("180"),BigDecimal.ZERO,EquationVariant.PLUS_5,ActivityClass.LINE)}
        assertThrows(IllegalArgumentException::class.java){MaintenanceEstimate.calculate(MaintenanceInput(120,BigDecimal.ONE,BigDecimal.ONE,EquationVariant.MINUS_161,ActivityClass.LINE),stamp)}
    }
}
