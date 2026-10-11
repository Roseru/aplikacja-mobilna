# Profil REST Gemini i dowody transportu E7 - osoba 2

Odczyt primary documentation: 11 października 2026. Profil:
`gemini-rest-v1beta-2026-10-11`, model `gemini-3.5-flash-lite`,
prompt `food-photo-prompt-v1`, schema `food-photo-schema-v1`.
To gotowy adapter E7-O2; nie wykonano prawdziwych wywołań ani E7-R.

## Źródła i przyjęte znaczenie

| Primary source | Wniosek dla tego profilu |
|---|---|
| [Model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) | Stable ID obsługuje wejście obrazu, tekstowe wyjście, structured output i thinking. Karta modelu nie potwierdza dostępności projektu O3. |
| [Standard pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite) | Standard input/output, także thinking, mają Free Tier. Nie używamy Batch, Flex, Priority, grounding lub paid fallback. Nie aktywowano billing. |
| [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) | RPM, wejściowe TPM i RPD są odrębne; limity dotyczą projektu, a RPD resetuje się o północy Pacific. Konkretne wartości i dodatkowe wymiary wymagają datowanego odczytu AI Studio O3. |
| [generateContent REST](https://ai.google.dev/api/generate-content) | Endpoint `POST /v1beta/models/{model}:generateContent`; aktualna konfiguracja JSON to `generationConfig.responseFormat.text` z `mimeType=APPLICATION_JSON` i `schema`. Nie kopiujemy pól Interactions API. |
| [Structured output](https://ai.google.dev/gemini-api/docs/structured-output) | Obsługiwany podzbiór JSON Schema ma obiekty, required/additionalProperties, enum, nullable types i bounded arrays. Osobny provider schema prowadzi model; runtime nadal egzekwuje E6, Decimal, teksty i zgodność stanów. |
| [Image understanding](https://ai.google.dev/gemini-api/docs/image-understanding) | Przygotowany JPEG jest przekazywany przez inlineData. Bez Files API, nazwy pliku, EXIF, URL fetch, właściciela/JWT i pełnego dziennika. |
| [CountTokens REST](https://ai.google.dev/api/tokens) | `generateContentRequest` obejmuje prompt i sterowanie modelu; jest wykluczający wobec osobnego contents/model body. Preflight liczy ten sam pełny request, który potem trafia do generation. |
| [Generate Content thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking) | Udokumentowany limit wyjścia obejmuje myśli i widoczny tekst. Flash-Lite obsługuje minimal thinking; profil ustawia MINIMAL i nie zwraca thought parts. |
| [Google RPC error details](https://github.com/googleapis/googleapis/blob/master/google/rpc/error_details.proto) | QuotaFailure ma machine quotaId/metric/dimensions; RetryInfo zawiera retryDelay. Swobodny description/message nie określa rodzaju limitu. |
| [Terms](https://ai.google.dev/gemini-api/terms) | Wydanie klienta użytkownikom EOG/CH/UK wymaga Paid Services. Free-only prace deweloperskie nie otwierają wydania AI w Polsce. Lokalna retencja 24 h nie opisuje retencji Google. |

## Budżet i rozliczanie bez podwójnego thinking

`countTokens` jest najwyżej jednym preflightem na analizę, przez wspólny worker,
zgodę, trwały dispatch marker, permit oraz pool. `token_count <= 8192` jest
dowodem ograniczenia wejścia, a nie dowodem rzeczywistego zużycia quota samego
preflightu. Brak lub błędny count kończy analizę przed generowaniem.

Request ustawia `maxOutputTokens=2048`, `thinkingLevel=MINIMAL`,
`includeThoughts=false` i Standard. Generacja ma pojedynczego candidate.
Sprawdzamy `promptTokenCount <= 8192`,
`candidatesTokenCount + thoughtsTokenCount <= 2048` oraz
`totalTokenCount = promptTokenCount + candidatesTokenCount + thoughtsTokenCount`.
`output_tokens` oznacza wyłącznie candidates; `thoughts_tokens` jest osobne.
Brak pola thoughts oznacza zero. Nie doliczamy thinking ponownie do total.
Malformed, ujemne, boolean, niespójne lub nadmierne usage kończy wynik kodem
`provider_usage_invalid`; missing usage nie daje rabatu rezerwacji.

Normatywny [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
opisuje TPM jako input tokens. Własna aplikacja świadomie rezerwuje
konserwatywnie **10240 tokenów i jedno żądanie przed każdym outbound call**,
także countTokens. Odczytane dokumenty nie obiecują wyłączenia countTokens
z wszystkich limitów projektu ani nie definiują dla niego generation usage.
Nie traktujemy `totalTokens` odpowiedzi preflightu jako refundacji zużycia.
Ta konserwatywna polityka aplikacji może ograniczyć dostępność wcześniej niż
Google, lecz nie tworzy obejścia puli. Inne wymagane wymiary O3 muszą zamknąć
live do czasu ich jawnej obsługi.

## Błędy, proces i sekrety

### Opcjonalne metadane otoczki REST — poprawka po odbiorze koordynatora

Ponowny odczyt 11 października 2026: [Part/Candidate](https://ai.google.dev/api/generate-content)
definiuje `thoughtSignature` jako nieprzezroczyste bytes/base64 oraz `tokenCount`,
`finishMessage`, `avgLogprobs` jako metadane kandydata. [Thought signatures](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures#signatures-in-non-functioncall-parts)
mogą wystąpić przy końcowym tekście bez functionCall. Nie są treścią jedzenia ani
zgodą na rozpoczęcie kolejnej tury. E7 nie zachowuje i nie odsyła tych danych.

Lokalny profil odpowiedzi waliduje, a następnie pomija dokładnie te pola:

| Pole | Typ i granica aplikacji |
|---|---|
| `Part.thoughtSignature` | String base64 do 65536 ASCII/wire bytes; standard lub URL-safe, z/bez poprawnego paddingu i z zerowymi niewykorzystanymi bitami. Bez mieszania alfabetów. Pusty string koduje empty bytes i jest pomijany; jawny null odrzucony. |
| `Candidate.tokenCount` | JSON integer, bez bool/coercion, 0..10240. Granica profilu nie jest limitem Google; pole nie zastępuje usageMetadata i nie daje refundacji. |
| `Candidate.finishMessage` | UTF-8 string do 4096 bytes, po dotychczasowej walidacji stringów/control characters. Nie jest przekazywany dalej. |
| `Candidate.avgLogprobs` | Skończony JSON number, bez bool/coercion, od ujemnej granicy binary64 do0. Nie uczestniczy w obliczeniach ani rozliczeniu. |

[ProtoJSON bytes](https://protobuf.dev/programming-guides/json/#representation-of-each-type)
dopuszcza oba alfabety base64 oraz opcjonalny padding. Podane caps są jawnie
lokalne, nie przypisujemy ich dokumentacji dostawcy. `thought=false` jako poprawny
boolean przy jedynej końcowej części text jest pomijany; `thought=true` oraz
inne typy nadal odrzucane. Function/tool/image/code parts, podział odpowiedzi,
safety/MAX_TOKENS i nieznane pola nadal nie są dopuszczone. Strict food JSON,
wersje modelu/prompt/schema oraz rozliczenie usageMetadata pozostają bez zmian.

Walidacja odbywa się w child parserze. Do ProviderOutcome trafiają tylko food,
dotychczasowe usage/modelVersion i kod; signature/opis/auxiliary counters/raw
response nie trafiają do DB, receipt, API ani logów. Nie dodano SDK, multi-turn
lub nowego modelu. Syntetyczny fake REST/PG jest dowodem E7-O2, nie E7-R.

REST ma HTTPS do dokładnego `generativelanguage.googleapis.com`, TLS włączone,
`trust_env=False`, `retries=0`, brak redirects oraz klucz wyłącznie w nagłówku.
Request jest bounded do 8 MiB, przygotowany obraz do 5 MiB, odpowiedź do 1 MiB
przed parsowaniem, wewnętrzny wynik do 512 KiB. Żadnego zapisu obrazu/raw
odpowiedzi w adapterze. Do parenta wraca wyłącznie ścisły bounded envelope.

Parent przekazuje image/config, także klucz, przez stdin osobnego procesu Python;
argv zawiera tylko nazwę modułu. Child nie dostaje innych DB/JWT/cloud sekretów
ze środowiska; jego stderr jest odłączony i logowanie wyłączone. Parent
`communicate(timeout)` przy timeout wykonuje `kill`, `communicate`, `wait`
przed oddaniem wyniku. Bounded stdin zawiera absolutny host-monotonic deadline
ustalony na początku execute. Child w małym stdlib-only bootstrap uruchamia
daemon watchdog `Timer(os._exit(124))` przed importem HTTPX/Pydantic/providera;
nie zmienia deadline po importach lub otrzymaniu kolejnego chunka. Pozostały
czas ogranicza także socket timeout. Watchdog działa po zabiciu parenta i
kończy fizyczny proces/IO. Serialization/spawn/import/IO korzystają z jednej
granicy, a wygasły deadline odmawia provider IO.
Proces nie robi automatycznych ponowień. Root worker zajmuje i zwalnia trwały
permit po potwierdzonym zakończeniu; śmierć parenta nie jest podstawą do
automatycznego zwolnienia osieroconego permitu. O3 musi odciąć stare procesy
i jawnie uzgodnić stan przed jego ponownym użyciem.

ConnectError/ConnectTimeout jest pewnym błędem przed wysłaniem. Timeout,
pozostały network error, crash lub 5xx po możliwym send daje
`provider_result_unknown`, bez resend. HTTP 429 bez wiarygodnego rozpoznanego
machine sygnału kończy `ai_quota_exhausted` / `unknown`. Domyślne
`quota_windows` jest puste; nie wpisujemy zgadywanych quotaId. O3 może dostarczyć
potwierdzoną mapę dokładnych quotaId dla tego projektu/modelu. Minutowy retry
wymaga rozpoznania każdego QuotaFailure, zgodnego metric/model oraz bounded
Retry-After/RetryInfo; dobowe lub mieszane z dobowym wyczerpanie jest terminalne.
Tekst błędu nigdy nie uruchamia retry. Root ponowienie rezerwuje osobno i
respektuje pozostały deadline oraz cancellation/fences.

## Ścisły wynik i wykonane dowody

DTO dziedziczy CatalogDTO i używa QuantityDTO, NutritionDTO, IdentityDTO E6.
1–30 składników, dodatnia ilość g/ml, taka sama podstawa, Decimal strings/null,
null-only density, low/medium/high, do 5 notes/składnik i 10 overall.
Model nie nadaje żadnych backend/account/product/source/verification IDs.
Brak jedzenia, safety, MAX_TOKENS, nieznany finishReason, brak/multiple candidate,
thought/function/image/split parts, unknown fields, duplicate keys, Unicode/NUL,
NaN/Infinity i depth >20 są kontrolowanymi błędami. Tekst instrukcji ze zdjęcia
pozostaje inert data; nie uruchamia narzędzi lub SQL. Totale oblicza nutrition_v1
poza providerem. Potwierdzenie człowieka pozostaje wymagane.

Lokalnie: **115 provider unit/transport tests PASS**, Ruff check/format PASS.
Testy obejmują realne lokalne HTTP przez rzeczywisty child proces, dokładną
liczbę połączeń, pojedyncze 503/429 bez retry, redirect rejection, bounded body,
trickle oraz potwierdzone zakończenie po timeout. Osobny test faktycznie zabija
żywy własny parent po potwierdzeniu HTTP acceptance, obserwuje dokładny child
przez Windows process handle / Linux pidfd i potwierdza jego autonomiczne
zakończenie w przekazanym deadline, zamknięcie połączenia i brak resend.
Wygasły deadline przed provider importem również nie wykonuje IO.
Mock jest jawnie wybranym
scenariuszem serwera, z syntetycznym preflight 512 i modelVersion mock.
Internal fixture adapter dopuszcza wyłącznie dokładny `http://127.0.0.1:port`
przy `environment=test` i `test_fixture_adapter=true`; create API nie przyjmuje
takiej konfiguracji. To dowody E7-O2, bez pomiaru trafności modelu, PG integracji,
CI lub niezależnego review. **E7-R: nie wykonano / WAITING_EXTERNAL** — wejścia
O3 i zatwierdzony corpus 30 zdjęć oraz osobny raport są nadal wymagane.
