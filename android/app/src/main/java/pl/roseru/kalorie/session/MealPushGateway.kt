package pl.roseru.kalorie.session

import pl.roseru.kalorie.core.sync.PushBatch
import pl.roseru.kalorie.core.sync.PushProtocol
import java.net.URL
import javax.net.ssl.HttpsURLConnection

/** Sends a previously frozen envelope. Persistence, authentication, retry and ACK belong to callers. */
internal interface MealPushGateway {
    suspend fun post(session: ApiSession, batch: PushBatch, beforeSend: suspend () -> Unit): BootstrapHttpResult
}

internal class HttpsMealPushGateway(base: String,
    private val open: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection }) : MealPushGateway {
    private val endpoint = URL(BootstrapHttpProtocol.endpoint(base).toString()
        .removeSuffix("/me/bootstrap") + "/sync/push")

    override suspend fun post(session: ApiSession, batch: PushBatch, beforeSend: suspend () -> Unit) =
        HttpsJsonTransport.request(endpoint, "POST", session, null, open, beforeSend,
            maxBytes = PushProtocol.MAX_RESPONSE_BYTES, requireNoStore = true, privateErrors = true, push = batch)
}
