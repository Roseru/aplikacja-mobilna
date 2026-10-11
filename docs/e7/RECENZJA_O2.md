# Niezależny odbiór backendu E7-O2 - osoba 2
**Aktualizacja zakresu:** historyczna ocena 9,3/10 poniżej nie obejmowała poprawnych opcjonalnych metadanych REST i nie zamykała P2 zgłoszonego później przez koordynatora. Nowy, odrębny odbiór źródła 2646cf4 znajduje się na końcu dokumentu.

11 października 2026 r. Recenzent: niezależny nieautor implementacji E7.
Werdykt: **9,3/10; zero otwartych istotnych P1/P2. E7-O2 gotowe do osobnego odbioru koordynatora.**
Ocena dotyczy backendu, a nie E7-R, APK, wdrożenia lub pełnego wydania.
Zakres normatywny określa [master E7](../MASTER_PROMPT_E7.md).

## Źródło i niezależność

Dostarczana gałąź: codex/backend-e7-analiza-zdjec, [PR #28](https://github.com/Roseru/aplikacja-mobilna/pull/28).
Końcowy sprawdzony source binding: 9a7edcc95ae254cf6d1b59ca78add4c1a188ce75;
baza 75c4414a1aab22094c9425fa3dda890782e92370.
Własny managed checkout recenzenta był zamrożony, bez edycji runtime lub testów autora.

Odbiór wykonałem samodzielnie na własnym PostgreSQL 17/SCRAM, prywatnym storage
z rzeczywistym Windows DACL, osobnych procesach i loopback HTTP oraz własnym
Keycloak 26.8.0 z repozytoryjnego development harnessu. Nie korzystałem z bazy,
storage lub procesów autora ani koordynatora. Próbki były syntetyczne; nie wysyłano
zdjęć do Google. Keycloak jest rzeczywistym IdP, a development harness nie stanowi
odbioru jego produkcyjnego magazynu lub restore.

Zmiana c091c5a → b4d2780 obejmowała precondition ACL, kontrolę MAINTAIN w CLI,
fresh bootstrap i właściwe testy/dokumenty. b4d2780 → 9a7edcc zmienia wyłącznie
wspólne dokumenty zespołu; porównanie zakresu backend/kontrakty/infra jest puste.

Manifest 264 śledzonych plików runtime, migracji, testów, kontraktów, lockfile,
narzędzia referencyjnego i lokalnej infrastruktury: SHA-256
699ad0c6e645562de12aa51c0ecad47d169cbc50ed3abe16fe9068ed644a4c36.
Manifest dla wcześniejszego c091c5a: SHA-256
228f02893e172469fd60114a1839abc17d6ced11136ac91dafee2e86e589da08.
Prywatne probes końcowe: SHA-256
3b214bfe30cae0bbf10a2054dca2c47f00fd087f307089802d83f912085f2941.
Logi, zrzuty, poświadczenia, środowiska i obrazy pozostają poza Git.

## Faktycznie wykonane kontrole

| Zakres | Wynik i source binding |
|---|---|
| Pełne unit | 1170 PASS na c091c5a; 25 właściwych unit provisioningu ponownie na b4d2780 |
| Pełne integration PG17 | 928 PASS na b4d2780, 904,05 s; źródła identyczne z końcowym 9a7edcc |
| Real Keycloak / PKCE / E7 | 28 PASS na własnym IdP i PG, c091c5a; zakres auth/E7 HTTP nie zmienił się |
| Własne adversarial probes | 21 PASS na 9a7edcc, 25,60 s; wcześniejsze 15 są podzbiorem |
| Dokładny fresh bootstrap | 1 własny scenariusz PASS: SQL init-db.sh przez psql → migracja 0015 → minimalny SCRAM LOGIN → real worker CLI |
| Jakość / kontrakty | Ruff PASS; format 251 plików PASS; E0 89 valid / 32 invalid / 18 scenarios oraz 374 lokalne linki na b4d2780 |
| Pakiet | Wheel/sdist PASS; 127 plików runtime identycznych bajtowo ze źródłem; locked install oraz installed -I smoke poza checkoutem PASS |

Nie było skipów. Powtórek i nakładających się zakresów nie sumuję.
Pełne PG obejmuje nowy E7 oraz właściwą regresję E0–E6: migracje, całe dawne grafy,
historię, standard sync, ACL, concurrency, actual worker processes i dump/restore.

Pierwszy własny pełny PG run na c091c5a zakończył się 801 PASS / 11 FAIL / 111 ERROR,
więc nie jest zaliczony. Jedna odmowa dotyczyła potwierdzonej starej listy tabel E6
poprawionej przez autora. Pozostałe wynikały z mojego niepełnego harnessu: brak
ścieżek PG17 CLI/sekretu legacy workera, wymaganych pustych baz i zbędny własny
grant CONNECT do bazowej roli AI. Poprawiłem wyłącznie prywatne środowisko,
zachowałem pierwszy log i wykonałem cały właściwy run ponownie. Jeden własny
test połączenia wymagał korekty oracle: psycopg nie dostarcza SQLSTATE dla tej
odmowy startowej; potwierdziłem efektywny brak CONNECT i rzeczywistą odmowę.

## Zamknięte istotne uwagi i własne oczekiwania

- **P1 cleanup race:** bariery zatrzymały create po staging i sweep po odczycie
  intentów. Acceptance usunęło intent i zwolniło lock, zanim cleaner kontynuował.
  Aktualny recheck po locku zachował zaakceptowane bajty i queued job.
- **P2 COMMIT ACK:** awaria przed oraz po rzeczywistym COMMIT zachowała plik.
  Przy braku zapisu durable intent umożliwił unlink; przy zapisie replay zwrócił
  jeden job bez ponownego codec/staging.
- **P2 fazy/żywe IO:** ponowny preflight callback po rozpoczętej generacji nie
  cofnął fazy; drugi dispatch, finish podczas żywego IO i zwolnienie cudzym
  tokenem zostały odrzucone. Opaque fences i hash tokenu nie udostępniają
  aktywnych capabilities nowemu workerowi.
- **P2 minimalne ACL:** własne upgrade probes obejmowały direct/column/PUBLIC
  grants, LOGIN, MAINTAIN i SECURITY DEFINER EXECUTE. Odmowa nastąpiła przed DDL;
  head, lista tabel i wcześniejsza funkcja purge pozostały zachowane.
  Rzeczywisty CLI odrzucił MAINTAIN przyznane loginowi lub PUBLIC, bez dispatch.
- **P2 namespace/CONNECT:** disabled stara pool nie umożliwiła nowego środowiska
  tego samego projektu. PUBLIC CONNECT do własnej dodatkowej bazy odmówiło
  provisioningu atomowo; po odebraniu grantu minimalny LOGIN działał wyłącznie
  we właściwej bazie, bez odczytu fence.
- **Deadline i restore:** własny transport child bez watchdogu rodzica zakończył
  trickling HTTP przy absolutnym deadline i zamknął socket, bez kolejnego call.
  Rzeczywisty zrzut sprzed dwóch późniejszych mock calls odtworzył pusty ledger,
  ale nowa epoka nadal zamknęła oba purpose, odmówiła wcześniejszego resume
  i odcięła wysłanie starego joba.

Pełne testy potwierdzają też zgodę przed przygotowaniem, brak spoola oryginału,
JWT/context przed replay, cancel/purge fences, compensation/deletion intents,
TTL, rolling RPM/TPM, Pacific RPD/DST, UTC admission i 336 h energy interface,
null/Decimal, exact refs, korektę oraz confirm → standard sync bez wcześniejszego
zapisu Meal/ProductDraft. Zachowano prawa legacy workera i retencję O3.

## Granice dowodu

Własne VP8 i VP8L probes potwierdziły identyczny fresh JPEG po usunięciu inert
excess bytes oraz odmowę rzeczywistego drugiego kontenera ZIP. Nie deklaruję
uniwersalnego exact-bitstream-end proof dla WebP ani odrzucenia wszystkich
dowolnych inert bajtów w declared entropy chunk. Oryginał pozostaje w pamięci;
do storage/provider trafia świeżo zakodowany obraz bez metadanych.

E7-R pozostaje **WAITING_EXTERNAL**: wymagane datowane free-only/model/project/limits
O3 oraz zatwierdzony corpus minimum 30 zdjęć. Mock i loopback REST nie potwierdzają
trafności Gemini ani publicznego wydania w EOG. Room/outbox/fallback/APK O1,
produkcyjny mount/cleanup/backup exclusion/restore O3, pełne E5-C i KO-31 pozostają
osobnymi odbiorami.

Nie odczytywałem ani nie zatwierdzałem końcowego CI/merge PR. Ten raport jest dowodem
własnego odbioru technicznego; exact head/base i zdalne kontrole potwierdza wykonawca
oraz koordynator. Nie scalałem PR, nie rozpocząłem E8/E9 i nie uruchamiałem automatyzacji.
Własne Keycloak, oba klastry PG i procesy prób zostały zatrzymane. Przed zapisem
tego raportu tracked diff był pusty; jedyna zmiana recenzenta to ten dokument.

## Nowy odbiór P2 otoczki REST — source 2646cf4

11 października 2026 r. Nowa ocena niezależnego nieautora: **9,3/10; zero otwartych
istotnych P1/P2 w odebranym backendzie E7-O2. Zgłoszony P2 parsera zamknięty.**
Wynik wynika z poniższej nowej reprodukcji i testów, a nie z przeniesienia starej
oceny. Odbiór koordynatora oraz kontrole zdalne końcowego head pozostają osobne.

### Dokładne źródła i zakres zmiany

Sprawdzony zamrożony commit: **2646cf440182e2bdca769f61ff3acbd2c04c2f5a**;
baza **75c4414a1aab22094c9425fa3dda890782e92370**; ta sama gałąź
codex/backend-e7-analiza-zdjec / [PR #28](https://github.com/Roseru/aplikacja-mobilna/pull/28).
Własny checkout był detached na tym commicie. Odczytano raport koordynatora,
aktualny profil REST, master i komunikację, również O1-014 z 42763f8 bez merge.

Porównanie z poprzednim 9b2fb7e741c8c833f210a42de276c30364229076 obejmuje sześć
plików: parser, dwa nowe pliki testów i trzy dokumenty. Jedyną zmianą runtime
jest protocol.py. Migracje, SQL/ACL, transport, limity, food schema, HTTP API
oraz autoryzacja pozostają bajtowo niezmienione. Historyczne pełne 928 PG,
28 real OIDC i wcześniejsze probes są wcześniejszym dowodem tych zakresów;
nie przedstawiam ich jako nowego pełnego uruchomienia na 2646cf4.

Nowe próby wykonałem osobiście na własnym PG17/SCRAM, prywatnym storage,
loopback REST i rzeczywistych procesach transportu. Nie używałem usług autora,
Google ani obrazów użytkowników. Nie zmieniałem runtime lub testów autora.
Własne niezależne oracles znajdują się poza Git; jedyną śledzoną zmianą recenzenta
jest ten dokument.

### Reprodukcja przed zmianą i wynik po zmianie

Na dokładnym 9b2fb7e baseline z poprawnym food, STOP i usage zwracał ok.
Dodanie samego thoughtSignature zwracało provider_parts_invalid; tokenCount,
finishMessage, avgLogprobs oddzielnie oraz kombinacja zwracały
provider_result_invalid. Własna realna próba PG/REST na tym źródle również
odtworzyła failed analysis zamiast poprawnej propozycji: **1 FAIL, 12 deselected**
w uruchomionym oracle akceptacji. Jest to dowód usterki przed poprawką, nie PASS.
Hash starego parsera: d48e0faaeb0fcf035989ede858b33d561106ab928273af6741b4d7aca849cc80.

Na nowym źródle wszystkie 16 kombinacji czterech opcjonalnych pól dały identyczny
food i usage jak baseline. Pojedynczy countTokens i generateContent zostały
zachowane, bez retry. Auxiliary tokenCount 0 lub 10240 nie zastąpił trusted
usageMetadata 128 + 64 + 16 = 208. Bez usage i przy odmowie pozostała
konserwatywna rezerwacja 10240; nie pojawił się zwrot limitu za te metadane.

| Nowy zakres, dokładne 2646cf4 | Faktyczny wynik |
|---|---|
| Pełne unit backendu | 1258 PASS, 75,48 s |
| Własne niezależne parser oracles | 116 PASS, 0,48 s |
| Własne PG/storage/fake REST oracles | 13 PASS, 38,87 s |
| Dostarczone nowe metadata PG i pełne runtime confirm | 21 + 11 = 32 PASS w jednym run, 89,11 s |
| Jakość i kontrakty | Ruff PASS, format 253 plików PASS; E0 89 valid / 32 invalid / 18 scenarios / 384 lokalne linki; diff-check PASS |
| Pakiet i instalacja | Wheel/sdist: 127 plików runtime identycznych ze źródłem; installed parser -I oraz installed smoke poza checkoutem PASS |

Nowe wykonane zakresy mają zero skipów. Nie sumuję nakładających się testów
ani nie zaliczam reprodukcji sprzed poprawki. Jedynym ostrzeżeniem pytest była
istniejąca deprecacja Starlette/httpx. Przy końcowym skrypcie installed pierwsza
próba zapisu miała błędny względny katalog; parser nie został wtedy uruchomiony.
Po wskazaniu własnej bezwzględnej ścieżki właściwy isolated parser zakończył się PASS.

### Adwersaria i brak wycieku

Własne oracles obejmowały standard i URL base64, padding oraz brak paddingu,
empty bytes, granicę 64 KiB encoded, złe pad bits, mieszane alfabety, format,
typy oraz rozmiary. Sprawdzono tokenCount jako ścisły int 0..10240,
finishMessage jako UTF-8 do 4096 bajtów oraz skończone avgLogprobs od
-binary64max do 0. Bool, null, nieprawidłowe typy i przekroczenia zostały
odrzucone; jawne thought=false przyjęte, thought=true lub inne typy odrzucone.

Unknown fields nadal odmówione na poziomie response/candidate/content/part
oraz wewnątrz food/item, także gdy mają nazwy nowych metadanych. Pozostały
odmowy function/tool/image/file/code, split parts, safety, truncation,
niepoprawnego food/usage, duplikatów JSON, głębokości i rozmiaru. Podpisy są
opaque bytes: parser sprawdza wyłącznie kodowanie i limit, nie interpretuje
ich treści i nie przenosi ich do własnego wyniku.

Unikalne canaries podpisu i finishMessage nie wystąpiły w wyniku IPC, API,
receipts, właściwych tabelach DB ani przechwyconych logach/stdout/stderr.
W realnych próbach po zakończeniu nie pozostał plik zdjęcia ani physical permit.
Replay create receipt zachował jeden job bez powtórnego codec/staging/provider.
Confirm i standard sync w 32 dostarczonych testach zachowały poprzedni kontrakt;
metadane nie tworzą Meal/ProductDraft przed standard sync.

Weryfikacja opierała się na pierwotnej dokumentacji
[GenerateContent/Part/Candidate](https://ai.google.dev/api/generate-content),
[podpisów w częściach tekstowych](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures#signatures-in-non-functioncall-parts)
i [kodowania bytes w ProtoJSON](https://protobuf.dev/programming-guides/json/).
Obecne null pozostaje świadomie odrzucone przez udokumentowany ścisły profil E7;
pola te nie rozszerzają schematu food ani nie stają się podstawą księgowania.

### Manifest i zamknięcie usług

Nowy manifest **266 śledzonych plików** obejmuje runtime, migracje, testy,
pyproject/uv.lock, smoke/OpenAPI, kontrakty, lokalną infrastrukturę i narzędzie
referencyjne. SHA-256: **e9848d7393cc349991e8f045cc614a24db32004291a76dd8fd078e7a05f19fc9**.
Nowy parser SHA-256: **6ff61bd944655bb7fbf788c2b3c56668b885e2fca0b7590504ac3ccd8955135d**.
Własne parser probes: **caf4f0860d58eb30c2fc2990d28c5e3d64c60e680cb3678d77ce18d8b949d33f**;
własne PG probes: **7639c7bc8e8b5860b8ab8de42e521c7c4b4698e431d30fab7c4627794eac2734**.
Manifest, logi, oracles, wcześniejsza recenzja/diff i poświadczenia pozostają prywatne.

Własny PG15687 został zatrzymany przez pg_ctl po sprawdzeniu, że data directory
leży wyłącznie w prywatnym katalogu recenzenta. Zweryfikowano zamknięcie własnych
portów 15687/15787/18687/19687; wcześniejsze Keycloak i fresh-bootstrap PG nie
były uruchamiane ponownie. Serwery REST i dzieci transportu zostały zamknięte
przez teardown prób. Nie zatrzymywano cudzych procesów.

Nowy wynik zamyka wskazane P2 otoczki REST w technicznym odbiorze nieautora.
Nie stanowi potwierdzenia nowego zdalnego CI, publikacji, merge, jakości modelu
ani pełnego E7-R. **E7-R pozostaje WAITING_EXTERNAL**; datowane wejścia O3,
corpus co najmniej 30 zdjęć oraz osobne odbiory O1/O3/E5-C/KO-31 pozostają
zgodnie z masterem. Historyczna granica WebP opisana wcześniej nie zmieniła się.
