# Raport backendu analizy zdjęć E7 - osoba 2

## Ponowny odbiór — poprawka P2 metadanych REST

11 października 2026. Koordynator na `9b2fb7e` / base `75c4414` odtworzył jeden
P2: poprawny food JSON/STOP/usage był odrzucany po dodaniu opcjonalnej
thoughtSignature lub Candidate tokenCount/finishMessage/avgLogprobs. Własna
reprodukcja przed zmianą: baseline ok, signature parts_invalid, pozostałe i combo
result_invalid. Po ograniczonej naprawie wszystkie sześć wariantów ma ok i
identyczną propozycję/usage. To syntetyczne próby, bez wywołania modelu Google.

Naprawa waliduje tylko potrzebne metadane otoczki REST i pomija je, zanim wynik
przejdzie przez process boundary. Strict food JSON i usageMetadata pozostają
dotychczasową normą. Rozmiary/typy i datowane primary references są w
[profilu REST](REFERENCJE_GEMINI.md). Sygnatury/opisy/raw response nie są zapisywane.
Nie zmieniono modelu, SDK, migracji, API, sync, cleanup lub polityki rezerwacji.

Dowody autora tej poprawki:88 nowych unit parsera +85 wcześniejszych w właściwym
module =173 PASS; pełne1258 unit PASS. Nowe21 actual loopback REST/subprocess/PG
(7 dodatnich/14 odmów) PASS: count10240 i generation896 wyłącznie z usage,
1 count+1 generate bez retry, brak metadanych w DB/API/receipts/logs, brak Meal/Draft
przed explicit confirm→standard sync. Na utrwalonym `2646cf4` cała wcześniejsza
właściwa regresja E7 ma129 PG PASS (runtime/quota/process/maintenance/migration/
worker-login/acceptance),174,63s, bez skipów. Własny testowy PG zatrzymano.
Powtórek nie sumujemy. Dwa wcześniejsze
błędy own harnessu downstream (display oraz legalne matches.candidates) i długi
pytest ID przekraczający Windows environment limit są poprawione; nie były PASS.

