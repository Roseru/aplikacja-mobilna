package pl.roseru.kalorie.session

/** One explicitly approved photo; UI must pass the provider/model/notice it actually displayed. */
class PhotoUploadConsent(val provider:String,val model:String,val noticeVersion:String) {
    override fun toString()="PhotoUploadConsent(redacted)"
}

/** Own local queue summary only. No token, account identity, image or response body. */
class PhotoUploadStatus(val operationId:String,val photoId:String,val provider:String,val model:String,
    val attempted:Boolean,val acknowledged:Boolean,val retryAtMillis:Long,val blocked:Boolean) {
    override fun toString()="PhotoUploadStatus(redacted)"
}
