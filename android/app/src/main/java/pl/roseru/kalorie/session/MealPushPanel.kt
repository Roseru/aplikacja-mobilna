package pl.roseru.kalorie.session

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.data.OwnerLease

@Composable internal fun MealPushPanel(view:SessionView,synchronize:(OwnerLease)->Unit) {
    val binding=view.binding?:return
    if(binding.owner.kind!="account")return
    val status=view.mealPush
    val busy=view.busy || view.pendingLogin || view.bootstrapBusy || view.snapshotBusy || view.profileBusy ||
        view.motivationBusy || view.rankingConsentBusy || view.rankingBusy || view.nemesisBusy ||
        view.nemesisMutationBusy || view.photoUploadBusy || view.mealPushBusy
    Card(Modifier.fillMaxWidth().testTag("meal-push-panel")) {
        Column(Modifier.padding(20.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
            Text("Wysyłanie dziennika",style=MaterialTheme.typography.titleMedium)
            Text("Wyślij przygotowane zmiany sześciu typów danych tego konta. Wpisy gościa pozostają osobno.")
            if(status!=null) {
                Text("Gotowe: ${status.pending} · Czekają na poprzednią zmianę: ${status.waiting}",Modifier.testTag("meal-push-counts"))
                val labels = mapOf("meal" to "Posiłki", "weight" to "Waga", "profile" to "Profil",
                    "goal" to "Cele", "diary_day" to "Kompletność dni", "product_draft" to "Prywatne produkty")
                labels.forEach { (type, label) ->
                    status.domains[type]?.let { count -> Text("$label: gotowe ${count.pending}, oczekujące ${count.waiting}, do uzgodnienia ${count.refused}",
                        Modifier.testTag("sync-domain-$type")) }
                }
                if(status.persistedBatch)Text("Zapisana partia czeka na potwierdzenie. Ponowienie zachowa te same operacje.")
                if(status.refused>0)Text("Wymagają uzgodnienia: ${status.refused}. Lokalne dane zachowano.")
                if(status.legacy>0)Text("Starsze lub wymagające konwersji wpisy: ${status.legacy}. Pozostają lokalnie do świadomego uzgodnienia.")
            }
            if(!view.mealPushConfigured)Text("Wysyłanie będzie dostępne po podłączeniu serwera.")
            else if(view.snapshot?.blocked==true)Text("Konto jest usuwane. Wysyłanie pozostaje zablokowane; dane lokalne zachowano.")
            else if(view.requiresRecovery)Text("Sprawdź połączenie i pobierz kopię do uzgodnienia. Zwykłe wysyłanie pozostaje zablokowane.")
            else if(status?.ready!=true)Text("Najpierw połącz konto i pobierz pełną kopię danych serwera.")
            if(view.mealPushRetryAt>0)Text("Serwer może wymagać przerwy przed kolejną próbą. Jej termin jest sprawdzany przed wysyłką.")
            view.mealPushMessage?.let {Text(it,Modifier.testTag("meal-push-message"))}
            if(view.mealPushBusy){LinearProgressIndicator(Modifier.fillMaxWidth());Text("Wysyłam zapisaną kolejkę…")}
            Button(onClick={synchronize(binding.lease)},enabled=view.mealPushConfigured && view.serverLinked &&
                !view.requiresRecovery && status?.ready==true && !busy &&
                (status.pending>0 || status.persistedBatch),modifier=Modifier.fillMaxWidth().testTag("session-send-meals")) {
                Text(if(status?.persistedBatch==true)"Ponów zapisaną partię" else "Wyślij oczekujące wpisy")
            }
        }
    }
}
