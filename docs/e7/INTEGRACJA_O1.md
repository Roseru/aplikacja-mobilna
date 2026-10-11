# Integracja analizy zdjęć E7 z Androidem - osoba 2

Stan interfejsów odczytany 11 października 2026 na `codex/backend-e7-analiza-zdjec`.
Dokument przekazuje obecne DTO i runtime E7-O2. Wyniki końcowych testów, niezależnego
odbioru i CI określa raport wykonawcy; ten dokument nie potwierdza APK ani E7-R.
Normatywne źródła to [router](../../backend/src/calorie_app/modules/ai/router.py),
[DTO](../../backend/src/calorie_app/modules/ai/schemas.py),
[wynik providera](../../backend/src/calorie_app/modules/ai/result.py),
[confirm/cancel](../../backend/src/calorie_app/modules/ai/decisions.py),
[OpenAPI](../../backend/openapi.json) oraz istniejący
[kontrakt domeny](../../contracts/schemas/domain.schema.json).

## Chronione operacje i kontekst konta

| Metoda i ścieżka | Wejście i wynik |
|---|---|
| `GET /api/v1/ai/capabilities` | JWT; provider, notice, dostępność i limity. |
| `POST /api/v1/ai/food-analyses` | JWT, `Idempotency-Key`, `X-Sync-Epoch`, jeden multipart; 202 `CreateResponse`. |
| `GET /api/v1/ai/food-analyses/{analysis_id}` | JWT; 200 własny `AnalysisResponse`. |
| `POST /api/v1/ai/food-analyses/{analysis_id}/confirm` | JWT, oba nagłówki, JSON `ConfirmRequest`; 200 zatwierdzone szablony. |
| `POST /api/v1/ai/food-analyses/{analysis_id}/cancel` | JWT, oba nagłówki, JSON `CancelRequest`; 200 anulowanie. |

UUID-y używają kanonicznego tekstu z małymi literami i myślnikami. `X-Sync-Epoch`
pochodzi z aktualnego bootstrapu; zdjęcie, key, analysis ID, wynik i lokalny zapis
pozostają w zakresie tego samego konta. Backend sprawdza bieżące konto, generację
i epokę przed trwałym replay. Cudzy i nieistniejący analysis ID mają jednakowe 404;
rola moderatora/admina nie udostępnia cudzych analiz.

Po przełączeniu konta odpowiedź wcześniejszego requestu może być zapisana tylko
w jego pierwotnym zakresie. O1 stosuje własne zabezpieczenie sesji/Room/WorkManager
jak dla standardowego sync; aktualny ekran drugiego konta nie przejmuje tej odpowiedzi.

## Capabilities i świadoma zgoda na ten obraz

`Capabilities` zwraca `provider` (`mock` albo `gemini`),
publiczny `profile` (model/warianty prompt/schema/preparation/REST, bez sekretów
i identyfikatorów puli), `notice_version="food-photo-notice-v1"`, `available`,
`unavailable_reason` i limity:
`image_bytes=5242880`, `body_bytes=6291456`, `ingredients=30`, `daily_photos=10`,
`queue_seconds=300`, `attempt_seconds=45`, `total_seconds=120`,
`max_generate_attempts=2`, `manual_entry_available=true`.
Publiczne limity równoległości to `max_outbound_calls=2` i
`active_jobs_per_account=1`. Profil można sprawdzić przed wysłaniem zdjęcia.
Dostępność zależy także od konfiguracji, bramki restore/puli i prywatnego storage.
Monitorowanie żywego workera zapewnia O3. Stan `available` nie rezerwuje dziennego
limitu ani miejsca dla kolejnego requestu.

O1 pokazuje informację przypisaną do wersji notice, wybranego providera i zakresu
jednego zdjęcia. Informacja powinna wyjaśniać cel wysyłki, charakter szacunków,
retencję naszego backendu do zakończenia zlecenia/maksymalnie 24 h oraz odrębne
zasady dostawcy. API dostarcza numer notice; tekst informacji w UI jest zadaniem O1.
Mock ma być widocznie opisany jako scenariusz testowy serwera. Nie ma funkcji
rozpoznawania dowolnego zdjęcia offline ani zgody domyślnie włączonej.

