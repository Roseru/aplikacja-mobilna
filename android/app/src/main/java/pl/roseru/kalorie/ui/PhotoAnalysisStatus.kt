package pl.roseru.kalorie.ui

import pl.roseru.kalorie.session.PhotoAnalysisPreview

/** Presentation only. A terminal failure never authorizes another upload or provider call. */
internal data class PhotoAnalysisStatus(val title: String, val message: String, val manual: Boolean)

internal fun photoAnalysisStatus(result: PhotoAnalysisPreview): PhotoAnalysisStatus = when {
    result.decision == "cancelled" -> PhotoAnalysisStatus(
        "Analiza anulowana", "Możesz zapisać posiłek ręcznie. Anulowanie analizy nie usuwa zapisanych posiłków.", true)
    result.decision == "confirmed" -> PhotoAnalysisStatus(
        "Propozycja zatwierdzona", "Propozycja zatwierdzona na serwerze. Sam odczyt nie dodaje jej do lokalnego dziennika.", false)
    result.state == "queued" -> PhotoAnalysisStatus(
        "Oczekiwanie na analizę", "Zdjęcie czeka na analizę. Posiłek nie został jeszcze zapisany.", false)
    result.state == "running" -> PhotoAnalysisStatus(
        "Analiza w toku", "Serwer analizuje zdjęcie. Posiłek nie został jeszcze zapisany.", false)
    result.state == "failed" -> PhotoAnalysisStatus("Analiza bez propozycji", failureMessage(result.errorCode), true)
    else -> PhotoAnalysisStatus(
        "Zapisany wynik analizy", "Propozycja do sprawdzenia. Posiłek nie został jeszcze zapisany.", false)
}

private fun failureMessage(code: String?): String = when (code) {
    "provider_result_unknown" -> "Nie otrzymaliśmy potwierdzonego wyniku od AI. Zlecenie zostało zakończone i nie będzie automatycznie ponawiane. Możesz dodać posiłek ręcznie."
    "provider_no_food", "provider_no_candidates" -> "AI nie przygotowało propozycji jedzenia na tym zdjęciu. Nie zapisano posiłku. Możesz uzupełnić go ręcznie."
    "provider_safety_block" -> "AI odmówiło analizy tego zdjęcia. Nie zapisano posiłku. Ręczne dodawanie jest dostępne."
    "ai_quota_exhausted", "provider_rate_limited" -> "Limit analiz został osiągnięty. To zlecenie zostało zakończone. Możesz dodać posiłek ręcznie, także bez internetu."
    "provider_unavailable" -> "Usługa AI jest niedostępna dla tego zlecenia. Nie zapisano posiłku. Możesz dodać go ręcznie."
    "provider_input_too_large" -> "AI nie mogło przetworzyć tego zdjęcia w dostępnym limicie. Nie zapisano posiłku. Możesz dodać go ręcznie."
    else -> "Nie udało się przygotować poprawnej propozycji. Nie zapisano posiłku. Możesz dodać go ręcznie."
}
