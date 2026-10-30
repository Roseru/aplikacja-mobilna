package pl.roseru.kalorie.photo

import android.app.Application
import android.net.Uri
import androidx.core.content.FileProvider
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import java.io.File
import java.time.LocalDate
import java.util.UUID

class MealPhotoViewModel(private val context: Application, private val store: MealPhotoStore, private val saved: SavedStateHandle) : ViewModel() {
    private val mutableBusy = MutableStateFlow(false)
    private val mutableMessage = MutableStateFlow<String?>(null)
    private val mutableSelection = MutableStateFlow(false)
    val busy = mutableBusy.asStateFlow()
    val message = mutableMessage.asStateFlow()
    val selectionPending = mutableSelection.asStateFlow()
    val drafts = store.drafts.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())
    init {
        if (saved.get<String>("photo-source") != null && pendingMatches()) { mutableBusy.value = true; mutableSelection.value = true }
        else clearPending()
    }
    private fun pendingMatches():Boolean = runCatching {
        val id=checkNotNull(saved.get<String>("photo-id"))
        val date=checkNotNull(saved.get<String>("photo-date"))
        saved.get<String>("photo-owner") == store.lease.storageScope && saved.get<Long>("photo-generation") == store.lease.generation &&
            saved.get<String>("photo-source") in setOf("camera","gallery") && UUID.fromString(id).toString()==id && LocalDate.parse(date).toString()==date
    }.getOrDefault(false)
    private fun reserve(source: String, date: LocalDate): Boolean {
        if (mutableBusy.value) return false
        saved["photo-owner"] = store.lease.storageScope
        saved["photo-generation"] = store.lease.generation
        saved["photo-date"] = date.toString()
        saved["photo-id"] = UUID.randomUUID().toString()
        saved["photo-source"] = source
        mutableBusy.value = true
        mutableSelection.value = true
        mutableMessage.value = null
        return true
    }
    fun beginGallery(date: LocalDate, launch: () -> Unit) {
        if (!reserve("gallery", date)) return
        try { launch() } catch (_: Exception) { cancelSelection(); mutableMessage.value = "Galeria jest niedostępna. Możesz dodać posiłek ręcznie." }
    }
    fun beginCamera(date: LocalDate, launch: (Uri) -> Unit) {
        if (!reserve("camera", date)) return
        viewModelScope.launch {
            try {
                val file = withContext(Dispatchers.IO) {
                    captureFile(checkNotNull(saved.get<String>("photo-id"))).also {
                        check(it.parentFile!!.isDirectory || it.parentFile!!.mkdirs())
                        check(it.createNewFile())
                    }
                }
                launch(FileProvider.getUriForFile(context, "${context.packageName}.photo-capture", file))
            } catch (error: CancellationException) { throw error }
            catch (_: Exception) { cancelSelection(); mutableMessage.value = "Aparat jest niedostępny. Wybierz zdjęcie z galerii lub dodaj posiłek ręcznie." }
        }
    }
    fun galleryResult(uri: Uri?) {
        if (!pendingMatches() || saved.get<String>("photo-source") != "gallery") return
        if (uri == null) { cancelSelection(); return }
        importResult { require(uri.scheme == "content"); requireNotNull(context.contentResolver.openInputStream(uri)) }
    }
    fun cameraResult(success: Boolean) {
        if (!pendingMatches() || saved.get<String>("photo-source") != "camera") return
        if (!success) { cancelSelection(); return }
        val id = checkNotNull(saved.get<String>("photo-id"))
        importResult { captureFile(id).inputStream() }
    }
    private fun importResult(open: () -> java.io.InputStream) {
        val id = checkNotNull(saved.get<String>("photo-id"))
        val date = LocalDate.parse(checkNotNull(saved.get<String>("photo-date")))
        val source = checkNotNull(saved.get<String>("photo-source"))
        clearPending()
        mutableBusy.value = true
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { open().use { store.import(it,date,source,id) } }
                mutableMessage.value = "Zdjęcie zapisane na telefonie."
            } catch (error: CancellationException) { throw error }
            catch (_: Exception) { mutableMessage.value = "Nie udało się zapisać zdjęcia. Wybierz pojedynczy obraz do 20 MB lub dodaj posiłek ręcznie." }
            finally {
                withContext(Dispatchers.IO + NonCancellable) { if (source == "camera") captureFile(id).delete() }
                mutableBusy.value = false
            }
        }
    }
    fun cancelSelection() {
        if (!pendingMatches()) { clearPending(); mutableBusy.value = false; return }
        val id = saved.get<String>("photo-id")
        val camera = saved.get<String>("photo-source") == "camera"
        clearPending()
        mutableBusy.value = false
        if (camera && id != null) viewModelScope.launch(Dispatchers.IO) { captureFile(id).delete() }
    }
    fun delete(id: String) {
        if (mutableBusy.value) return
        mutableBusy.value = true
        viewModelScope.launch {
            try { store.delete(id); mutableMessage.value = "Lokalne zdjęcie usunięte." }
            catch (error: CancellationException) { throw error }
            catch (_: Exception) { mutableMessage.value = "Nie udało się usunąć zdjęcia. Spróbuj ponownie." }
            finally { mutableBusy.value = false }
        }
    }
    suspend fun preview(id: String) = store.preview(id)
    internal suspend fun preview(id: String, diagnosticRequest: Long) = store.preview(id, diagnosticRequest)
    private fun clearPending() {
        mutableSelection.value = false
        listOf("photo-owner","photo-generation","photo-date","photo-id","photo-source").forEach { saved.remove<Any>(it) }
    }
    private fun captureFile(id: String): File {
        require(UUID.fromString(id).toString() == id)
        return File(File(context.cacheDir,"photo-captures"), "$id.jpg")
    }
    override fun onCleared() {
        if(pendingMatches() && saved.get<String>("photo-source")=="camera") {
            val file=captureFile(checkNotNull(saved.get<String>("photo-id")))
            runCatching {
                context.revokeUriPermission(FileProvider.getUriForFile(context,"${context.packageName}.photo-capture",file),
                    android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                file.delete()
            }
        }
        super.onCleared()
    }
}
