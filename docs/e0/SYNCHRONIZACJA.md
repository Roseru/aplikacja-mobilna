# Synchronizacja i odzyskiwanie v1 - osoba 2

Status: **design draft E0**. [Schemat](../../contracts/schemas/sync.schema.json) i [scenariusze](../../contracts/examples/scenarios) opisują przyszłe zachowanie E4; walidator nie wykonuje transakcji serwera. Właściciel wynika wyłącznie z tokenu. UUID konta, epoka i generacja sesji wyznaczają osobny lokalny zakres synchronizacji.

## Kontenery i kolejność

`Entity` zawiera `entity_type`, `entity_id`, serwerową `revision`, `deleted` i typowany `payload`. Rewizja lokalna Androida jest odrębna i nie trafia do `base_revision`. Usunięcie ma `deleted=true,payload=null`; żywa encja zawiera pełny payload. Typy: profil, niezmienna wersja celu, posiłek wraz ze wszystkimi składnikami, pomiar, kompletność dnia, prywatny szkic produktu. Zgody są osobnymi operacjami online.

`Operation`: `operation_id`, `entity_type`, `entity_id`, `action=upsert|delete`, `base_revision`, `sync_epoch`, `payload`, opcjonalne `recovery`. Utworzenie ma `base_revision=null`; aktualizacja/usunięcie podaje znaną rewizję serwera. Delete ma `payload=null`. Serwer rozstrzyga istnienie i własność. UUID zastrzeżony po usunięciu nie może być ponownie utworzony.

Cel jest nowym UUID wersji, z datą obowiązywania, czasem decyzji i bazową rewizją osi. Aktualizacja treści istniejącej wersji zwraca `goal_immutable`; usunięcie używanej wersji `goal_in_use`, a innej wersji `goal_immutable`. Usuwanie celu nie zmienia osi; anulowanie przyszłego celu wymaga nowej audytowanej wersji. Dwie decyzje o tej samej bazowej osi dają `goal_timeline_conflict`. Jawna korekta historii wskazuje poprawianą wersję i zachowuje audyt. Posiłek wskazuje dokładny `goal_id` albo null; składniki są jednym agregatem i jedną transakcją. Klient najpierw potwierdza nowy cel, dopiero potem wysyła zależny posiłek (prywatny szkic nie jest referencją Meal; można zapisać ręczny snapshot składnika). Konflikt zależności wstrzymuje potomków. Data posiłku nie jest przesuwana przy synchronizacji ani zmianie strefy profilu.

Cykl klienta: pull → push → pull. Każda strona pull i token następnej strony są zapisywane atomowo. `server_shadow` jest oddzielony od lokalnych zmian. Późniejsza edycja już wysłanej operacji nie zmienia jej ID ani treści; czeka na wynik poprzednika i otrzymuje nowy `operation_id` oraz zwróconą rewizję. Utrata odpowiedzi oznacza ponowienie identycznej operacji.

## Push i wyniki

`PushRequest` ma `protocol_version=1`, bieżący `sync_epoch`, ukończony `checkpoint` i 1–100 operacji. Limit to 1 MiB nieskompresowanego JSON żądania oraz 256 KiB JSON payloadu pojedynczej encji, w UTF-8. Jedna paczka zmienia daną parę typ/UUID najwyżej raz; nie zawiera powtórzonych ID operacji. Transport sprawdza rzeczywiste bajty przed parsowaniem; lokalny walidator może sprawdzić tylko kompaktową reprezentację fixture’a. Reprezentacja hashująca nie zmienia limitu transportowego.

Przed mutacjami całej paczki serwer kontroluje uwierzytelnienie, zgodność epok każdego elementu, token checkpointu, jego wiek, strukturę i limity. Kolejność po autoryzacji: epoka przed wiekiem checkpointu. 401 wymaga zalogowania, 409 `sync_epoch_changed` odzyskiwania po restore, 409 `sync_reconciliation_required` pełnego snapshotu w tej samej epoce, 413 limitu bajtów, 422 struktury/tokenów. Żaden z tych błędów nie wykonuje zapisu encji. Poprawna paczka daje HTTP 200, nawet jeśli wszystkie operacje zakończą się konfliktem.

Operacje są przetwarzane w kolejności tablicy; każda ma własną transakcję. Wyniki występują w identycznej kolejności, jeden na operację:

| Status | Znaczenie |
|---|---|
| `accepted` | Zatwierdzona zmiana i jej rewizja |
| `already_applied` | Identyczna przyjęta operacja: pierwotna przyjęta rewizja, nawet jeśli encja ma dziś nowszą |
| `conflict` | Zachowanie lokalnej wersji i serwerowej `current`; potrzebna decyzja użytkownika |
| `rejected` | Zapamiętana odmowa, np. `operation_id_reused`, `goal_in_use`, `dependency_missing` |

