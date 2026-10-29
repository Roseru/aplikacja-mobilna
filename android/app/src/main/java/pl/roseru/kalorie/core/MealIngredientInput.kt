package pl.roseru.kalorie.core

import java.math.BigDecimal

/** Explicit manual values per 100 basis units, independent of the consumed quantity. */
data class MealIngredientInput(val name: String, val amount: String, val unit: QuantityUnit,
    val basisUnit: QuantityUnit, val nutrition: ExactNutrition, val density: ExactDensity? = null) {
    fun portion(): ExactPortion = ExactPortion(ContractDecimal.read(amount), unit, basisUnit, nutrition, density)
    fun validate() {
        require(name.isNotBlank() && name.codePointCount(0,name.length) <= 200 && name.none { it.isISOControl() })
        var index=0
        while(index<name.length) {
            val char=name[index++]
            require(!Character.isLowSurrogate(char))
            if(Character.isHighSurrogate(char))require(index<name.length && Character.isLowSurrogate(name[index++]))
        }
        require(ContractDecimal.userQuantity(amount) != null)
        nutrition.values().filterNotNull().forEach { ContractDecimal.read(ContractDecimal.canonical(it)) }
        density?.let {ContractDecimal.read(ContractDecimal.canonical(it.gramsPerMl))}
        NutritionV1.calculate(listOf(portion()))
    }
    companion object {
        fun parse(name: String, amount: String, unit: String, basis: String, fields: List<String>,
            density: ExactDensity? = null): MealIngredientInput? = try {
            require(fields.size == 4)
            fun nutrient(text: String): BigDecimal? = text.trim().takeIf { it.isNotEmpty() }?.let {
                require(Regex("^(0|[1-9][0-9]{0,5})([.,][0-9]{1,6})?$").matches(it))
                ContractDecimal.read(ContractDecimal.canonical(BigDecimal(it.replace(',', '.'))))
            }
            val values = fields.map(::nutrient)
            MealIngredientInput(name.trim(), ContractDecimal.canonical(requireNotNull(ContractDecimal.userQuantity(amount))),
                QuantityUnit.read(unit), QuantityUnit.read(basis), ExactNutrition(values[0], values[1], values[2], values[3]), density)
                .also { it.validate() }
        } catch (_: IllegalArgumentException) { null }
    }
}
