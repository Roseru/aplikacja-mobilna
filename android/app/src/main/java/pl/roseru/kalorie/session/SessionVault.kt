package pl.roseru.kalorie.session

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import org.json.JSONObject
import java.io.File
import java.nio.ByteBuffer
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** One encrypted atomic record, outside backups. Call only while holding the session mutex.
 * AuthState, PKCE verifier and nonce never enter Room, DataStore, SavedStateHandle or logs.
 */
class SessionVault(context: Context, name: String = "oidc-session-v1") {
    init { require(name.matches(Regex("[A-Za-z0-9.-]+"))) }
    private val file = AtomicFile(File(context.noBackupFilesDir, name))
    private val alias = "${context.packageName}.$name"
    private val aad = "$alias:1".toByteArray(Charsets.UTF_8)
    private fun key(create: Boolean): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        check(create) { "Session key unavailable" }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).build())
        }.generateKey()
    }
    fun read(): JSONObject {
        if (!file.baseFile.exists() && !File(file.baseFile.path + ".bak").exists()) return JSONObject()
        val bytes = file.openRead().use { stream ->
            val data = ByteArray(262_145)
            var length = 0
            while (length < data.size) {
                val count = stream.read(data, length, data.size - length)
                if (count == -1) break
                length += count
            }
            require(length <= 262_144)
            data.copyOf(length)
        }
        require(bytes.size in 30..262_144 && bytes[0] == 1.toByte())
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(false), GCMParameterSpec(128, bytes.copyOfRange(1, 13)))
        cipher.updateAAD(aad)
        return JSONObject(String(cipher.doFinal(bytes.copyOfRange(13, bytes.size)), Charsets.UTF_8))
    }
    fun write(value: JSONObject) {
        val plain = value.toString().toByteArray(Charsets.UTF_8)
        require(plain.size <= 250_000)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key(true))
        check(cipher.iv.size == 12)
        cipher.updateAAD(aad)
        val encrypted = cipher.doFinal(plain)
        val bytes = ByteBuffer.allocate(1 + cipher.iv.size + encrypted.size).put(1).put(cipher.iv).put(encrypted).array()
        val stream = file.startWrite()
        try { stream.write(bytes); file.finishWrite(stream) }
        catch (error: Exception) { file.failWrite(stream); throw error }
    }
    fun clear() {
        file.delete()
        KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry(alias) }
    }
}