Klucz idempotencji to `(owner_id,operation_id)`. Hash obejmuje cały obiekt operacji, w tym epokę i recovery, lecz nie checkpoint paczki. Kanonizacja: sortowanie kluczy obiektów, zachowanie kolejności tablic, UTF-8 bez zbędnych odstępów, dziesiętne ciągi sprowadzone według wspólnego kontraktu decimal. Normalizujemy tylko pola decimal rozpoznane przez schemat, nigdy dowolny tekst ani tokeny. Ten sam ID z inną treścią daje `rejected/operation_id_reused`; nie zastępuje pierwotnego potwierdzenia. Zapisany konflikt/odmowa przy ponowieniu zachowuje swój status i kod. Po 60 dniach `details_retained=false` dopuszcza `current=null`; kod pozostaje. Poprawienie odmowy tworzy nowy ID.

Serwer blokuje licznik konta do końca transakcji i razem zapisuje encję, rewizję, wynik, zmianę i ewentualne mapowanie odzyskania. Porządek pull wynika z zatwierdzenia tych transakcji, nie z czasu telefonu ani samego BIGSERIAL. Wszystkie mutacje online i worker stosują tę samą usługę.

## Pull, tokeny i granice czasu

`GET /sync/pull` używa definicji `PullRequest` jako ograniczeń całego zestawu query. `limit` domyślnie 500 (1–500). Parametry są nieprzezroczyste:

| Zestaw parametrów | Znaczenie |
|---|---|
| Brak tokenów; opcjonalne `sync_epoch`, `limit`, `recovery_operation_ids` | Start pełnego snapshotu; znana nieaktualna epoka daje 409 |
| `checkpoint`, `sync_epoch`; opcjonalne `page_token`, `limit` | Pierwsza/kolejna strona przyrostowa; zakaz `snapshot_token` |
| `snapshot_token`, `page_token`, `sync_epoch`; opcjonalne `limit` | Kontynuacja snapshotu; zakaz `checkpoint` |

`recovery_operation_ids` to do 100 UUID, query `form/explode`, tylko na początku snapshotu. Pozwala odczytać potwierdzenia zachowane w odtworzonej bazie; brak potwierdzenia nie dowodzi niewykonania operacji przed kopią. Dla większej lokalnej kolejki klient wykonuje kolejne pełne odczyty z kolejnymi grupami ID; nie dodajemy endpointu mutującego odzyskiwanie.

`checkpoint` potwierdza ukończony odczyt do H. `page_token` wskazuje następną stronę i nie uprawnia do push. `snapshot_token` identyfikuje materializowany niezmienny odczyt i wygasa po 60 min od utworzenia (w chwili wygaśnięcia jest nieważny). Android nie dekoduje ani nie podpisuje tokenów. Serwer wiąże je z kontem, generacją konta, protokołem, epoką i pozycją oraz weryfikuje podpis. Cudzy/uszkodzony token daje 422 `invalid_sync_token`, bez ujawnienia stanu innego konta.

Pierwszy snapshot powstaje w repeatable read z granicą H. Odpowiedzi paginują łącznie najwyżej 500 elementów `entities`, `recovery_mappings`, `operation_receipts`; ich porządek i granice są utrwalone. Pełny snapshot zawiera wszystkie żywe encje, bieżącą rewizję osi celu i trwałe mapowania; tombstone’y nie są wymagane, gdy ich szczegóły już usunięto. `operation_receipts` obejmują tylko żądane zachowane potwierdzenia. Po ostatniej stronie `page_token=null`, a `checkpoint` staje się nie-null. Wcześniejsze strony mają `checkpoint=null`. Po ukończeniu klient pobiera zmiany większe niż H. Retencja nie narusza aktywnego snapshotu.

Odczyt przyrostowy zamraża H przy pierwszej stronie; dopiero ostatnia wystawia nowy checkpoint. Zegar serwera ocenia wiek poprzedniego ukończonego checkpointu: **dokładnie 30 × 24 h nadal działa**, +1 s daje 410 `sync_cursor_expired`. Token strony nie odnawia tego okresu. Wygasły snapshot daje 410 `snapshot_expired`: zaczynamy pełny odczyt ponownie, zachowując lokalną bazę i outbox.

## Powrót po 30 dniach a restore

W tej samej epoce brak wcześniej znanego wpisu w ukończonym pełnym snapshotcie oznacza usunięcie. Nie wskrzeszamy go automatycznie; niewysłane operacje zachowują pierwotne ID i treść do sprawdzenia idempotencji. Świadome ponowne utworzenie po usunięciu dostaje nowy UUID.

