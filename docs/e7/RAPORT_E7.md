# Raport backendu analizy zdjęć E7 - osoba 2

Zakres: E7-O2 z [mastera](../MASTER_PROMPT_E7.md), odczytanego w całości
z `485fb2e959f4d4b74548e6ac6ffe4e129cd5e68f`. Gałąź
`codex/backend-e7-analiza-zdjec`; własny managed worktree. Bieżący PR/head/base,
końcowy nieautor i osiem rzeczywistych CI zostaną związane z odbiorem poniżej.
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
| Migration: pełne wypełnione E4–E6 rowsets przez0014↔0015 i4 atomic durable E7 guards; wcześniejsza E6 DB regresja | 5 nowych +48 wcześniejszych PASS |
| Maintenance: TTL/unlink/ACK/grace/lock/purge z żywym IO, quiet retention i rzeczywisty dump/restore | 11 PASS real PG/storage/process/PG17 tools |
| Minimalny LOGIN provisioning, replay/rotation, szerokie role, raw ACL/column jobs/private CONNECT, zachowany pool/unknown ledger | 10 PASS PG17/SCRAM;25 helper unit są już w1170 |
| Pełna regresja PG E0–E7, maintenance/restore i LOGIN provision | trwa końcowy odbiór; nie zastępuj wcześniejszym partial PASS |
| E0 contracts / Ruff / diff-check / package resources | 89valid/32invalid/18scenarios/363links PASS; Ruff244 PASS;127 exact source/wheel/sdist/installed files i38 locked runtime versions PASS |

Pierwszy pełny unit run miał190 fixture errors dostępu do systemowego pytest Temp;
nie zmieniono jego ACL, powtórka we własnym katalogu dała1170 PASS. Stare izolowane
klastry testowe wymagały nowej bazowej roli AI dla head0015; osobny author cluster
miał błędny LOGIN operatora zamiast NOLOGIN i został poprawiony wyłącznie lokalnie.
Nowa E6 publication assertion początkowo oczekiwała201 zamiast istniejącego200;
poprawiono test. Test TTL wykrył JSON null zamiast SQL NULL w terminalnej ścieżce;
runtime naprawiony, bez fałszywego przypisania unknown. Lokalny partial run nie jest PASS całości.

## Nieautor i CI

[RECENZJA_O2.md](RECENZJA_O2.md) wiąże finalną ocenę≥9/10 i własne testy z SHA.
Wcześniejszy przegląd wykrył istotne cleanup/phase/ACL/pool relocation/watchdog/commit-ACK
uwagi; zostały poprawione i wymagają własnej reprodukcji recenzenta, nie samego odczytu.
Finalne osiem jobs: contracts, quality, postgres, keycloak-pkce, android-build,
android-device, local-integration, ci-required. Nie pominięto kontroli Androida/O3.
Push/local PASS nie oznacza CI PASS. PR pozostanie otwarty, bez merge/auto-merge.

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

Odczytano nowy main `d7ac450` i O1 plan z PR22; retencja O3/PKCE overlay i
Android0.7.2/0.7.3 są zmianami zespołu. Główny E4 checkout oraz Random Data
pozostają nietknięte. Nie rozpoczęto E8/E9, nie włączono automatyzacji i nie wysłano
wiadomości koordynatorowi. Procesy/bazy odbioru są własne i zostaną zakończone po kontroli.
