package pl.roseru.kalorie.community

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.util.UUID

/** The public online catalogue has its own contract; it is not a private product draft. */
class CommunityProtocolException : IllegalArgumentException("community_contract")

data class PublicProductRef(val id: String, val revision: Int) {
    init { CommunityProtocol.uuid(id); require(revision > 0) }
    fun json() = JSONObject().put("product_id", id).put("revision", revision)
}

class CommunityProduct internal constructor(
    private val canonical: String,
    val ref: PublicProductRef,
    val canonicalRef: PublicProductRef,
    val name: String,
    val basisUnit: String,
    val portionAmount: String,
    val portionUnit: String,
    val isMine: Boolean,
    val positive: Long,
    val negative: Long,
    val verified: Boolean,
    val visible: Boolean,
    val complete: Boolean,
) {
    fun json(): JSONObject = StrictJson.read(canonical.toByteArray(Charsets.UTF_8))
    fun stored(): String = canonical
    val sourceDescription: String get() = json().getString("source_description")
    val aliases: List<String> get() = CommunityProtocol.strings(json().getJSONArray("aliases"))
    val nutrition: ExactNutrition get() {
        val values = json().getJSONObject("nutrition_per_100")
        return ExactNutrition.read(ExactNutrition.fields.associateWith { if (values.isNull(it)) null else values.getString(it) })
    }
    val density: ExactDensity? get() = json().let { value ->
        if (value.isNull("density")) null else value.getJSONObject("density").let {
            // The DTO provides a description, not a density-source UUID. Never invent one.
            val citation = it.getString("source_description").takeIf { text -> text.length <= 500 }
                ?: "Gęstość: publiczny produkt ${ref.id}@${ref.revision}"
            ExactDensity(ContractDecimal.read(it.getString("amount")), citation)
        }
    }
    fun consumed(amount: String, unit: String) = NutritionV1.calculate(listOf(ExactPortion(
        ContractDecimal.read(amount), QuantityUnit.read(unit), QuantityUnit.read(basisUnit), nutrition, density)))
    override fun toString() = "CommunityProduct(${ref.id}@${ref.revision})"
}

data class CommunityPage(val items: List<CommunityProduct>, val next: String?)
data class CommunityFeedback(val product: PublicProductRef, val positive: Long, val negative: Long,
    val mine: Int?, val revision: Long, val isMine: Boolean)
data class CommunityCandidate(val product: PublicProductRef, val provenance: String,
    val reasons: List<String>, val confident: Boolean)
data class CommunityMatches(val decision: String, val existing: PublicProductRef?,
    val candidates: List<CommunityCandidate>, val missing: List<String>, val truncated: Boolean)

/** Strict keys/types and cross-field rules of contracts/schemas/community.schema.json. */
object CommunityProtocol {
    private val uuidPattern = Regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    private val identityFields = listOf("brand", "variant", "composition", "energy_kcal")
    private val sourceKinds = setOf("label", "recipe", "estimate", "ai")
    private val productKeys = setOf("product_id", "revision", "canonical_ref", "state_revision", "name", "aliases",
        "brand", "variant", "identity", "basis_unit", "nutrition_per_100", "portion", "density", "source_id",
        "source_kind", "source_description", "provenance", "verification", "visibility", "complete",
        "missing_nutrition_fields", "missing_identity_fields", "positive_votes", "negative_votes", "voters", "is_mine")
    fun uuid(value: String): String { require(uuidPattern.matches(value)); require(UUID.fromString(value).toString() == value); return value }
    fun text(value: String, max: Int = 2000): String {
        require(value.codePointCount(0, value.length) in 1..max && value.isNotBlank() && '\u0000' !in value)
        var index=0
        while(index<value.length) {
            val char=value[index]
            if(char.isHighSurrogate()){require(index+1<value.length && value[index+1].isLowSurrogate());index+=2}
            else {require(!char.isLowSurrogate());index++}
        }
        return value
    }
    fun strings(value: JSONArray): List<String> = (0 until value.length()).map { value.get(it).let { item -> require(item is String); item } }
    private fun keys(value: JSONObject, expected: Set<String>) { require(value.keys().asSequence().toSet() == expected) }
    private fun string(value: JSONObject, key: String): String = (value.get(key) as? String) ?: error("string")
    private fun bool(value: JSONObject, key: String): Boolean = (value.get(key) as? Boolean) ?: error("boolean")
    private fun count(value: JSONObject, key: String): Long {
        val number = value.get(key); require(number is Int || number is Long)
        return (number as Number).toLong().also { require(it >= 0) }
    }
    private fun revision(value: JSONObject, key: String): Int = count(value, key).also { require(it in 1..Int.MAX_VALUE.toLong()) }.toInt()
    private fun nullableString(value: JSONObject, key: String): String? = if (value.isNull(key)) null else string(value, key)
    fun ref(value: JSONObject): PublicProductRef { keys(value, setOf("product_id", "revision")); return PublicProductRef(uuid(string(value,"product_id")), revision(value,"revision")) }
    private inline fun <T> checked(action: () -> T): T = try { action() } catch (_: Exception) { throw CommunityProtocolException() }
    fun read(bytes: ByteArray): JSONObject = checked { StrictJson.read(bytes) }

