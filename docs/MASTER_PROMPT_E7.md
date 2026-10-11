# Master prompt E7 — analiza zdjęć i trwałe zadania AI - osoba 2

Wersja 1, 11 października 2026 r. Wykonawca: OSOBA 2 / Agent 2. Główny czat: **GPT 6.1, reasoning xhigh**, zgodnie z bezpośrednim zleceniem właściciela. Priorytet: jakość, prywatność, zachowanie historii i czytelność kodu. Ten plik jest instrukcją; sam nie uruchamia pracy i nie jest dowodem implementacji. [Niezależny odbiór instrukcji](e7/RECENZJA_MASTER_E7.md): finalnie 9,3/9,3, zero otwartych istotnych P1/P2.

## 1. Rezultat i bramka startowa

Dostarcz **E7-O2**: działający backend zdjęcie → trwała analiza → zwalidowana propozycja i dopasowania → jawna korekta/confirm → szablon do lokalnego Room i istniejącego sync. W zakresie są rzeczywisty PostgreSQL, prywatny magazyn zdjęć, proces roboczy, mock oraz gotowy adapter Gemini, jeden relacyjny limiter dla E7/E9, retencja, purge, restore fences, kontrakty, testy i przekazanie O1/O3. Nie wystarcza szkic endpointów ani sam mock odpowiedzi bez worker/storage/PG.

