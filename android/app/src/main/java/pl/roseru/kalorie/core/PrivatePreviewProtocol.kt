package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.util.UUID

enum class PrivatePreviewKind { MOTIVATION,RANKING,NEMESIS_LIST,NEMESIS_DETAIL }

/** Historical read-only values. They deliberately are not live read/consent/decision sources. */
sealed interface PrivatePreviewValue {
    val motivation:MotivationRead
    class Motivation(override val motivation:MotivationRead):PrivatePreviewValue
    class Ranking(override val motivation:MotivationRead,val page:RankingPage):PrivatePreviewValue
    class NemesisList(override val motivation:MotivationRead,val page:NemesisPage):PrivatePreviewValue
    class NemesisDetail(override val motivation:MotivationRead,val challenge:NemesisChallenge,val statistics:NemesisStatistics?):PrivatePreviewValue
}

/** A client cache envelope, never a server protocol or a persisted mutation. */
object PrivatePreviewProtocol {
    const val VERSION=1
    const val MAX_BYTES=1_048_576
    fun requireKey(kind:PrivatePreviewKind,resource:String) {
        if(kind==PrivatePreviewKind.NEMESIS_DETAIL)require(UUID.fromString(resource).toString()==resource)
        else require(resource==if(kind==PrivatePreviewKind.MOTIVATION)"self" else "latest")
    }
    fun decode(kind:PrivatePreviewKind,resource:String,bytes:ByteArray,generation:Int,epoch:String):PrivatePreviewValue {
        requireKey(kind,resource);require(bytes.size in 1..MAX_BYTES)
        val json=StrictJson.read(bytes)
        val fields=when(kind) {
            PrivatePreviewKind.MOTIVATION->setOf("format_version","motivation")
            PrivatePreviewKind.RANKING->setOf("format_version","motivation","ranking","request_cursor")
            PrivatePreviewKind.NEMESIS_LIST->setOf("format_version","motivation","listing","request_cursor")
            PrivatePreviewKind.NEMESIS_DETAIL->setOf("format_version","motivation","challenge","statistics")
        }
        require(json.keys().asSequence().toSet()==fields && json.get("format_version")==VERSION)
        val own=MotivationReadProtocol.parse(body(json,"motivation"))
        require(own.accountGeneration==generation && own.syncEpoch==epoch)
        return when(kind) {
            PrivatePreviewKind.MOTIVATION->PrivatePreviewValue.Motivation(own)
            PrivatePreviewKind.RANKING->{
                val cursor=if(json.isNull("request_cursor"))null else json.get("request_cursor") as String
                PrivatePreviewValue.Ranking(own,RankingReadProtocol.parse(body(json,"ranking"),RankingQuery(cursor)))
            }
            PrivatePreviewKind.NEMESIS_LIST->{
                val cursor=if(json.isNull("request_cursor"))null else json.get("request_cursor") as String
                PrivatePreviewValue.NemesisList(own,NemesisReadProtocol.page(body(json,"listing"),NemesisQuery.Listing(cursor)))
            }
            PrivatePreviewKind.NEMESIS_DETAIL->{
                val challenge=NemesisReadProtocol.detail(body(json,"challenge"),resource)
                val statistics=if(json.isNull("statistics"))null else NemesisReadProtocol.statistics(body(json,"statistics"),challenge)
                require((challenge.status in setOf("active","finished"))==(statistics!=null))
                PrivatePreviewValue.NemesisDetail(own,challenge,statistics)
            }
        }
    }
    /** Drop former partner names from durable payloads when sharing ends. */
    fun canonicalForStorage(kind:PrivatePreviewKind,resource:String,bytes:ByteArray,generation:Int,epoch:String):String {
        val value=decode(kind,resource,bytes,generation,epoch)
        val json=StrictJson.read(bytes)
        when(value) {
            is PrivatePreviewValue.NemesisList->{
                val items=json.getJSONObject("listing").getJSONArray("items")
                value.page.items.forEachIndexed {index,item->if(item.status=="cancelled")items.getJSONObject(index).put("partner_pseudonym",JSONObject.NULL)}
            }
            is PrivatePreviewValue.NemesisDetail->if(value.challenge.status=="cancelled")json.getJSONObject("challenge").put("partner_pseudonym",JSONObject.NULL)
            else->Unit
        }
        return StrictJson.canonical(json)
    }
    private fun body(value:JSONObject,key:String)=StrictJson.canonical(value.getJSONObject(key)).toByteArray(Charsets.UTF_8)
}
