package pl.roseru.kalorie.session

import pl.roseru.kalorie.core.PhotoHttpRequest
import pl.roseru.kalorie.core.PhotoAnalysisReadProtocol
import java.net.URL
import javax.net.ssl.HttpsURLConnection

/** No scheduling, implicit consent, retries or journal writes. Callers supply a captured account. */
internal interface PhotoAnalysisGateway {
    suspend fun send(session: ApiSession, request: PhotoHttpRequest, beforeSend: suspend () -> Unit): BootstrapHttpResult
}
internal class HttpsPhotoAnalysisGateway(base: String,
    private val open: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection }) : PhotoAnalysisGateway {
    private val endpoint = BootstrapHttpProtocol.endpoint(base).toString().removeSuffix("/me/bootstrap")
    override suspend fun send(session: ApiSession, request: PhotoHttpRequest, beforeSend: suspend () -> Unit) =
        HttpsJsonTransport.request(URL(endpoint + request.path),request.method,session,request.key,open,beforeSend,
            maxBytes = when(request) {
                is PhotoHttpRequest.Read -> PhotoAnalysisReadProtocol.MAX_BYTES
                is PhotoHttpRequest.Confirm -> pl.roseru.kalorie.core.PhotoConfirmation.MAX_RECEIPT_BYTES
                else -> 1_048_576
            },requireNoStore = true,syncEpoch = request.epoch,privateErrors = true,photo = request)
}