Baza techniczna: odebrany E6 z [PR #20](https://github.com/Roseru/aplikacja-mobilna/pull/20), head `db1b33e3ed852b235db61952c1b227fbc84bc075`, scalony main `492811f998efe9256673a7c84bd942bcc07a9c9d`. Własny push [CI38141106156](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38141106156): osiem success, rzeczywiste 830 unit + 791 PG17 + 22 real Keycloak = 1643 PASS. Odebrano E6 matching/Unicode, publikację, kolejkę moderatora, migracje 0013/0014 i zgodność historii. Wiadomość startowa poda nowszy main zawierający ten master; zaczynaj z niego, nie z historycznej gałęzi E4.

Rozdziel trzy wyniki:

- **E7-O2**: kod backendu, realny PG/storage i testowany mock/provider transport, do osobnego odbioru koordynatora. Może powstać bez klucza i zdjęć referencyjnych.
- **E7-R**: rzeczywisty deweloperski Free Tier, potwierdzona konfiguracja O3 i minimum 30 opisanych zdjęć; osobno mierzone kryteria 11.6. Brak wejść oznacza `WAITING_EXTERNAL` tylko tego odbioru, z właścicielem i dowodem wznowienia.
- **Pełny E7 / wydanie**: dodatkowo O1 zdjęcie/zgoda/Room/outbox/fallback, O3 środowisko i restore oraz rozwiązana bramka regionu z 11.6. Mock, transport fixture i lokalne HTTPS nie zastępują tych dowodów.

WF-09, UC analizy/zatwierdzania zdjęcia, KO-10/21/28 oraz backendowa ochrona KO-32 są obowiązkowe. Zachowaj WF-06, 30 dni offline, KO-09/13, E2–E6, exact refs, statystyki i ręczny zapis. Pełny E5-C, official źródła oraz APK/KO-31/produkcja pozostają otwarte. Nie promuj danych testowych w official. Wykonawca nie scala PR, nie zaczyna E8/E9 i nie uruchamia automatyzacji.

## 2. Wejście, Git i organizacja czytelna dla ludzi

Przeczytaj AGENTS.md, WYMAGANIA_PROJEKTOWE.md (zwłaszcza WF-09, 11.2/11.3/11.6), ARCHITEKTURA, PLAN_PRAC, WORKFLOW, aktualny KOMUNIKACJA_AGENTOW, raport/przekazanie E6 i istniejące identity/diary/sync/catalog. Normatywne API pochodzi z FastAPI → backend/openapi.json. Design-v1 nie zawiera gotowej implementacji AI; obecnie nie ma modułów ai/jobs, workera ani konfiguracji Gemini. Tworzysz je w E7.

Sprawdź status, gałąź, remote, main, otwarte PR i nowe wpisy wpływające na O2. O1 planuje własne sesje/HTTP/Room/WorkManager; odczytaj jego aktualny plan/komunikację, nie przyjmuj samego planu za runtime. Nie przeglądaj niezwiązanych gałęzi i nie scalaj całej niescalonej pracy innego agenta. Zachowaj Random Data, .review-o2 i wcześniejsze niezatwierdzone pliki.

Odczytano związane prace zespołu: [PR #21 O3](https://github.com/Roseru/aplikacja-mobilna/pull/21), head `d6405ed9aaf3e0c8e240f420b66c5de6a66a1b36`, ma osobny godzinny proces retencji sync/read i status/permits; jest niescalony w tym punkcie. Nie jest kolejką AI ani minutowym cleanup zdjęć. Nie dubluj jego retencji, nie przejmuj całej gałęzi i nie zmieniaj jego zakresu bez potrzeby. Po dołączeniu nowego main zachowaj go; AI worker/cleanup mają odrębne odpowiedzialności. [PR #22 O1](https://github.com/Roseru/aplikacja-mobilna/pull/22) jest planem integracji; [PR #23 O1](https://github.com/Roseru/aplikacja-mobilna/pull/23) poprawia przewijanie/klawiaturę, bez OIDC/sync/E7. Te wskazania nie oznaczają odbioru lub merge cudzych PR.

Użyj własnego managed worktree z aktualnego main i gałęzi **codex/backend-e7-analiza-zdjec**. Preferuj odpowiedni własny checkout przed tworzeniem kolejnego. Nowy lokalny czat może wskazywać stary główny E4: odczytaj master przez `git show <SHA-ze-zlecenia>:docs/MASTER_PROMPT_E7.md`, pobierz refy i pracuj w izolacji. Nie przełączaj E4, checkoutu koordynatora ani innego wykonawcy. Jeden główny wykonawca O2; bazy, porty, procesy i fixture własne.

Proponowany podział odpowiedzialności:

```text
backend/src/calorie_app/
  worker.py                       # CLI, cykl życia, sygnały, sweep
  modules/jobs/
    models.py, repository.py, runner.py
  modules/ai/
    models.py, schemas.py, router.py
    service.py, repository.py
    food_analysis.py, validation.py
    quota.py, storage.py, idempotency.py
    prompts/                      # wersjonowany prompt i profil, bez sekretów
  integrations/gemini/
    protocol.py, mock.py, adapter.py
backend/migrations/versions/       # nowa migracja po 0014
backend/tests/unit/, integration/, keycloak/
contracts/schemas/, examples/e7/, test-vectors/
docs/e7/
```

Router sprawdza transport i auth, schema kontrakt, service przypadek użycia, repository SQL; commit należy do caller. Brak ukrytych commitów, drugiego backendu, gigantycznego pliku lub nowego brokera/Redis. Dopuszczalne połączenie małych modułów, jeżeli nazwy i odpowiedzialności pozostają jasne. Nową bibliotekę dekodowania obrazów przypnij w uv.lock po sprawdzeniu oficjalnej dokumentacji; nie dodawaj całego SDK tylko dla jednego REST call. Zmiany w istniejącym matching mają wydzielać wspólną funkcję, z regresją E6, nie budować drugą normę Unicode.

Przed runtime zapisz docs/e7/DECYZJE_V1.md i rzeczywiste przykłady kontraktu. Subagenci: medium dla ograniczonych fixture/kontraktów, high lub xhigh dla transakcji, bezpieczeństwa, storage i odbioru. Jeden właściciel pliku; nieautor nie recenzuje własnego modułu jako niezależnego. Główny czat zachowuje xhigh; obniżanie reasoning dotyczy świadomie wydzielonych podzadań, bez pomijania dowodów.

## 3. Jeden kontrakt przyjęcia zdjęcia

Podstawowe chronione operacje `/api/v1`:

| Operacja | Wynik |
|---|---|
| GET /ai/capabilities | provider mock/gemini, wersja notice, limity projektu aplikacji i dostępność; bez klucza, DSN i szczegółów konta technicznego |
| POST /ai/food-analyses | Jeden obraz + jawna zgoda; 202 z ID, rewizją, stanem, deadline i profilem |
| GET /ai/food-analyses/{id} | Własny stan, zwalidowana propozycja/dopasowania albo stabilny kod błędu |
| POST /ai/food-analyses/{id}/confirm | Utrwalenie jednej jawnej decyzji i stabilny szablon dla istniejącego sync |
| POST /ai/food-analyses/{id}/cancel | Cofnięcie zlecenia/zgody przed dalszym dispatch; idempotentny wynik |

Wybór v1: **jeden multipart/form-data** POST z dokładnie dwoma częściami: `metadata` jako JSON UTF-8 do 16 KiB i `image` jako jeden JPEG/PNG/WebP do 5 MiB. Całe body do 6 MiB, bounded streaming przed kosztownym parserem/dekodowaniem, limit części/nagłówków; brak równoległego upload URL/base64/Files endpointu. Nie ufaj Content-Length, nazwie pliku, rozszerzeniu ani MIME. Odrzuć dodatkowe części, duplicate JSON keys, niepoprawne UTF-8, depth >20, kompresję body i nieznane pola. Auth/aktywne konto/epoka są sprawdzane przed kosztownym przygotowaniem; nie trzymaj transakcji i account lock podczas dekodowania/IO. Przed końcowym zapisem ponownie sprawdź kontekst. Niedopuszczalny obraz nie tworzy joba ani nie zużywa dziennej analizy/provider quota.

Surowe body i oryginalny obraz pozostają wyłącznie w bounded pamięci (całość do 6 MiB). Nie używaj domyślnego multipart spool/UploadFile do systemowego Temp ani zapisu oryginału na dysk. Sprawdź pełne metadata, accepted, notice_version, provider i scope przed dekodowaniem i jakimkolwiek file IO; dotyczy także części image dostarczonej przed metadata. Brak prawidłowej zgody kończy request bez plików, joba i admission. Hash surowych bajtów i istniejący receipt sprawdź przed przygotowaniem/staging. Trwały replay nie tworzy pliku; współbieżne pierwsze przyjęcia tego samego operation key muszą być serializowane również na czas przygotowania, np. dedykowaną per-operation blokadą sesyjną, bez trzymania transakcji lub account lock podczas file IO. Nie blokuj globalnie całego konta przez upload; po disconnect/failure zwalniaj własny zasób przetwarzania i staging.

Metadata zawiera zgodę `accepted=true`, właściwy `notice_version`, wskazanego providera zgodnego z capabilities i zakres `this_photo`. Czas zgody ustala DB; zgoda jest powiązana z konkretną analizą i hashem przyjętego obrazu. Nie ma owner/role/status/model-overrides/API URL. Dotychczasowy UserConsent dotyczy rankingu i automatu energii; nie traktuj go jako zgody na zdjęcie i nie zmieniaj starego sync-v1 tylko dla nowej zgody.

Create/confirm/cancel wymagają UUID Idempotency-Key i X-Sync-Epoch z bootstrapu. Confirm/cancel mają właściwą oczekiwaną rewizję. Najpierw aktualny JWT/user, active account/generation i epoka, potem hash/replay, zasób i jego rewizja. Cudzy/nieistniejący zasób jednakowo404. Moderator/admin nie ma dostępu do cudzych zdjęć/propozycji. Dane mock są jawnie oznaczone mock i nie udają Gemini.

Create hash obejmuje metodę/path, semantyczne metadata i SHA-256 oryginalnych bajtów obrazu; przyjęty profil/model/preparation zapisuje się raz w analizie. Zmiana klucza API lub bieżącego profilu nie zmienia semantyki replay starego requestu. Identyczny create po lost ACK zwraca pierwotne ID bez drugiego joba, consent/admission/file lub provider call; inne body pod kluczem409. Receipt nie zawiera obrazu/raw provider response. Przy replay nie odtwarzaj usuniętego obrazu. Utrwal minimalne potwierdzenie/hash do purge, pełną odpowiedź minimum 60 dni, bounded cleanup jak w E6, bez resetu idempotencji. Dodatkowy limit nowych receipts E7:1000 / konto / dobę UTC, również trwałe odmowy; replay nie konsumuje puli. Nie osłabiaj istniejących receipts E3/E4/E6.

No-store dla chronionych odpowiedzi oraz błędów auth/parsera/middleware. Stabilne ApiError:401, 403, 404, 409, 410 dla niedostępnego wygasłego obrazu, 413, 422, 429 z Retry-After, 503; brak oczekiwanego500 i echo payloadów. Odpowiedź API do 1 MiB, maks. 30 składników; provider response również bounded przed pełnym JSON parse. Nie dodawaj publicznego endpointu zdjęć ani listingu katalogu plików.

## 4. Przygotowanie i prywatny storage

Zweryfikuj rzeczywisty format dekoderem, pojedynczą klatkę, brak animacji, poprawność całego pliku. Limit wejścia:5MiB, 4096px na bok, 16mln pikseli. Odrzuć decompression bomb, truncated/polyglot/format spoof i niedopuszczalne tryby. Zastosuj orientację EXIF, konwertuj do uzgodnionego RGB, skaluj dłuższy bok do 1600 px i ponownie zakoduj bez EXIF/GPS/XMP/ICC/comment/innych metadanych. Zapisz wersję tej deterministycznej procedury, wymiary i przygotowany hash; przygotowany plik również do 5 MiB. Przezroczystość spłaszcz na jawne białe tło. Użytkownikowy filename nie staje się ścieżką.

Obecna integracja O3 ma API z filesystem read-only i osobny publiczny storage katalogu. Nie wykorzystuj ich do zdjęć. E7 wymaga odrębnego, prywatnego writable photo root/mount dla API i AI workera; brak konfiguracji lub praw zamyka photo capabilities, ale nie health/ready dziennika. Nie włączaj zapisu do katalogu official ani systemowego Temp. O3 otrzymuje ten jawny wymagany mount i oddzielny harmonogram minutowy; obecny godzinny retention z PR21 go nie zastępuje.

Prywatny katalog wspólny API/worker, poza statycznym serwerem i backupami; losowe nazwy i ścisłe uprawnienia. DB ma metadane/hash/właściciela/TTL, nie BLOB zdjęcia. Brak URL fetch, symlink/reparse/path traversal. Użyj bezpiecznego tworzenia i otwierania plików, sprawdzaj docelowy root; właściwe ograniczenia uprawnień Windows/POSIX opisz i sprawdź, nie udawaj że samo chmod zapewnia ACL Windows. Żadnych zmian systemowego Temp/ACL lub katalogów innych czatów.

PG i filesystem nie mają wspólnego commit. Protokół v1: prywatny staging przygotowanego pliku → trwałe fsync/atomic rename w tym samym FS → transakcja acceptance z referencją do aktywnego obiektu/jobem/zgodą/receipt. Worker wybiera wyłącznie kompletny zaakceptowany obiekt. Przy odmowie/rollback usuń staging/niepowiązany plik; crash kompensuje bounded orphan sweep z grace i jawnym markowaniem aktywnej operacji, aby nie usunąć pliku transakcji w toku. Nie trzymaj transakcji ani blokad wierszy DB podczas file IO; dopuszczalna jest dedykowana sesyjna blokada operation key z rozdziału 3. Utrzymuj trwałe deletion intents/tombstones przed unlink; retry po braku pliku jest sukcesem. Nie kasuj intent przed potwierdzonym usunięciem.

Obraz usuń po zakończeniu analizy, również przy failed/unknown/cancel, najpóźniej 24 h od przyjęcia. Startup i cykliczny sweeper nadrabiają po awarii; harmonogram co minutę, bounded partie1–1000. O3 dostaje wymagany start sweep i wyłączenie zdjęć z backupów. Maksimum 24 h jest regułą naszej aplikacji: przy zatrzymanych wszystkich procesach fizyczne usunięcie wymaga działającego zewnętrznego nadzoru/cleanup O3; backend nie deklaruje magicznego usunięcia podczas awarii całego hosta. Po24h API/worker nigdy nie odczytuje/wysyła starego obrazu, nawet gdy cleanup jeszcze zalega.

Purge zachowuje trwały zamiar cleanup, ale usuwa prywatną treść/zgody/analizy/confirm receipts/owner bindings; po potwierdzonym unlink usuwa intent. Zachowane intent ma tylko nieosobowy losowy storage key, bez account UUID/issuer/sub/opisu. Testuj deleting/purge podczas przygotowania/upload/IO: brak odtworzenia pliku/zasobu po usunięciu. Przyjęcie zasobu musi commitować przed deleting albo odmówić z kompensacją.

## 5. Job, próby i fences

Publiczne stany robocze `queued/running/succeeded/failed`; claim/dispatch/retry to jawne fazy/próby w danych, nie ukryty in-memory workflow. Cancellation ma stabilny powód/stan decyzji; zakończony wynik można odrzucić bez nowego call. Job/analysis ma właściciela, generation, sync_epoch, rewizję, deadline kolejki, attempt count, next_attempt_at, lease_until i niepowtarzalny fence/lease ID. Profil model/prompt/schema/preparation i provider namespace są przypięte przy acceptance; worker nie przełącza go po deploy bez jawnego błędu.

Kolejność blokad: konto → sync counter, jeśli potrzebny → catalog, gdy potrzeba matching/confirm → wspólna AI pool/control → job/analysis → admission/reservation/receipt w deterministycznym porządku. Cleanup/purge/claim/finish stosują zgodną kolejność i nie blokują arbitralnie cudzych kont. Kandydat joba może być wybrany bounded SELECT bez locka; claim dopiero po account lock, warunkowo z recheck. Nie bierz job lock, potem account lock. Nie wywołuj Gemini ani filesystem przy otwartej transakcji. Dwa różne purpose dzielą tę samą pool.

Przepływ: bounded wybór → atomowe claim i walidacja aktywnego konta/epoki/deadline → atomowa rezerwacja limitów i commit durable `dispatch_started` → IO bez transakcji → warunkowy finish dla tego samego fence/generation/epoch. Stary worker nie zapisuje rezultatu po przejęciu, cancel/deleting lub restore. Wynik zapisuje się dopiero po ścisłej walidacji i matching; wszystkie terminalne ścieżki uruchamiają cleanup.

Deadline oczekiwania:5 min od acceptance; brak puli dobowej kończy zadanie, nie czeka do następnej doby. Maksymalnie 2 próby generateContent, każda do 45 s i całość do 120 s od rozpoczęcia obsługi. Licz pozostały deadline także podczas przygotowania/preflight/retry. Użyj faktycznego całkowitego timeout transportu i ograniczenia bajtów, nie tylko read timeout resetowanego kolejnymi chunkami lub timeout oczekiwania na wciąż żywy thread. Zakończenie własnego subprocess/transportu musi być potwierdzone. Graceful shutdown nie wysyła następnej próby.

Crash przed durable dispatch pozwala na bezpieczny reclaim. Crash po markerze, także przed faktycznym send, po przyjęciu przez provider lub po odpowiedzi przed DB commit: `provider_result_unknown`, bez automatycznego powtórzenia tej próby. Nie obiecuj exactly-once Gemini. Timeout/network/5xx po możliwym wysłaniu są unknown, nie retry. Nowa analiza wymaga nowej świadomej zgody/zlecenia.

Ponów tylko pewny błąd przed wysłaniem lub jednoznaczny chwilowy429: nowa rezerwacja, respektowanie Retry-After, opóźnienie i wszystkie deadlines. Nieznany/dobowy429 kończy zadanie; nie klasyfikuj po swobodnym tekście błędu. Jeżeli dla generateContent nie ma wiarygodnego sygnału typu limitu, kończ kontrolowanym quota błędem. Odrzucone/unknown próby nie oddają niepewnej puli.

Najwyżej1 aktywny job na konto i2 outbound calls na środowisko, wymuszone relacyjnie między procesami. **Wygaśnięcie job lease/failed/cancel nie zwalnia samo miejsca fizycznie żywego IO.** Slot ma trwałe powiązanie z próbą; zwolnienie następuje po potwierdzonym zakończeniu transportu/procesu. Reclaim po awarii wymaga dowodu zakończenia poprzedniego IO lub fail-closed/O3 odcięcia starego workera. Opisz konkretny mechanizm permits, heartbeat/hard timeout i odzyskania, potwierdź realnymi dwoma/trzema procesami. Bez dowodu bezpiecznej rezygnacji pozostaw slot zamknięty; ręczny wpis dalej działa. Nie deklaruj kontroli czasu wewnętrznego przetwarzania u Google po zerwaniu połączenia.

Cofnięcie zgody przed kwalifikacją dispatch blokuje call. Po durable kwalifikacji żądanie mogło już zostać wysłane; cancel odcina następne próby i zapis/odczyt nowej propozycji, inicjuje cleanup. Nie gwarantuj cofnięcia już wysłanego zdjęcia. Testuj obie kolejności kwalifikacja/cancel, bez trzymania account lock przez sieć.

## 6. Jeden limiter Free Tier dla E7 i przyszłego E9

Interfejs z `purpose=food_photo|energy_adjustment`, już testowany dla obu purpose w PG; nie wdrażaj endpointów/reguł biznesowych E9. Admission:10 nowych poprawnie przyjętych zdjęć/konto/dobę DB UTC; jedna analiza energii na ruchome14×24h w przyszłej ścieżce. Identyczny retry nie jest nowym admission, druga provider próba jest nową rezerwacją. 1 active/konto obejmuje oba rodzaje zadań (purpose). Wszystkie time windows oparte o clock_timestamp DB; bez zegara klienta.

Pool scope: stabilny provider/project/model oraz wskazane środowisko; nigdy API-key hash jako identyfikator puli. Rotacja klucza, restart, cleanup, zmiana workerów i purge właściciela nie resetują zużycia. Tylko jedno środowisko ma prawdziwy klucz projektu; pozostałe mock. RPM/TPM/RPD i dodatkowe wymagane wymiary pochodzą z datowanego potwierdzenia O3 dla konkretnego projektu/modelu. Brak/niepoprawna konfiguracja zamyka live adapter; nie wpisuj domyślnej „darmowej liczby zapytań”. Mock ma własny jawny namespace i testowe wartości, nie udaje dostępności Free Tier.

RPM i TPM: konserwatywne ruchome okno60s, indexed/bounded agregacja i rezerwacje pod wspólną blokadą; fixed tumbling minute nie może dopuścić podwójnego burst na granicy. RPD: dzień `America/Los_Angeles`, rzeczywiste DST, nie UTC. Wspólny slot/rezerwacja przed każdym outbound call, również referencyjnym testem i countTokens. Lokalny limiter nie gwarantuje przyjęcia przez dostawcę.

Budżet generateContent: wejście≤8192, wyjście ≤2048 łącznie z reasoning. Rezerwuj pełny dopuszczalny budżet przed send; prawidłowe usage może zmniejszyć rezerwację, unknown/missing/untrusted usage jej nie zwalnia. Nie używaj float. Jeżeli potrzebny countTokens do potwierdzenia wejścia, v1 najwyżej jeden preflight na analizę, też przez limiter i zgodę, przed generateContent; wszystkie calls mieszczą się w 120 s. Nie jest trzecią próbą generacji ani boczną drogą darmowego ruchu. Brak dowodu budżetu wejścia kończy próbę, nie wysyła niekontrolowanego promptu. CountTokens rezerwuje konserwatywną pulę; udokumentuj wymiar jego zużycia na podstawie primary docs, nie zakładaj wyłączenia z limitów.

Usage zapisuje in/out/thoughts według dokumentowanej semantyki, bez podwójnego doliczenia thinking. Malformed/ujemny/większy od dostępnego limitu usage daje kontrolowany stan i konserwatywne wykorzystanie; nie staje się ujemnym licznikiem. Nie przechowuj USD/billing ledgeru. Pool reservations nie są kasowane kaskadą z kontem: zachowaj anonimowe attempt/window agregaty do końca okien, usuń account identifiers i prywatne treści przy purge. Minimalny operator nie ma zwykłego „reset quotas”.

Restore: nowe sync_epoch odcina stare create/confirm/cancel, również pod nowym kluczem. AI control związane z epoką zamyka dispatch gdy cofnięty stan nie jest uzgodniony; stare jobs nie są ponownie wysyłane. Live wymaga odcięcia starych procesów i datowanego operator reconciliation lub wygaśnięcia wszystkich niepewnych okien (także Pacific/user14dni, jeżeli dotyczą pool). Nie wyliczaj wykorzystywanej puli tylko z cofniętego backupu. Domyślnie live paused po restore; ograniczenie dotyczy również przeniesienia środowiska z kluczem. CLI odblokowania wymaga jawnego current epoch i dowodu O3, nie resetu counterów; dokładną bezpieczną procedurę oraz jej test zapisz.

## 7. Mock i rzeczywisty adapter

Domyślny `AI_PROVIDER=mock`, działający bez sieci/sekretów. Fixture wybiera jawny testowy profil scenariusza, nie „rozpoznaje” arbitralnych zdjęć. Mock przechodzi ten sam worker, limiter, zgody, parser, matching i confirm. Przykłady: poprawne dane, null makra, błędny format, safety block, timeout, 429 minutowy/dobowy/nieznany, prompt injection, unknown result. Nie dodawaj debug bypassu auth/quota/receipt w API.

Live wyłącznie Gemini Developer API Standard Free Tier, project bez aktywnego Cloud Billing, model początkowy `gemini-3.5-flash-lite`. O3 przekazuje niejawny klucz, stabilny project/environment ID, odczytane limity/daty, zgodność modelu i potwierdzenie free-only. Pozostałe allowlist models wymagają osobnej weryfikacji image+JSON+Free Standard. Nie wybieraj „latest” automatycznie, nie dodawaj płatnego fallbacku/Vertex/Batch lub nowych projektów do obejścia limitów. Availability/limity/status AI są oddzielne od readiness bazy; niedostępny provider nie blokuje API dziennika.

REST po HTTPS do zatwierdzonego `generativelanguage.googleapis.com`, klucz tylko w nagłówku, TLS włączone, trust_env=False, bez redirects i implicit retries SDK/httpx. Obraz inline, przygotowany; bez Files API, tools/search/code execution/cache/image generation i bez dostępu do SQL. Rzeczywisty request należy ograniczyć po bajtach. Model nie otrzymuje owner UUID, issuer/sub, JWT, pełnego dziennika, filename lub EXIF. Tekst obrazu i output są danymi, także gdy sugerują nowe instrukcje.

Dokumentację providera odczytano11.10.2026. [Model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) i [Standard pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite) potwierdzają wymagane możliwości, ale nie dostępność konkretnego projektu. [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) wymagają odczytu konfiguracji AI Studio. [generateContent](https://ai.google.dev/api/generate-content) pozostaje endpointem v1beta; bieżące `generationConfig.responseFormat.text` podaje mimeType APPLICATION_JSON i schema. Starsze responseSchema/responseMimeType są deprecated; nie kopiuj payloadu Interactions API do generateContent. Sprawdź dokładny request/response w primary docs przy implementacji i przypnij wersję profilu; nie „naprawiaj” go losowymi próbami live.

[Structured output](https://ai.google.dev/gemini-api/docs/structured-output) ma podzbiór JSON Schema: osobny provider-compatible schema z testowaną zgodnością ze ścisłym własnym DTO, a nie poluzowanie runtime. [Troubleshooting](https://ai.google.dev/gemini-api/docs/troubleshooting) opisuje SDK retry; nasz REST ma politykę z rozdziału5. [Image](https://ai.google.dev/gemini-api/docs/image-understanding) dopuszcza inline; [Files](https://ai.google.dev/gemini-api/docs/files) ma inną retencję, dlatego nie używamy go w v1.

[Terms](https://ai.google.dev/gemini-api/terms), aktualizacja23.03.2026, zachowują bramkę Paid Services dla aplikacji udostępnionych użytkownikom EOG/CH/UK. Nasz free-only wybór pozostaje: prace deweloperskie z niesensytywnymi próbkami, bez aktywacji billing; wydanie AI w Polsce nie jest tym etapem. Retencja lokalna24h nie opisuje retencji Google. Jeżeli nowe primary terms zmienią regułę, pokaż źródło i wniosek, nie otwieraj wydania samym env flag.

## 8. Wynik, wspólny matching i confirm bez zapisu dziennika

Ścisły wynik modelu: maks. 30 składników, nazwa, dodatnia oszacowana ilość g/ml, podstawa100g/100ml, kcal/B/T/W jako kanoniczne Decimal strings lub null, ewentualna udokumentowana gęstość/źródło, znana/unknown tożsamość zgodna z E6, niepewność i ograniczone uwagi. Numer identyfikatora składnika nadaje backend; model nie nadaje ProductRef/account/verified/official/SQL. Limity tekstów/list jak E6, wartości/granice jak domena, brak NaN/Infinity/duplikatów/nieznanych pól/jednostek. Empty/no-food, błędny JSON, safety block, brak candidate, MAX_TOKENS, nieoczekiwane parts i niekompletny wynik kończą kontrolowanym błędem. Raw odpowiedź nie trafia do DB/logów; zachowaj ograniczone statusy/modelVersion/usage/wersje profilu.

Gęstość wymyślona przez model nie jest udokumentowanym źródłem. Propozycja bez wiarygodnego potwierdzenia ma density=null i zgodną podstawę/ilość; użytkownik może przy confirm dodać jawne potwierdzone rho wraz ze źródłem. Sam opis AI nie zezwala na automatyczną konwersję g↔ml.

Brak makr pozostaje null, nie zero. Totale oblicza nutrition_v1, nie tekst modelu. Ilość ml nie wymaga gęstości, ale konwersja g↔ml jej wymaga. Nie rób automatycznej weryfikacji od popularności/pewności modelu. Wszystkie ilości/kcal są propozycją do korekty przez człowieka.

Wydziel wewnętrzne dopasowanie zwalidowanego transient MatchingIdentity z obecnych high_candidates/manual_candidates; brak wymogu utworzenia ProductDraft na serwerze. Ta sama NFKC/casefold/ws, Decimal10%, g/ml i indexed SQL; bounded najwyżej20 kandydatów/składnik. Zwróć exact refs, powody, missing/truncated i jawną niepewność. Żadnego automatycznego merge/publish lub nadpisywania katalogu. Nie zmieniaj kontraktu POST /products/matches wymagającego własnego szkicu. Wynik propozycji nie rezerwuje produktu; confirm ponownie sprawdza wybrane publiczne wersje pod catalog lock.

Confirm jest explicit request z expected proposal revision i kompletną zatwierdzoną korektą, lokalnym meal UUID/item UUID oraz ewentualnymi lokalnymi draft UUID. Nie wystarcza accept=true. Weryfikuje owner/context, ścisły istniejący Meal/ProductDraft payload oraz wybory publicznych exact refs; cel, jeżeli wskazany, ma być własny. Hidden/stale/merged wybór409 z informacją do ponownego wyboru; brak silent redirect. Klient może zrezygnować z katalogu i zatwierdzić własny szacunek, z product=null. Selected ref nie nadpisuje snapshotu; wybrane katalogowe makra mają catalog_snapshot, świadomie zatwierdzone oszacowanie AI ai_estimate. Nie oznaczaj oszacowania jako catalog_snapshot tylko dlatego, że istnieje referencja.

Zapisuje wyłącznie decyzję/binding oraz zatwierdzony szablon i provenance analizy. **Nigdy INSERT/UPDATE Meal, MealItem, ProductDraft, GoalVersion ani publicznego produktu.** Wynik: ścisły stary Meal payload, 0–30 ścisłych ProductDraft templates, oddzielne provenance (analysis ID, provider/model/prompt/schema/preparation, niepewność); nie dopisuj tych pól do sync-v1. Szacunek w ProductDraft ma jawny source_description AI. Serwer nie obiecuje kryptograficznego wymuszenia późniejszej deklaracji source_kind przez klienta; E6 jest świadomą osobną publikacją użytkownika. O1 przechowuje provenance zgodnie ze swoim modelem i nie myli go z weryfikacją katalogu.

One confirmed decision/analysis: identyczny retry lub nowy klucz z identyczną decyzją zwraca ten sam wynik; zmiana po confirmation409, bez kolejnych szablonów/efektów. IDs są stabilne w całym replay. O1 najpierw zapisuje wynik w Room+outbox atomowo; istniejący sync E4 tworzy posiłek i brakujące szkice, a opcjonalna późniejsza publikacja E6 używa source_kind ai. Test end-to-end: przed sync liczba meals/drafts nie zmienia się; po standardowym push dokładnie jeden meal/draft i prawidłowe źródło/Decimal/null. Odrzucenie analizy nie blokuje samodzielnego manualnego wpisu.

## 9. Migracje, ACL i usuwanie

Nowa migracja po0014, bez zmian0001–0014. Relacyjne account-owned analyses/jobs/consents/decisions/receipts/admission oraz niezależne pool/control/attempt reservations i file cleanup intents. FK/unique/check wymuszają własność, dodatnie/range wartości, stan/fences i brak drugiego aktywnego joba. Tabele JSON tylko dla bounded zwalidowanej treści, nie całej niekontrolowanej odpowiedzi ani obrazu. Nowe readiness rozpoznaje aktualny head; bez zmian health/live znaczenia.

API, worker, migrator i deletion operator nadal odrębne. API nie ma DDL/worker dispatch/zmiany pool zużycia, worker nie dostaje zapisu do prywatnego dziennika/katalogu. Wąskie kwalifikowane SQL functions tam, gdzie potrzebne; zamknięty search_path, REVOKE PUBLIC EXECUTE oraz skuteczne table/column grants nawet po hostile defaults. Cleanup/deletion nie jest rolą admina API. Nie poszerzaj praw modułów E2–E6, nie osłabiaj regresji sekretu operatora/SCRAM/logów.

Rozszerz ręczny purge obecnego grafu przez nową migrację. Zachowaj cudzy/shared katalog, historię i anonimowe globalne reservations; po usunięciu konta żaden issuer/sub/account UUID/private opis/zdjęcie/treść analizy nie pozostaje w audycie/provider ledger. Unlink ma trwały anonimowy intent, więc awaria po purge nie zostawia nieposprzątanego zdjęcia. Konkurencyjna finalizacja nie wskrzesza joba/account/pliku.

Pusty downgrade zachowuje pełny wypełniony E4–E6 graf. Przy trwałych E7 analizach/zgodach/decisions/minimal receipts/zużyciu provider/cleanup intents odmów atomowo przed DDL, chyba że wybrana konkretna migracja jawnie zachowuje je bezstratnie. V1 wybiera odmowę, bez ręcznego DROP lub fałszywego „bezstratnego rollbacku”. O3 dostaje rollout/worker stop/storage/backup/restore, migrację i maintenance commands z owner/context/bounded batches.

## 10. Weryfikacja implementacji

Nieautor sam wykonuje istotny nowy zakres, we własnym zamrożonym checkoutcie/PG/storage, oraz własne adversarial probes z niezależnymi oczekiwaniami. Minimum 9/10, zero otwartych istotnych P1/P2. Autor nie recenzuje własnego modułu jako niezależny. Nie sumuj powtórek do fikcyjnej liczby przypadków; oddziel local/nieauthor/CI/live/reference/O1/O3. Poprawiaj ten sam PR; po nowym head odbieraj zmieniony zakres i właściwą regresję.

Wymagane dowody:

1. Unit i ścisłe schematy: poprawne/nieczytelne/no-food, null/zero, 30/31 składników, Unicode, NaN/Infinity, nieznane jednostki/extra/duplicate JSON, wynik truncated/safety/nieoczekiwane parts, prompt injection. Deterministyczne wyliczenia sprawdzane niezależnym oracle nutrition_v1.
2. HTTP A/B i real Keycloak: brak tokenu, zły issuer/aud/signature, user/admin/moderator/wrong client, foreign404, bieżąca generation/deleting/epoch przed replay i provider; no-store także malformed multipart/oversize. Bez nowego własnego pełnego provider harness nie nazywaj mock JWT realnym OIDC.
3. Realny PG/SCRAM i storage: create/confirm/cancel lost ACK, inne body/key/current profile, jedna zgoda/admission/job/decision, brak zdjęcia w receipt, cleanup odpowiedzi bez powtórzenia joba/IO. Refusal receipt bounded, pełna pula nie jest obchodzona przez klucz.
4. Bariery i realne co najmniej dwa procesy worker: claim tego samego joba, 1 aktywny job/konto, 2 outbound calls/środowisko, trzecia próba blokowana; stale worker po lease expiry nie commit ani dalszy send; nie zwalniaj permitu podczas jego żywego transportu.
5. Kill/restart na granicach before marker/after marker/after provider acceptance/after response before DBcommit; osobny lokalny HTTP fake provider liczy faktyczne połączenia. Unknown nie jest resend, jedynie pre-dispatch retry jest dozwolone. DB fences i hardtimeout sprawdzone poza samym in-memory mockiem.
6. Limiter PG: ostatnie RPM/TPM/RPD pod współbieżnością, granica 60 s, PDT/PST midnight i DST, doba użytkownika UTC, moving 14 days E9interface, retry429/unknown/daily, missing usage, rotation/restart/purge bez resetu, oba rodzaje zadań (purpose) w jednej pool. CountTokens/reference calls nie obchodzą ledgeru.
7. Restore własnego starszego zrzutu z nową epoką: brak automatycznego provider replay nawet pod nowym kluczem, gate closed, niepewna pula niedostępna, fizycznie odcięte dawne własne procesy. Nie zmieniaj cudzej bazy/epoki.
8a. Multipart z image przed metadata, absent/false/stale notice/niezgodny provider lub scope, disconnect oraz create replay/race. Instrumentacja parsera i procesu potwierdza brak jakiegokolwiek spool oryginału w systemowym Temp; odrzucona zgoda/trwały replay nie tworzą również przygotowanego pliku. Nie zmieniaj ani nie skanuj cudzych plików Temp dla tej próby.
8. Realne JPEG/PNG/WebP+GPS/EXIF/orientation/alpha, bomba dekompresyjna/animation/truncated/MIME spoof i limity części/body; sanitized bytes bez metadanych. Crash before/after file activation/DBcommit i deletion ACK; orphan grace, symlink/reparse/traversal, TTL i restart i brak odczytu wygasłego obrazu. Brak payloadów, sekretów i zdjęć w captured logs.
9. Confirm→lokalnytemplate→standard sync→E6publication: same exact refs/stare rowsets/history, unicode matching, densityRequired/null, stale/hidden/merged choices; zero nowych meals/drafts przed sync i dokładnie jeden po retry sync. Ręczny zapis nadal działa podczas wszystkich błędów AI.
10. Fresh/upgrade z 0014 z całym pełnym grafem/pusty downgrade/re-up i atomowe refusal ze wszystkimi E7 artefaktami; raw DML/column DDL/PUBLIC privileges, purge przy inflight/niepewnychrezerwacjach, hashy źródeł/bajty/sealed historia bez zmian.
11. Pełna właściwa regresja E0–E6, bundlowane schematy/generowany OpenAPI, kontrakty i WindowsCRLF, Ruff/format, uv.lock, wheel/sdist oraz installed-I smoke poza checkoutem z nowymi prompts/resources/Pillow. Nowe CI nie wywołuje prawdziwego Google i nie wymaga live sekretu; zachowaj wszystkie8 obowiązkowych jobów Android/Keycloak/local integration. Żadnych skips jako PASS.

Testowe obrazy dla codec/storage mogą być syntetycznymi fixture, nie dowodem trafności Gemini. Nie wprowadzaj fixed sleep do dowodów wyścigów; bariery/zegar DB/twarde warunki. Przy błędzie własnego runnera odróżnij infrastrukturę od regresji, popraw tylko harness i raportuj uczciwie.

## 11. E7-R i zewnętrzne wejścia

Jeżeli w autoryzowanym środowisku istnieją kompletne datowane wejścia O3 oraz zatwierdzone niesensytywne próbki, E7-R może wykonać rzeczywiste deweloperskie analizy **przez to API/worker i wspólną pool**, w dostępnych darmowych limitach. Nie wysyłaj prywatnych zdjęć znalezionych w Downloads/Random Data ani załączników bez ich konkretnej zgody do tego użycia. Nie odczytuj/drukuj klucza w celu raportu. Nie kontaktuj dostawcy i nie aktywuj billing.

W przeciwnym razie ukończ pełny E7-O2, przygotuj odtwarzalny runner i manifest E7-R, wpisz „nie wykonano / WAITING_EXTERNAL” z właścicielem, brakującym wejściem i dowodem wznowienia. Nie zatrzymuj niezależnego backendu tylko z powodu braku API-key/O1APK/publicHTTPS. Koordynator decyduje o następnej pracy po osobnym odbiorze; nie twórz zastępczego watchera.

Minimum 30 opisanych zdjęć: produkty, dania mieszane, racje i nieczytelne ujęcia. Manifest opisuje hash, legalne źródło/zgodę, czytelność, referencyjne główne składniki i kryterium identyfikacji; model nie tworzy ground truth. Rozkład v1:8 produktów, 8 dań mieszanych, 10 ujęć racji/składników, 4 nieczytelne; ważniejszy jest jawny pełny przekrój niż sztuczne powielanie. 100% błędnych struktur blokuje walidacja, 100% przypadków zachowuje ręczny wpis; ≥90% czytelnych zdjęć identyfikuje główne składniki listy referencyjnej. Raport ma numerator/denominator i per-case wyniki, nie wyłącznie średnią. Masa i kcal pozostają szacunkiem.

Wynik E7-R przypnij do model ID/modelVersion, prompt/schema/preparation i generacji; istotna zmiana profilu wymaga nowego testu. Niespełnienie kryterium: popraw prompt lub jawnie wybierz inny dostępny Free Standard model, ponów na tym samym udokumentowanym zestawie przez limiter. Nie „zaliczaj” rozpoznawania mockiem ani wygenerowanym ground truth. Rzeczywisty dev PASS nadal nie otwiera wydania w EOG.

## 12. Dostawa i zakończenie

docs/e7: RAPORT_E7.md, RECENZJA_O2.md, DECYZJE_V1.md, INTEGRACJA_O1.md, KONFIGURACJA_O3.md, REFERENCJE_GEMINI.md i opis/manifest testów E7-R. Pierwsze nagłówki dokumentów O2 kończą się `- osoba 2`. Zdjęcia/logi/buildy/cache/sekrety pozostają poza Git; wersjonuj potrzebne legalne codec fixture tylko po świadomym przeglądzie. Wspólne źródła w Random Data zachowaj. Jedyny dziennik to KOMUNIKACJA_AGENTOW, bez drugiej tablicy.

O1: jedno multipart, notice/provider, stany/poll/deadline/cancel, rewizje propozycji i ręczny fallback, 30 składników, null/ai_estimate/exact refs, szablony confirm i provenance, idempotency/lost ACK/X-Sync-Epoch, Room+outbox przed sync. Zdjęcie lokalne jest decyzją O1; obraz serwerowy nie jest jego backupem. Prawdziwy APK/KO-31 ma osobny odbiór.

O3: konfiguracja bez sekretów, projekt/model Free Tier, limity z datą i jedno live środowisko, migracje/ACL/readiness/worker CLI, pool namespace, hard timeouts/permits, fences/restore gates, prywatny storage/ACL/backup exclusion, cleanup przy starcie i co minutę, schedule/monitoring/rollout i proceduryoperatora. Live-key nie trafia do APK/CI/repo. Samo ready API nie dowodzi AI capabilities ani produkcyjnego restore.

Git: sprawdzony rezultat → `agent 2: <konkretny wynik>` commit z lokalną tożsamością → push własnej gałęzi → jeden PR do main → faktyczne CI finalnego head/base i nieauthorreview. Przed commit diff/diff-check; przed końcowym push aktualny main/komunikacja, zwykły merge na czystym checkoutcie, bez force-push lub nadpisania cudzych wpisów. Aktualizuj końcowy opis PR, dołącz PR do czatu. Publikuj ważne zweryfikowane kroki; nie uznawaj lokalnego PASS za zdalny CI.

Końcowy raport ma branch/head/base/PR, migrację/kontrakty, konkretne WF/KO części O2, osobne wyniki local/nieauthor/CI/E7-R, limity i źródła, cleanup własnych procesów. Werdykt E7-O2 gotowe do osobnego odbioru lub konkretna blokada. E7-R i pełny E7 pozostają jawnie oddzielone. Nie scalałeś PR, nie rozpocząłeś E8/E9, nie zmieniłeś E4 checkoutu i nie uruchomiłeś automatyzacji. Koordynator `01a12156-2312-7c43-aedc-1858e782e5fb` odbierze wynik; zakończ własny czat, bez niepotrzebnej wiadomości do innego czatu.

Bezpośrednia autoryzacja: bieżące ludzkie polecenie koordynatora „scal do main, napisz master prompt 7 i w nowym czacie niech się on wykona na gpt 6.1 xhigh”. Wcześniejszy łańcuch i workflow pozostają, lecz automatyzacje są wyłączone na późniejsze polecenie użytkownika. Nowe zlecenie E7 nie jest zgodą na ponowne włączenie harmonogramu, płatne usługi, kontakt z dostawcą lub produkcyjne wdrożenie.
