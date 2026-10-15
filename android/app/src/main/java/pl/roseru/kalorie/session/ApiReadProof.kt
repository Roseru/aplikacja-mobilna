package pl.roseru.kalorie.session

/** Opaque validation observer: no DTO, credentials or identity leave the controller. */
internal interface ApiReadProof {
    fun dtoParsed()
    fun staleOwnerRejected()
}