Restore zmienia losowy `sync_epoch` przed otwarciem ruchu. Stara operacja jest odrzucana również z nowym checkpointem. Klient zatrzymuje push i zachowuje także wcześniej potwierdzone dane, rewizje i treść outbox. Pobiera nowy snapshot do oddzielnego obszaru, porównuje epoki, treść i potwierdzenia. Ta sama liczba rewizji między epokami nie oznacza zgodności; brak wpisu nie dowodzi usunięcia. `SyncError.details` przekazuje `current_sync_epoch`, `requested_sync_epoch` i `recovery_required=epoch_recovery`.

Po decyzji użytkownika nowa operacja w bieżącej epoce zawiera `recovery={source_epoch,source_entity_id,source_revision,source_operation_id,decision}`. Nieznana rewizja lub pierwotne ID operacji są null. `recreate_missing` wymaga nowego UUID, `base_revision=null` i `upsert`. `resolve_existing` wskazuje aktualną encję i jej bieżącą rewizję. Serwer sprawdza źródło, właściciela, istniejące potwierdzenie i zastrzeżenia UUID; źródło jest deklaracją klienta, nie dowodem uprawnienia.

Przy ponownym utworzeniu brakującego wpisu w tej samej transakcji powstaje unikalne `(owner_id,source_epoch,source_entity_id) → target_entity_id`. Nowe operacje drugiego urządzenia z tym samym źródłem i równoważną treścią otrzymują `already_applied` i istniejące `recovery_mapping`; nie powstaje druga encja. `entity_id` w wyniku odpowiada ID proponowanemu w żądaniu, a `recovery_mapping.target_entity_id` jest autorytatywnym rzeczywistym UUID do przyjęcia lokalnie. Rewizja wyniku jest rewizją istniejącego celu mapowania. `target_revision` w mapowaniu opisuje rewizję tego rekordu w chwili odpowiedzi/snapshotu; samo trwałe przypisanie UUID jest niezmienne. Równoważność treści odnosi się do bieżącego payloadu celu mapowania. Inna treść daje `recovery_content_conflict` z mapowaniem i stanem istniejącego celu. Równoczesne próby rozstrzyga ograniczenie UNIQUE i transakcja, nigdy sprawdzenie przed transakcją.

Zależne wpisy odzyskujemy po rodzicach, z nowymi referencjami celu. Oryginały pozostają lokalnie do potwierdzenia wszystkich decyzji. Zachowane potwierdzenie ze starej bazy nadal opisuje swój pierwotny wynik; odczyt przez `operation_receipts` nie legalizuje ponownego wykonania starej operacji.

## Gość, konta i trwałość

Gość nie zna epoki: lokalny szkic outbox ma `sync_epoch=null/unknown`, ale **nie jest jeszcze wire Operation**. Bootstrap nie importuje historii. Po świadomym przypisaniu zbioru do konta klient zapisuje trwałe lokalne mapowanie gość→konto, pobiera snapshot i dopiero materializuje niezmienne operacje z poznaną epoką. Zachowuje UUID encji i oryginały do potwierdzenia. Profil ma własny UUID niezależny od konta i najwyżej jeden żywy rekord na owner. Jeżeli konto ma już profil, import wymaga uzgodnienia i aktualizacji istniejącego profilu z jego rewizją, bez drugiego rekordu. Po delete albo utracie profilu przy restore nowy profil używa nowego UUID (przy restore z mapowaniem odzyskania). Zbioru nie można później przypisać do innego konta; wiek historii gościa nie ogranicza importu. Kolizja UUID jest konfliktem.

Przed wysłaniem i przed zapisem odpowiedzi WorkManager ponownie sprawdza konto oraz generację zadania. Przełączenie A→B nie przenosi właściciela outbox; opóźniona odpowiedź A jest ignorowana przez aktywny zakres B, a bezpieczny retry pozostaje w A. Tokeny nie trafiają do kolejki.

Szczegółowy dziennik zmian, pełne odpowiedzi i usunięte rekordy: minimum 60 × 24 h. Minimalne potwierdzenia (ID/hash/status/kod/encja/przyjęta rewizja), rezerwacje usuniętych UUID i mapowania odzyskania: do usunięcia konta. Żywe wpisy i wersje celu nie wygasają po 30 dniach. Usuwanie konta i blokada starego `(issuer,sub)` pozostają zgodne z wymaganiami 11.3.

## Weryfikacja E0 i przyszła E4

Schemat sprawdza typy komunikatów; `sync_checks.py` sprawdza unikalności, granice fixture’ów i spójność opisanych odpowiedzi. Scenariusze zawierają preconditions, żądania, oczekiwane statusy/odpowiedzi i oczekiwania klienta. Wynik lokalny „pass” oznacza poprawny kontrakt scenariusza. Transakcje, izolacja A/B, wyścigi mapowań, odtwarzanie i rzeczywiste granice czasu muszą być wykonane na PostgreSQL/Room w E4.