Pełne metadata mają jedynie pole `consent`, z wymaganymi polami
`accepted=true`, aktualnym `notice_version`, `provider` odczytanym z capabilities
i `scope="this_photo"`. Przykład rzeczywistego kontraktu:
[create-metadata.json](../../contracts/examples/e7/create-metadata.json).
Nie dodawaj owner/model/status/API URL lub własnych pól. Stare `UserConsent`
dotyczące rankingu/automatu energii nie zastępuje tej zgody.

## Jeden multipart, przygotowanie i retry

POST przyjmuje dokładnie dwie części `metadata` i `image`; kolejność jest dowolna.
`metadata` ma `Content-Type: application/json` (opcjonalnie `charset=UTF-8`),
JSON UTF-8 do 16 KiB. `image` zawiera bajty jednego JPEG/PNG/WebP do 5 MiB.
Cały multipart, razem z boundary i nagłówkami, musi zmieścić się w 6 MiB.
Nie umieszczaj JSON jako zwykłego formularzowego stringa bez Content-Type części.
Parser odrzuca dodatkowe/zdublowane części, duplicate JSON keys, niepoprawny UTF-8,
depth większy niż 20 i kompresję body; request używa zwykłego `Content-Encoding`
identity albo nie podaje tego nagłówka. Filename nie jest identyfikatorem zasobu.

Backend sprawdza zgodę i trwały replay przed dekodowaniem oraz zapisem przygotowanego
pliku. Oryginał/body pozostają w bounded pamięci. Limity codec: 4096 px na bok,
16 mln pikseli, pojedyncza klatka, bez animacji. Backend stosuje orientację EXIF,
RGB, białe tło dla przezroczystości, skalowanie do 1600 px na dłuższym boku i nowe
kodowanie JPEG bez prywatnych metadanych. Wersja procedury to
`food-photo-preparation-v1`; parametry i decoder są przypięte po stronie serwera.
Klient może wcześniej zastosować orientację/usunąć EXIF i ograniczyć rozmiar,
ale ponowne przygotowanie oraz walidację wykonuje backend.

Przed pierwszym POST nadaj UUID `Idempotency-Key` i zachowaj dokładne wysyłane
bajty obrazu wraz z semantycznymi metadata w zakresie konta. Lost ACK ponawia ten
sam key/body/epokę. Nowe kodowanie nawet tego samego widocznego zdjęcia zmienia
hash bajtów i może dać 409 `idempotency_key_reused`. Boundary, kolejność części
i filename nie należą do semantycznego hasha. Zapis obrazu na urządzeniu i jego
retencję określa O1; serwerowy plik nie jest kopią zapasową zdjęcia telefonu.

Replay create zwraca pierwotną odpowiedź 202 bez kolejnego joba/zgody/pliku/provider
call. Może więc ponownie zawierać pierwotny `state="queued"`: bieżący stan pobierz
osobnym GET. Nie wysyłaj nowego create w celu sprawdzania postępu. Nowy klucz jest
potrzebny dla nowego świadomego zlecenia albo poprawionego trwale odrzuconego requestu.

## Stan, wynik i anulowanie

`CreateResponse`: `analysis_id`, `revision`, `state`, `queue_deadline`, `profile`.
Przypięty `profile` zawiera provider/model, wersje prompt/schema/preparation/REST
i nullable `mock_scenario`. Nie ustawiaj tych pól w create.

`AnalysisResponse` dodaje `decision_state` (`pending/confirmed/cancelled`),
`photo_expires_at`, nullable `proposal` i `error_code`. Stany robocze są
`queued/running/succeeded/failed`. Polluj własne ID z ograniczonym backoff;
obserwuj deadline serwera i udostępniaj powrót do ręcznego wpisu. Wygaśnięcie kolejki,
quota, błędny wynik lub `provider_result_unknown` nie zapisują posiłku.
Nie powtarzaj automatycznie analizy po niepewnym wyniku dostawcy; nowe zlecenie
wymaga nowej świadomej zgody. Backend przeprowadza dopuszczalne próby sam.

