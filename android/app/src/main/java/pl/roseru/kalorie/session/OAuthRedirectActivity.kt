package pl.roseru.kalorie.session

import android.app.Activity
import android.os.Bundle
import net.openid.appauth.AuthorizationManagementActivity
import pl.roseru.kalorie.R
import pl.roseru.kalorie.core.validateAuthCallback

/** Android ignores a path filter without a host for scheme:/path; enforce it here. */
class OAuthRedirectActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        try {
            val callback = checkNotNull(intent.data)
            validateAuthCallback(callback.toString(), packageName, getString(R.string.oidc_issuer))
            startActivity(AuthorizationManagementActivity.createResponseHandlingIntent(this, callback))
        } catch (_: Exception) {
            // Never display/log a callback URL, code, state, nonce or token.
        } finally { finish() }
    }
}