Nowy [niezależny odbiór](RECENZJA_O2.md#nowy-odbiór-p2-otoczki-rest--source-2646cf4)
na `2646cf440182e2bdca769f61ff3acbd2c04c2f5a` / base `75c4414a1aab22094c9425fa3dda890782e92370`:
**9,3/10, zero otwartych istotnych P1/P2; zgłoszony P2 zamknięty**. Własne
1258 unit,116 parser oracles,13 real PG/fake REST oraz32 dostarczone PG/runtime
PASS bez skipów. Własny installed parser -I/smoke i127 exact package files PASS;
manifest266 `e9848d7393cc349991e8f045cc614a24db32004291a76dd8fd078e7a05f19fc9`.
Recenzent sam odtworzył przed/po także w realnym workerze, nie zmieniał kodu
i zatrzymał własne usługi. Poprzednia identyczna ocena9,3 i stare zielone CI nie
służą zamknięciu P2; zachowano je jako dowody historyczne.

Poprawka trafia do tego samego PR28 bez merge. Końcowy commit dokumentacji
nie zmienia executable tree odebranego źródła; aktualne final head/base oraz
rzeczywiste osiem wyników nowego CI są odczytywane osobno i publikowane
w opisie [PR28](https://github.com/Roseru/aplikacja-mobilna/pull/28). E7-O2 jest
zgłoszone do ponownego odbioru koordynatora. E7-R WAITING_EXTERNAL i działania
O1/O3 pozostają osobne; nie wykonano Google/key/corpus/billing/produkcji,
E8/E9 ani automatyzacji.

Zakres: E7-O2 z [mastera](../MASTER_PROMPT_E7.md), odczytanego w całości
z `485fb2e959f4d4b74548e6ac6ffe4e129cd5e68f`. Gałąź
`codex/backend-e7-analiza-zdjec`; własny managed worktree, [PR #28](https://github.com/Roseru/aplikacja-mobilna/pull/28).
Odebrane źródło: `9a7edcc95ae254cf6d1b59ca78add4c1a188ce75`, base
`75c4414a1aab22094c9425fa3dda890782e92370`; runtime identyczny z `b4d2780`.
Końcowy commit po tym odbiorze zmienia wyłącznie dokumentację. Jego exact head/base
i własne ostatnie osiem CI są zapisane w opisie PR oraz odpowiedzi wykonawcy.
**E7-O2 gotowe do osobnego odbioru koordynatora; PR pozostaje otwarty, bez merge.**
**E7-R: WAITING_EXTERNAL. Pełny E7 / APK / produkcja nie są zaliczone.**

## Dostarczony wynik

Pięć chronionych operacji AI: capabilities, jeden multipart create, własny poll,
jedna niezmienna confirm decision oraz cancel. Foto-zgoda jest osobnym rekordem
z DB time, notice/provider/this_photo i hash konkretnego obrazu. JWT/user,
active account/generation i sync_epoch poprzedzają hash/replay; auth jest ponownie
sprawdzany po body/staging. Admin/moderator nie omijają ownership.

Oryginał istnieje tylko w bounded pamięci, bez framework spool/Temp. Obraz
JPEG/PNG/WebP jest dekodowany, orientowany, spłaszczany na białe RGB i ponownie
kodowany JPEG bez metadanych; max wejście5 MiB, 4096/bok,16 mln px, wynik1600/bok.
Prywatny storage wymaga rzeczywistego POSIX mode/Windows DACL, chroni traversal,
symlink/reparse/hardlink. Fsync/rename i durable compensation poprzedzają DB acceptance.
Cleaner rechecks bieżący registry pod storage lock, zachowuje intent do unlink ACK;
startup/60 s, grace300 s, maxTTL24 h. Nie deklaruje fizycznego cleanup martwego hosta.

Durable job/phase/lease/fence i relacyjny limiter: jeden aktywny job/konto,
dwa fizyczne IO/środowisko, queue5 min, processing120 s, call45 s, generate≤2.
Commit marker poprzedza countTokens i generateContent. Crash po markerze daje
unknown bez resend. Subprocess i jego własny watchdog używają wspólnego hard deadline;
lease/cancel/purge nie zwalnia żywego permit. Dowód operatora jest trwałym hashem.

Provider mock jest jawny; Gemini REST adapter jest zaimplementowany bez SDK
i prawdziwego wywołania. Pinned prompt/schema/preparation/REST/model, bounded
JSON i ścisłe DTO odrzucają unknown fields, duplikaty, injection/control,
NaN/Infinity, zgadywaną density oraz niepoprawne usage. CountTokens używa tego
samego generation requestu; nie zmniejsza rezerwacji. Każde IO rezerwuje10240tokens.
Trusted usage rozlicza input≤8192 i text+thinking≤2048. Unknown/timeout/5xx nie ponawia;
retry wymaga pewnego pre-send lub potwierdzonego minute quotaId.

Pool provider/project/model/environment nie zależy od secret key. RPM/TPM
rolling60 s; RPD America/Los_Angeles/DST; photos10 i receipts1000/UTCday;
energy336 h jest wyłącznie wspólnym limiter interface, bez E9 API/business.
Restore trigger zamyka AI po zmianie sync_epoch; konserwatywne wznowienie dopiero
po336 h i fizycznym fencing, bez resetu liczników. Rutynowa zmiana środowiska
po disabled pool jest zablokowana. Brak/rozbieżna konfiguracja live zamyka AI.

Matching wywołuje wspólną normę E6 NFKC/casefold/whitespace, energy/density i
bounded indexed candidates; exact public refs pod catalog lock. Propozycja
wykorzystuje nutrition_v1/Decimal/null, do30 składników i uncertainty.
Confirm zawiera komplet starego Meal i0–30 ProductDraft templates, jawną korektę,
exact refs, UUID/revision i provenance. Nie tworzy Meal/Draft/Goal/katalogu.
Istniejący sync jest jedynym zapisem dziennika; E6 publication jest osobną decyzją.

## Migracja, zgodność i pakowanie

Nowa `0015_e7_ai`, dwanaście tabel i wersjonowane SQL resources; oryginalne
`0001–0014` pozostają niezmienione. Readiness wymaga nowego head. Przed migracją
minimalna bazowa rola AI: NOLOGIN/NOINHERIT, bez nadmiarowych ACL lub rodziców.
API i stary worker zachowują wcześniejszy zakres. Nowy AI LOGIN nie ma DML/DDL
ani prywatnego diary/catalog SELECT; job fence i token capability nie są jawnie czytelne.
Purge usuwa private content, owner bindings i zgody, zachowuje anonimowe quota
i cleanup intents. Niepusty downgrade odmawia atomowo zamiast skasować dowody.

Norma: [OpenAPI](../../backend/openapi.json) → generated
[ai.schema.json](../../contracts/schemas/ai.schema.json) → identyczny bundled
resource. Ścisłe valid/invalid przykłady w [registry](../../contracts/examples/index.json).
Stare domain/sync/nutrition/statistics pozostają normą. Pillow12.3.0 przypięte
w uv.lock, sprawdzone na primary release; nie dodano SDK/Gemini credentiala.
Wheel/sdist i installed `-I` zawierają prompt, schematy i codec.

## Faktyczne dowody autora

Wyniki bez skipów; powtórek nie sumujemy. Wszystkie zdjęcia i payloady poniżej
są syntetyczne. Fake HTTP oznacza rzeczywisty loopback/server/socket/subprocess,
nie kontakt Google. Większość testów HTTP używa kontrolowanego verifiera;
osobny Keycloak wskazany jawnie daje prawdziwe JWT/PKCE.

| Odbiór | Wynik |
|---|---|
| Pełne unit E0–E7, w tym140 codec/storage/multipart,115 provider,60 reference runner i25 LOGIN helper | 1170 PASS; własny tmp, 1 znane ostrzeżenie Starlette |
| Author acceptance: lost ACK, same/distinct-key race, purge podczas codec/staging, filesystem failure, zgody, foreign role, confirm→sync→E6 ai publication, bad AI config zachowuje diary ready | 17 PASS PG17/SCRAM/private storage |
| Quota/ACL: oba purpose, last-slot RPM/TPM/RPD races, UTC10/1000, rolling minute,336h, Pacific8dat/12DST, missing usage, raw DML denials, legacy isolation/token hash | 68 PASS real PG17/SCRAM |
| Process/crash: claim races, third IO, expired lease/stale fence, pre/post count/generate marker, HTTP acceptance, reply-before-commit, autonomous child watchdog/fencing | 13 PASS real PG/storage/HTTP/processes |
| Cały Keycloak/PKCE, w tym6 E7 actual access-token/ownership/no-user/ID-token cases | 28 PASS real Keycloak26.8/JDK25, własny H2 i PG17 |
| Migration: pełne wypełnione E4–E6 rowsets przez0014↔0015,4 durable guards i4 hostile MAINTAIN/SECURITY DEFINER ACL guards; wcześniejsza E6 DB regresja | 9 nowych +48 wcześniejszych PASS |
| Maintenance: TTL/unlink/ACK/grace/lock/purge z żywym IO, quiet retention i rzeczywisty dump/restore | 11 PASS real PG/storage/process/PG17 tools |
| Minimalny LOGIN provisioning, replay/rotation, szerokie role, raw ACL/column jobs/private/PUBLIC CONNECT, zachowany pool/unknown ledger | 11 PASS PG17/SCRAM;25 helper unit są już w1170 |
| Pełna author regresja PG E0–E7, maintenance/restore i LOGIN provision | run928 przypadków:926 PASS/2 harness FAIL; po uzupełnieniu pustej własnej calorie_app wszystkie13 provisioning PASS, w tym oba błędne IDs; nie sumujemy powtórek |
| E0 contracts / Ruff / diff-check / package resources | 89valid/32invalid/18scenarios/376links PASS na source9a7; Ruff251 PASS;127 exact source/wheel/sdist/installed files i38 locked runtime versions PASS |

Pierwszy pełny unit run miał190 fixture errors dostępu do systemowego pytest Temp;
nie zmieniono jego ACL, powtórka we własnym katalogu dała1170 PASS. Stare izolowane
klastry testowe wymagały nowej bazowej roli AI dla head0015; osobny author cluster
miał błędny LOGIN operatora zamiast NOLOGIN i został poprawiony wyłącznie lokalnie.
Nowa E6 publication assertion początkowo oczekiwała201 zamiast istniejącego200;
poprawiono test. Test TTL wykrył JSON null zamiast SQL NULL w terminalnej ścieżce;
runtime naprawiony, bez fałszywego przypisania unknown. Lokalny partial run nie jest PASS całości.

Pierwszy zdalny run38163918429:6jobs success, postgres8failed/915PASS i ci-required failure.
Stary Unicode rowset proof z granicy0013 porównywał nowe defaultAI tabele po head;
poprawiono jego zakres, zachowując cały osobny E7 graph proof. Fresh bootstrap
zostawiał PUBLIC CONNECT do calorie_test, więc minimalny helper prawidłowo odmówił
7 dodatnich prób. Odebrano PUBLIC w bootstrapie i dodano realny atomic PUBLIC CONNECT
regression; nie osłabiono helpera. Poprawki37PG oraz dodatkowe31PG ACL/runtime PASS
są właściwymi kontrolami, nie zamiennikiem następnego pełnego finalnego CI.

Finalny author fullPG na b4d nie miał błędu kodu: dwa testy E1 wymagały pustej
bazy o stałej nazwie calorie_app, której mój własny klaster nie miał. Uzupełniono
wyłącznie ten własny bootstrap;13 provisioning PASS. Jednostkowe1170 ponowione
na c091, a pełne single-run928 PG potwierdzają niezależny odbiór oraz CI źródła9a7.
Nie oznaczamy author runu926/2 jako pojedynczego928 PASS.

## Nieautor i CI

[RECENZJA_O2.md](RECENZJA_O2.md): **9,3/10, zero otwartych istotnych P1/P2**
na source9a7/base75c. Własny nieautor: pełne1170unit na c091 i25 właściwe delta,
pełne928 PG na b4d (identyczny backend9a7),28realOIDC na c091 (auth bez zmiany),
21 własnych probes na9a7 oraz dokładny fresh bootstrap/realCLI. Powtórek nie
sumuje; pierwszy błędny own harness jawnie opisany. Wcześniejsze P1/P2 zamknięte
rzeczywistymi własnymi barierami/SQL/HTTP/process/restore probes.

Manifest264 source plików:
`699ad0c6e645562de12aa51c0ecad47d169cbc50ed3abe16fe9068ed644a4c36`.
Prywatne probes: `3b214bfe30cae0bbf10a2054dca2c47f00fd087f307089802d83f912085f2941`.
127 exact package files/38locked runtime na b4d:
`8074bed77d00b474f3d517d7a2fbc8801257119aed3b4bc7c5f96281a8fdef70`.

[CI38165581472](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38165581472)
na9a7/base75c odczytane z rzeczywistych logs/jobs: **osiem success**, zero skipped.
1170unit,928PG,28Keycloak i21infra PASS; wheel/installed-I/Docker API smoke,
real PG export/offline import oraz lokalne HTTPS/down-up PASS. Jobs:
contracts, quality, postgres, keycloak-pkce, android-build, android-device,
local-integration, ci-required. Nowy commit dokumentacji otrzyma własne pełne CI;
ten wcześniejszy run potwierdza odebrany runtime, nie udaje kontroli przyszłego head.
PR pozostanie otwarty, bez merge/auto-merge.

## Granice i przekazanie

WF-09/UC photo: backend proposal/explicit confirm i fallback kontrakt dostarczony.
KO-10/21/28: transport/auth/idempotency/limits/cleanup/backend proof; KO-32:
oddzielny worker/physical permits/restore gate. WF-06 i30dni offline pozostają
na starym sync, chronione regresją. KO-09/13: brak→null, exact refs i snapshots.
KO-31, Room/outbox, prawdziwy APK i pełny fallback wymagają odbioru O1.

WebP nie ma uniwersalnego matematycznego proof końca entropy bitstream.
Codec odrzuca rozpoznane ZIP dual-format, outer trailing, błędne framing/decode
i animacje; inert excess wewnątrz zadeklarowanego chunku może być tolerowane przez
native decoder. Oryginał nie trafia do storage/provider; fresh JPEG usuwa payload
i metadata. Nie deklarujemy odrzucenia dowolnego możliwego polyglotu.

Live wymaga datowanych Free Tier/model/project/limits O3 i prawdziwego legalnego
corpus≥30 zgodnie z [E7-R](E7_R_MANIFEST.md). E7-O2/mock/codec tests nie zaliczają
accuracy ani EOG/produkcji. O3 mount/Windows ACL/backup exclusion/minutowy nadzór,
production restore/RPO/RTO oraz O1 APK są osobne. [Instrukcja O3](KONFIGURACJA_O3.md)
i [O1](INTEGRACJA_O1.md). Klucz nie trafia do repo/APK/CI, żadnego billing/contact.

Odczytano main `d7ac450`, następnie `75c4414` i O1 plan z PR22; retencja O3/PKCE overlay i
Android0.7.2/0.7.3 są zmianami zespołu. Główny E4 checkout oraz Random Data
pozostają nietknięte. Nie rozpoczęto E8/E9, nie włączono automatyzacji i nie wysłano
wiadomości koordynatorowi. Oba zwykłe merge zachowały wpisy wszystkich autorów.
Nowy plan E8 jest dokumentem zespołu, bez uruchomienia E8 przez wykonawcę E7.
Własny Keycloak/PG autora oraz oba PG/Keycloak nieautora zostały zatrzymane;
pozostają ignorowane prywatne dowody, bez publikacji logów, obrazów lub credentiali.