Propozycja ma 1–30 `items`, do 10 ogólnych `notes`, `totals`, nullable
`model_version` i `formula_version="nutrition_v1"`. Składnik ma nadany przez backend
`component_id`, nazwę, dodatnią `quantity` w g/ml, `basis_unit`, `nutrition_per_100`,
E6 `identity`, `density=null`, `uncertainty=low/medium/high`, do 5 `notes` oraz
`matches`. Nazwy składników i uwagi traktuj jako tekst; tekst obrazu/modelu nie
stanowi instrukcji uruchamiania narzędzi.

Wartości odżywcze/ilości są kanonicznymi Decimal strings, a brak wartości pozostaje
`null`. Total dla każdej z energii/B/T/W ma `known_sum`, `missing_count`, `complete`
i `display`. Pokazuj niepełność przy brakach. Model v1 nie dokumentuje gęstości:
ilość i podstawa mają tę samą jednostkę. Użytkownik może przy confirm dodać rzeczywiste
potwierdzone źródło gęstości; g↔ml wymaga takiego źródła. Ilość w ml sama nie wymaga
przeliczenia na gramy.

`matches` używa E6 `decision=existing_variant/manual_candidates/new_product`,
nullable `existing_product`, najwyżej 20 `candidates`, `missing_identity_fields`
i `truncated`. Candidate ma exact `product_id`/`revision`, `provenance`, `reasons`
i `high_confidence`. Użytkownik wybiera; matching nie publikuje/scalania produktu
i nie gwarantuje aktualności wyboru w chwili confirm.

Cancel wysyła JSON zawierający jedynie `expected_revision` z ostatniego odczytu
oraz własny key/epokę. Wynik ma `state="failed"`, `decision_state="cancelled"`
i `error_code="analysis_cancelled"`. Przed kwalifikacją dispatch cofnięcie blokuje
call; później żądanie mogło już zostać wysłane. Cancel blokuje dalsze próby i wynik
oraz inicjuje cleanup, bez obietnicy cofnięcia zdjęcia już wysłanego do dostawcy.
Zatwierdzonej decyzji nie zmienia się przez cancel.

## Confirm, szablony i jedyny zapis dziennika przez sync

Confirm jest pełną korektą, a nie `accept=true`. JSON zawiera `expected_revision`,
`meal={meal_id,payload}` i `drafts` (0–30 elementów `{draft_id,payload}`).
`meal_id`, wszystkie `item_id` i `draft_id` nadaje O1 przed wysłaniem i utrzymuje
stabilnie przez retry. Użyj ścisłych istniejących `Meal`/`MealItem` i `ProductDraft`:
wszystkie wymagane nullable pola są obecne, dodatkowe pola są zabronione. E7
ogranicza posiłek do 30 składników, choć ogólny kontrakt Meal ma większy limit.
`goal_id`, jeśli podany, musi być własny. Draft IDs nie mogą się powtarzać,
`source_description` szkicu zawiera jawne `AI` i szkic odpowiada składnikowi
zatwierdzanego posiłku pod względem nazwy, podstawy, wartości i gęstości/źródła.

Każdy składnik confirm ma `nutrition_origin="ai_estimate"` albo `catalog_snapshot`.
Świadomie zatwierdzony szacunek pozostaje `ai_estimate`, również przy publicznym
`product`. Można zrezygnować z referencji i wysłać `product=null`. `catalog_snapshot`
wymaga publicznego exact ref oraz zgodnych aktualnych wartości/podstawy katalogu.
Ukryty/stary/scalony wybór daje 409 `photo_catalog_choice_changed`: pobierz nowe
informacje i pozwól ponownie wybrać. Backend nie przekierowuje ref po cichu.

