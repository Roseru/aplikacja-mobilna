package pl.roseru.kalorie

import android.content.Context
import android.content.pm.ApplicationInfo
import android.util.Log
import java.util.concurrent.atomic.AtomicLong

/** Debug-only process counters and fixed phases; never owner keys, scopes, UUIDs or payloads. */
internal object DiaryStartupDiagnostics {
    private val sequence=AtomicLong()

    fun request(context:Context):Long? = runCatching {
        if(context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE!=0) sequence.incrementAndGet() else null
    }.getOrNull()

    private fun record(message:()->String) {
        // Diagnostic output must not change startup or teardown if logging is unavailable.
        runCatching {Log.d("DiaryStartup",message())}
    }

    fun model(id:Long?,attempt:Long,phase:String,error:Class<out Throwable>?=null) {
        if(id!=null) record {"model=$id attempt=$attempt phase=$phase"+
            (error?.let {" errorClass=${it.name}"}?:"")}
    }

    fun rendered(id:Long?,ready:Boolean,error:Boolean) {
        if(id!=null) record {"model=$id phase=RENDER ready=$ready error=$error"}
    }

    fun store(id:Long?,phase:String,reason:String) {
        if(id!=null) record {"store=$id phase=$phase reason=$reason"}
    }

    fun attached(store:Long?,model:Long?) {
        if(store!=null && model!=null) record {"store=$store model=$model phase=ATTACH"}
    }
}
