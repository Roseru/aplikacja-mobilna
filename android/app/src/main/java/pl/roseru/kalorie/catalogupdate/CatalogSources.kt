package pl.roseru.kalorie.catalogupdate

import pl.roseru.kalorie.core.catalog.CatalogManifest

data class CatalogSource(val id:String,val document:String,val url:String?,val checkedOn:String,
    val market:String?,val manufacturer:String?,val variant:String?,val basis:String,val verified:Boolean,
    val missing:List<String>,val notes:List<String>)
data class CatalogSourcePage(val manifest:CatalogManifest,val page:Int,val entries:List<CatalogSource>) {
    companion object {const val SIZE=5}
    val hasPrevious:Boolean get()=page>0
    val hasNext:Boolean get()=(page+1)*SIZE<manifest.sources
}
sealed interface CatalogSourcesState {
    data object Closed:CatalogSourcesState
    data class Loading(val manifest:CatalogManifest,val page:Int):CatalogSourcesState
    data class Ready(val value:CatalogSourcePage):CatalogSourcesState
    data class Failed(val manifest:CatalogManifest,val page:Int):CatalogSourcesState
}
