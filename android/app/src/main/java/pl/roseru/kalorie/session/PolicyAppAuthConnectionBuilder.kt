package pl.roseru.kalorie.session

import android.net.Uri
import net.openid.appauth.connectivity.ConnectionBuilder
import pl.roseru.kalorie.core.network.*
import java.net.HttpURLConnection
import java.net.URL

/** Discovery/token requests use the same provider as API and catalog downloads. */
internal class PolicyAppAuthConnectionBuilder(private val connections:PolicyConnectionFactory):ConnectionBuilder {
    override fun openConnection(uri:Uri):HttpURLConnection=connections.open(URL(uri.toString())).apply {
        connectTimeout=15_000;readTimeout=15_000;useCaches=false;instanceFollowRedirects=false
    }
}
internal object ClosedAppAuthConnectionBuilder:ConnectionBuilder {
    override fun openConnection(uri:Uri):HttpURLConnection=throw NetworkAccessDenied(NetworkDenial.UNAVAILABLE)
}