Confirm jest możliwy dla `succeeded/pending` i właściwej rewizji. Wynik zawiera
`analysis_id`, ścisły `meal`, `drafts` oraz oddzielne `provenance` analizy
(profile/`model_version`/niepewność składników). Jedna analiza ma jedną decyzję;
identyczny retry i nowy key z identyczną decyzją zachowują wynik/UUID-y.
Zmieniona decyzja po confirmation daje 409. Provenance przechowuj lokalnie obok
wpisu; nie dopisuj go do starego payloadu sync-v1 ani nie przedstawiaj jako
weryfikacji katalogu.

Po odpowiedzi confirm O1 w jednej transakcji Room zapisuje szablony, ich powiązanie
z analizą/provenance i operacje outbox w pierwotnym zakresie konta. Ponowna obsługa
tej samej decyzji nie nadaje nowych UUID-ów ani kolejnych operacji. Następnie
standardowy sync E4, z aktualnym checkpointem/epoką, wysyła upsert
`product_draft` dla brakujących szkiców oraz `meal`, wykorzystując zwrócone ID
i stare payloady. Nowe encje używają `base_revision=0` zgodnie z sync-v1.
Room/outbox i potwierdzenia standardowego sync pozostają źródłem stanu dziennika.

Create, worker i confirm nie tworzą `Meal` ani `ProductDraft` na serwerze.
Odbiór O1 powinien wykazać: przed standardowym push liczba meals/drafts nie wzrasta;
po push i jego lost-ACK retry powstaje dokładnie jeden właściwy posiłek i każdy
zamierzony szkic. Późniejsza publikacja produktu jest osobną decyzją E6 z
`source_kind="ai"`; samo confirm nie publikuje go i nie daje statusu verified.

## Błędy i wymagany odbiór O1

Chronione odpowiedzi oraz błędy mają `Cache-Control: no-store` i zwykły `ApiError`
z `code/message/details/request_id`. Backend nie zwraca raw obrazu/provider response.

| Status / przykładowy code | Obsługa Androida |
|---|---|
| 401 | Odnowienie logowania w zakresie pierwotnego konta; zachowaj niewysłane dane. |
| 403/404 | Zatrzymaj działanie dla odmówionego/niedostępnego zasobu. |
| 409 `sync_epoch_changed`, `analysis_context_changed` | Uzgodnij bieżący kontekst; zachowaj lokalne potwierdzone wpisy i outbox, bez automatycznego odtwarzania starej operacji. |
| 409 `idempotency_key_reused`, `proposal_revision_conflict`, `photo_catalog_choice_changed` | Odróżnij zmieniony request od konfliktu propozycji/katalogu; pobierz stan i uzyskaj jawną decyzję. |
| 409 `ai_operation_busy` | Współbieżny identyczny create: zachowaj ten sam key/body i użyj ograniczonego retry. |
| 413 / 422 | Popraw rozmiar/obraz/JSON/zgodę; nie zmieniaj automatycznie notice lub providera w już zatwierdzonym zleceniu. |
| 429 | Respektuj `Retry-After`; lokalny wpis nadal działa. Dotyczy również aktywnego joba i puli receipts. |
| 503 | Funkcja zdjęcia chwilowo niedostępna; zachowaj ręczny fallback. |

Schema dokumentuje także 410 dla niedostępnego obrazu. Nie istnieje publiczny GET
zdjęcia; GET analizy zwraca stan/propozycję, a czas usunięcia zdjęcia nie usuwa
automatycznie zatwierdzonego lokalnego posiłku. Serwerowy TTL nie jest instrukcją
usunięcia niewysłanego lokalnego dziennika.

Osobny odbiór O1 obejmuje zgodę i odmowy, multipart z image przed metadata,
wybór/correction, null/Decimal/g/ml, cancel w obu kolejnościach dispatch,
lost ACK/replay/Room/outbox/standard sync, zmianę konta w trakcie requestu,
stare ref/epokę i działający ręczny zapis przy każdym błędzie AI.
E7-R, rzeczywisty APK/KO-31 i wydanie pozostają osobnymi dowodami; mock nie jest
pomiarem trafności Gemini. Wymagania free-only/EOG określa
[11.6](../../WYMAGANIA_PROJEKTOWE.md#116-gemini-darmowe-api-limity-i-trwałość-zadań).
