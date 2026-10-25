package pl.roseru.kalorie

import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.catalogupdate.*
import pl.roseru.kalorie.core.catalog.*
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.data.CalorieDatabase
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger
import java.util.zip.GZIPOutputStream

/** Explicitly synthetic data, never an official catalogue delivery or real nutrition evidence. */
internal object CatalogUpdateFixtures {
    fun schema(context:Context)=CatalogSchema(
        JSONObject(context.assets.open("catalog/e2/common.schema.json").bufferedReader().use{it.readText()}),
        JSONObject(context.assets.open("catalog/e2/catalog.schema.json").bufferedReader().use{it.readText()}))
    data class Package(val descriptor:CatalogManifest,val manifest:ByteArray,val gzip:ByteArray)
    fun official(context:Context,release:Int=1,sourceCount:Int=1):Package {
        val schema=schema(context)
        val template=CatalogPackageReader(schema,CatalogPackageReader.DEMO_ID,"demo").read(
            context.assets.open("catalog/e2/manifest.json"),context.assets.open("catalog/e2/base-pl.1.json.gz.bin")).payload()
        fun id(name:String)=UUID.nameUUIDFromBytes("test-only-catalog-download-$name".toByteArray()).toString()
        val sourceTemplate=template.getJSONArray("sources").getJSONObject(0)
        val sources=JSONArray((0 until sourceCount).map { index->JSONObject(sourceTemplate.toString())
            .put("source_id",id("source-$index")).put("document_id","SYNTHETIC TEST SOURCE $index")
            .put("url",JSONObject.NULL).put("checked_on","2026-10-23").put("market","TEST")
            .put("manufacturer","FIXTURE").put("variant","SYNTHETIC").put("basis","per_100_g").put("status","verified")
            .put("missing_data",JSONArray()).put("notes",JSONArray(listOf("Synthetic fixture; not verified real-world food data."))) })
        val product=JSONObject(template.getJSONArray("products").getJSONObject(0).toString())
            .put("product_id",id("product")).put("revision",release).put("name","SYNTHETIC TEST FOOD")
            .put("aliases",JSONArray()).put("source_id",id("source-0")).put("status","verified")
            .put("basis_unit","g").put("package_quantity",JSONObject().put("amount","100").put("unit","g"))
            .put("density_g_per_ml",JSONObject.NULL).put("nutrition_per_100",JSONObject()
                .put("energy_kcal","100").put("protein_g","10").put("fat_g","2").put("carbs_g","15"))
        val ration=JSONObject(template.getJSONArray("rations").getJSONObject(0).toString())
            .put("ration_id",id("ration")).put("revision",release).put("name","SYNTHETIC TEST RATION")
            .put("source_id",id("source-0")).put("manufacturer","FIXTURE").put("status","verified").put("complete",true)
            .put("excluded_items",JSONArray())
        val part=JSONObject(ration.getJSONArray("components").getJSONObject(0).toString()).put("position",1)
            .put("product",JSONObject().put("product_id",id("product")).put("revision",release))
            .put("quantity",JSONObject().put("amount","100").put("unit","g"))
        ration.put("components",JSONArray().put(part))
        val counts=JSONObject().put("products",1).put("rations",1).put("components",1).put("sources",sourceCount)
        val payload=template.put("package_id",CatalogPackageReader.OFFICIAL_ID).put("kind","official").put("release",release)
            .put("products",JSONArray().put(product)).put("rations",JSONArray().put(ration)).put("sources",sources).put("counts",counts)
        val raw=payload.toString().toByteArray(Charsets.UTF_8)
        val gzip=ByteArrayOutputStream().also{out->GZIPOutputStream(out).use{it.write(raw)}}.toByteArray()
        val manifest=JSONObject(context.assets.open("catalog/e2/manifest.json").bufferedReader().use{it.readText()})
            .put("package_id",CatalogPackageReader.OFFICIAL_ID).put("kind","official").put("release",release)
            .put("path","base-pl.$release.json.gz").put("counts",counts).put("source_ids",JSONArray((0 until sourceCount).map{id("source-$it")}))
            .put("compressed_bytes",gzip.size).put("uncompressed_bytes",raw.size).put("sha256",sha(gzip)).toString().toByteArray(Charsets.UTF_8)
        return Package(CatalogPackageReader(schema,CatalogPackageReader.OFFICIAL_ID,"official").inspect(manifest.inputStream()),manifest,gzip)
    }
    fun sha(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it.toInt() and 255)}
    fun privateRows(db:CalorieDatabase):Map<String,List<List<String?>>> {
        val database=db.openHelper.readableDatabase
        val tables=database.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'catalog_%' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'room_%' AND name NOT LIKE 'android_%' AND name NOT IN ('products','rations','ration_components') ORDER BY name").use {cursor->
            buildList{while(cursor.moveToNext())add(cursor.getString(0))}
        }
        return tables.associateWith {table->database.query("SELECT * FROM \"$table\" ORDER BY rowid").use {cursor->
            buildList{while(cursor.moveToNext())add((0 until cursor.columnCount).map{column->if(cursor.isNull(column))null else cursor.getString(column)})}
        }}
    }
    class Gate:ObservableNetworkAccessGate() {
        fun allow(revision:Long=1){publish(NetworkAccessState.Allowed(revision))}
        fun block(){publish(NetworkAccessState.Blocked)}
    }
    class Gateway(var published:Package):CatalogDownloadGateway {
        val checks=AtomicInteger();val downloads=AtomicInteger()
        var response:CatalogHttpResult?=null
        var bytes:ByteArray?=null
        var onDownload:suspend(File,NetworkPermit)->Unit={_,_->}
        override suspend fun manifest(permit:NetworkPermit):CatalogHttpResult {
            checks.incrementAndGet();return response?:CatalogHttpResult.Success(published.manifest)
        }
        override suspend fun download(manifest:CatalogManifest,target:File,permit:NetworkPermit,progress:(Long,Long)->Unit):CatalogHttpResult {
            downloads.incrementAndGet();onDownload(target,permit)
            val body=bytes?:published.gzip
            target.writeBytes(body);progress(body.size.toLong(),manifest.compressedBytes.toLong())
            return CatalogHttpResult.Success()
        }
    }
    class PreferenceContext(base:Context,val prefix:String="test-catalog-${UUID.randomUUID()}-"):ContextWrapper(base) {
        override fun getApplicationContext():Context=this
        override fun getSharedPreferences(name:String,mode:Int):SharedPreferences=baseContext.getSharedPreferences(prefix+name,mode)
        fun clear(){baseContext.deleteSharedPreferences(prefix+"catalog-download-backoff")}
    }
}