    fun product(bytes: ByteArray): CommunityProduct = checked { product(read(bytes)) }
    fun product(value: JSONObject): CommunityProduct = checked {
        keys(value, productKeys)
        val product = PublicProductRef(uuid(string(value,"product_id")), revision(value,"revision"))
        val canonical = ref(value.getJSONObject("canonical_ref")); revision(value,"state_revision")
        val name = text(string(value,"name"))
        val aliases = strings(value.getJSONArray("aliases")); require(aliases.size <= 50); aliases.forEach { text(it) }
        val identity = value.getJSONObject("identity"); validateIdentity(identity)
        listOf("brand", "variant").forEach {
            require(nullableString(value,it) == nullableString(identity.getJSONObject(it),"value"))
        }
        val unit = string(value,"basis_unit"); QuantityUnit.read(unit)
        val nutrition = value.getJSONObject("nutrition_per_100"); keys(nutrition,ExactNutrition.fields.toSet())
        val missing = ExactNutrition.fields.filter { nutrition.isNull(it) }
        ExactNutrition.fields.filterNot { it in missing }.forEach { ContractDecimal.read(string(nutrition,it)) }
        require(strings(value.getJSONArray("missing_nutrition_fields")) == missing)
        require(bool(value,"complete") == missing.isEmpty())
        val missingIdentity = identityFields.take(3).filter { string(identity.getJSONObject(it),"state") == "unknown" } +
            if ("energy_kcal" in missing) listOf("energy_kcal") else emptyList()
        require(strings(value.getJSONArray("missing_identity_fields")) == missingIdentity)
        val portion = value.getJSONObject("portion"); quantity(portion)
        val density = if(value.isNull("density")) null else value.getJSONObject("density").also { validateDensity(it) }
        require(string(portion,"unit") == unit || density != null)
        uuid(string(value,"source_id")); require(string(value,"source_kind") in sourceKinds)
        text(string(value,"source_description")); require(string(value,"provenance") == "community")
        val verification = string(value,"verification"); require(verification in setOf("unverified","verified"))
        require(verification != "verified" || missing.isEmpty())
        val visibility = string(value,"visibility"); require(visibility in setOf("visible","hidden"))
        val positive=count(value,"positive_votes"); val negative=count(value,"negative_votes")
        require(Math.addExact(positive,negative) == count(value,"voters"))
        CommunityProduct(StrictJson.canonical(value),product,canonical,name,unit,string(portion,"amount"),string(portion,"unit"),
            bool(value,"is_mine"),positive,negative,verification=="verified",visibility=="visible",missing.isEmpty())
    }
    fun page(bytes: ByteArray): CommunityPage = checked {
        val value=read(bytes); keys(value,setOf("items","next_page_token"))
        val items=value.getJSONArray("items"); require(items.length()<=500)
        val products=(0 until items.length()).map { product(items.getJSONObject(it)) }
        require(products.map { it.ref.id }.distinct().size==products.size)
        val token=nullableString(value,"next_page_token")?.also { text(it,4096) }
        CommunityPage(products,token)
    }
    fun feedback(bytes: ByteArray): CommunityFeedback = checked {
        val value=read(bytes); keys(value,setOf("product","positive_votes","negative_votes","voters","my_value","my_revision","is_mine"))
        val positive=count(value,"positive_votes"); val negative=count(value,"negative_votes")
        require(Math.addExact(positive,negative)==count(value,"voters"))
        val mine=vote(value,"my_value")
        CommunityFeedback(ref(value.getJSONObject("product")),positive,negative,mine,count(value,"my_revision"),bool(value,"is_mine"))
    }
    private fun vote(value: JSONObject,key:String):Int? {
        if(value.isNull(key))return null
        val result=value.get(key); require(result is Int || result is Long)
        require((result as Number).toLong() in listOf(-1L,1L)); return result.toInt()
    }
    fun voteResult(bytes:ByteArray):Pair<Long,Int?> = checked {
        val value=read(bytes);keys(value,setOf("revision","value"));count(value,"revision") to vote(value,"value")
    }
    fun publishResult(bytes:ByteArray):Pair<String,PublicProductRef> = checked {
        val value=read(bytes);keys(value,setOf("decision","product"))
        val decision=string(value,"decision");require(decision in setOf("new_product","existing_variant","selected_existing"))
        decision to ref(value.getJSONObject("product"))
    }
    fun reportResult(bytes:ByteArray):String = checked {
        val value=read(bytes);keys(value,setOf("report_id","revision","status"));revision(value,"revision")
        require(string(value,"status") in setOf("open","resolved","dismissed","referred_to_admin"));uuid(string(value,"report_id"))
    }
    fun matches(bytes:ByteArray):CommunityMatches = checked {
        val value=read(bytes);keys(value,setOf("decision","existing_product","candidates","missing_identity_fields","truncated"))
        val decision=string(value,"decision");require(decision in setOf("existing_variant","manual_candidates","new_product"))
        val existing=if(value.isNull("existing_product"))null else ref(value.getJSONObject("existing_product"))
        require((decision=="existing_variant")== (existing!=null))
        val missing=strings(value.getJSONArray("missing_identity_fields"));require(missing.size<=4 && missing.all { it in identityFields })
        require(decision=="manual_candidates" || missing.isEmpty())
        val array=value.getJSONArray("candidates");require(array.length()<=20)
        val candidates=(0 until array.length()).map { i -> array.getJSONObject(i).let {
            keys(it,setOf("product","provenance","reasons","high_confidence"))
            val provenance=string(it,"provenance");require(provenance in setOf("official","community"))
            val reasons=strings(it.getJSONArray("reasons"));require(reasons.size in 1..20);reasons.forEach { reason->text(reason) }
            CommunityCandidate(ref(it.getJSONObject("product")),provenance,reasons,bool(it,"high_confidence"))
        } }
        CommunityMatches(decision,existing,candidates,missing,bool(value,"truncated"))
    }
    fun validateIdentity(value:JSONObject) {
        keys(value,setOf("brand","variant","composition"))
        listOf("brand","variant").forEach { key ->
            val item=value.getJSONObject(key);keys(item,setOf("state","value"));val state=string(item,"state")
            require(state in setOf("known","unknown","not_applicable"))
            require((state=="known")== !item.isNull("value"));if(state=="known")text(string(item,"value"))
        }
        val composition=value.getJSONObject("composition");keys(composition,setOf("state","value"))
        val state=string(composition,"state");require(state in setOf("known","unknown"))
        require((state=="known")== !composition.isNull("value"))
        if(state=="known")when(val item=composition.get("value")) {
            is String -> text(item,4000)
            is JSONArray -> {require(item.length() in 1..100);strings(item).forEach {text(it)}}
            else -> error("composition")
        }
    }
    private fun quantity(value:JSONObject) {
        keys(value,setOf("amount","unit"));require(ContractDecimal.read(string(value,"amount"))>BigDecimal.ZERO)
        QuantityUnit.read(string(value,"unit"))
    }
    private fun validateDensity(value:JSONObject) {
        keys(value,setOf("amount","source_description"));require(ContractDecimal.read(string(value,"amount"))>BigDecimal.ZERO)
        text(string(value,"source_description"))
    }
    fun publication(draftId:String,revision:Int,sourceKind:String,description:String,brandState:String,brand:String,
        variantState:String,variant:String,composition:String,aliases:List<String>,portionAmount:String?,portionUnit:String,
        densityAmount:String?,densityDescription:String):String {
        uuid(draftId);require(revision>0 && sourceKind in sourceKinds);text(description)
        val identity=JSONObject().put("brand",identityField(brandState,brand)).put("variant",identityField(variantState,variant))
            .put("composition",JSONObject().put("state",if(composition.isBlank())"unknown" else "known")
                .put("value",if(composition.isBlank())JSONObject.NULL else text(composition,4000)))
        validateIdentity(identity);require(aliases.size<=50);aliases.forEach {text(it)}
        val portion=portionAmount?.let { JSONObject().put("amount",it).put("unit",portionUnit).also(::quantity) }
        val density=densityAmount?.let {JSONObject().put("amount",it).put("source_description",densityDescription).also(::validateDensity)}
        return StrictJson.canonical(JSONObject().put("draft_id",draftId).put("draft_revision",revision)
            .put("source_kind",sourceKind).put("source_description",description).put("identity",identity)
            .put("aliases",JSONArray(aliases)).put("portion",portion?:JSONObject.NULL).put("density",density?:JSONObject.NULL))
    }
    private fun identityField(state:String,value:String)=JSONObject().put("state",state).put("value",if(state=="known")text(value) else JSONObject.NULL)
    fun publishBody(matchBody:String,selected:PublicProductRef?,confirmNew:Boolean):String {
        require(selected==null || !confirmNew)
        return StrictJson.canonical(read(matchBody.toByteArray()).put("selected_product",selected?.json()?:JSONObject.NULL).put("confirm_new",confirmNew))
    }
    fun reportBody(product:PublicProductRef,reason:String,description:String):String = StrictJson.canonical(JSONObject()
        .put("product",product.json()).put("reason",text(reason)).put("description",text(description)))
}
