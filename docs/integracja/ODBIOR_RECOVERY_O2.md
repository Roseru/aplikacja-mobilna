# Odbiór migracji i recovery — O2

Stan17.10.2026: **FIX1 i serwerowy KO17/32 PASS** na nowym C2.
Rzeczywisty scratch rollback0021→upgrade0024→paired restore0021 również **PASS**.
**Pełne KO32 WAITING_EXTERNAL**: O1 telefon/Room/UI; O3 offsite, autorytatywny
ciągły ledger, issuer/repliki i produkcyjne RPO/RTO/rollback wdrożenia.
Google I/O0; AI/Nemesis zamknięte; usługi zespołu nietknięte.
Koordynator odebrał FIX1: **9,4/10, trzy P2 zamknięte, brak nowych P1/P2**.
[PR116](https://github.com/Roseru/aplikacja-mobilna/pull/116) scalono do main
jako `faee91f771d9dcf0e5155d64984bc3f042ad394f`; wymagane CI dokładnego D2:8/8 SUCCESS.
Bieżący krok: osobny odbiór merge oraz wspólny kandydat APK/API i brakujące
dowody O1/O3 według [przekazania O2-039](../KOMUNIKACJA_AGENTOW.md).
Receipts i obrazy C2 zachowują źródło C2; merge nie oznacza odbioru pełnego KO32.

## FIX1 — odbiór koordynatora i nowe źródło C2

Marker `O2_RECOVERY_PR116_FIX1_2866c69d`. Koordynator ocenił wcześniejszy
head2866c69d na8,5/10: **trzy P2, wymaga poprawek**. Historyczne8/8 i pliki C
pozostają prawdziwe; słabsze asercje nie wystarczały do odebrania całego zakresu.
Aktualny wynik C2: **8/8 CI SUCCESS**, rzeczywisty recovery i scratch rollback PASS.
Historyczna ocena9,4/10 została zastąpiona uwagami koordynatora; odbiór FIX1 jest osobny.

1. Porównanie `null == null` przepuszczało dwie różne encje. Nowy oracle wymaga
   pełnego mappingu ze źródła wejściowego do pierwszego target, statusów
   accepted/already_applied i zachowuje kontraktowe requested entity_id drugiej
   odpowiedzi. Pełny snapshot HTTP porównuje oba oczekiwane payloady, składniki
   i wartości z kanonicznym fixture, SQL sprawdza dokładnie baseline+jedną
   odzyskaną encję z właściwym owner/revision oraz jeden mapping; brak drugiego ID.
2. Retencja61dni: przed prune dokładne4changes/3pełne receipts i niezależne
   hashe SHA256 canonical JSON z końcowym newline. Po prune4/3: baza ma0changes,
   3NULL response i identyczne trwałe ID/hash/status/revision/source/action oraz
   niezmieniony tombstone. Wszystko przed snapshot/replay oryginalnych operacji.
3. Nowy [eksperyment rollbacku](../../infra/integration/rollback_o2.py) pobiera
   exacta522471 przez gitarchive, buduje jego niezmieniony Dockerfile z uczciwym
   OCI revision tego źródła i własnym immutable imageID. Własny PG17/KC26.8.0,
   A/B/posiłki, historyczny capture/rehearse (app/KC/globals/catalog/config),
   rzeczywisty upgrade0024, odmowa readiness starego obrazu na0024, paired
   restore0021 i nowa epoka, cleanup, logout-all/421s, odmowa starych sesji,
   świeżePKCE i HTTP read/write/replay. Obraz0021 jest oddzielny od C2/image0024.
   Brak biznesowych zapisów między kopią i restore jest jawnym ograniczeniem RPO;
   dwa świeże zapisy po restore służą odbiorowi scratch. Produkcja nadal O3.

Affected GREEN:92unit/runner (w tym26oracle) oraz36PG E4 push/snapshots/restore.
Test61dni przeszedł także osobno na własnym PG17. Kontrolowane kopie RED:
wyłączony helper walidacji odpowiedzi6FAIL (w tym historyczny null/null);
wyłączony oracle końcowego stanu7FAIL (duplikat, mapping, owner, treść/składniki/wartości);
no-op prune z kłamliwymi counts4/3 FAIL na rzeczywistym DB4!=0. Kod roboczy
pozostał poprawny. Pierwsza nowa próba hash pokazała brak końcowego newline
w testowym oczekiwaniu; poprawiono oracle według canonical wire, nie produkt.
Niezależny odbiór kodu/runtime/pakietu FIX1: **9,4/10, bez otwartych P1/P2**.
Sprawdzono ponownie CI, sześć SHA256/rozmiarów i oba configi obrazów/OCI revision;
trzy P2 koordynatora zamknięte. Końcowy odczyt dokumentacji wskazuje PR.

## Odebrany zestaw wykonawczy C2

[CI39031423976](https://github.com/Roseru/aplikacja-mobilna/actions/runs/39031423976):
**8/8 SUCCESS**, head `1abd43753031b974029213542563bcb490e51449`,
base `a6e239558a4ab664e3f9d3b6635657876878b412`.
Actual checkout **C2**: `672b72a3a1d0ad9b03ec7d2ed1297bbff701031e`; schema0024.
Current image/OCI revision=C2: `sha256:3b803488e0cdfc99bd5398a00f5e0f9f92386b7a90a546300ba58e2aaa24b7e7`.
Predecessor image: `sha256:bdea93cae9918a4a30c425d31e838a8649316903dbcc014ab87ee7a39b9c90cd`;
OCI revision=`a522471140150271d853d66aa06f11d868699e49`, schema0021.
Nie podmieniono etykiety bieżącego obrazu; zbudowano rzeczywisty historyczny context.

1714unit/167infra(+1istniejącyLinuxskip)/1364PG/28PKCE/155JVM/169device PASS.
Ruff/format, contracts, local-integration i ci-required SUCCESS. Local-integration
wykonał nowy oracle nonnull mapping/status/payload/SQL oraz obie prawdziwe próby:
recovery wait421,0s; rollback wait421,049s, stareJWT401/refresh400, świeżePKCE.
Stary obraz na0024 dał readiness503; dopiero powrót spójnego zestawu0021
przywrócił readiness/API. Zachowano oba posiłki i właścicieli, wykonano dwa świeże
zapisy i ich replay po restore; AI/Nemesis zamknięte. Rehearsal globals/SCRAM,
archiwa app/KC i katalog/config wykonane narzędziami historycznego źródła.

Dostawa lokalna `.tools/o2-zgodnosc-recovery-delivery/39031423976`:
cztery neutralne JSON, dwa obrazy i `delivery-manifest.json` z sześcioma hashami.
Artefakty neutralny12101191829 i obrazy12100882806 pochodzą wyłącznie z tego run.
Ich digesty: `sha256:5cd76ed7ce875f13b24a501c8c6729ae4e677354582a409f091939eafa461de8`
oraz `sha256:8ce3df97203443f660baa7fb6e37e6083c01424ea48dc29783036283d55ea4bf`.

| Plik | SHA256 |
|---|---|
| `recovery-o2.json` | `88797aadeea78826c7044c94fefe92664f988b0bd3afb83107afb6220900a251` |
| `backend_acceptance.json` | `291f1bb010debf1af25d71511feac4b403dea78c11889ea708900234a696820d` |
| `migration.json` | `df701b28155894e9434fb294ba3e42b4fe97d2de2d4821a2bdc574579ae5ca36` |
| `rollback.json` | `445114a84d4c0dd0ec4050958758804ed5fe56725075a1faef966ea287631c0b` |
| `backend-image.tar` | `561b23c533253eb7c9d5be1fdad5f74c6b9ee015403eb1a6d3a31104dd3bf519` |
| `predecessor-image.tar` | `f9cfce96b1bb705227dc129b3d29c09521a3589f9376e7bbb2a73e51f795cd71` |

Receipts C2 pozostają niezmienne po dokumentacyjnym D2; exact D2/head/base/CI
podaje opis PR i callback. Deployment nie jest autoryzowany. Brakujące dowody
O1/offsite/produkcyjnego rejestru nadal blokują komplet CANDIDATE_VALIDATED.

## Odebrany zestaw wykonawczy C

**Historia sprzed FIX1**: dawne wyniki/receipts są zachowane; słabe asercje i brak
scratch rollbacku wykryte przez koordynatora są poprawione wyłącznie w nowym C2.

[CI39026906997](https://github.com/Roseru/aplikacja-mobilna/actions/runs/39026906997)
ma **8/8 SUCCESS** dla head `243bdc0d45199da33c2e229e9516bbd40f8728a7`
i base `a6e239558a4ab664e3f9d3b6635657876878b412`.
Rzeczywisty checkout wykonania **C**: `3c62ee65b28a415572073d0474501fa609268b65`.
Obraz: `sha256:c130717b5687f63172eed736097fc894de9ce841b5c62c8496e50fca29193679`;
OCI revision=C, schema=`0024_e9_history_graph`.

- Quality:1714 unit PASS; infra153 PASS i jeden istniejący Linux skip testu konsoli Windows.
- PostgreSQL:1364 PASS, bez pominięć; Keycloak/PKCE:28 PASS.
- Android z main:155 JVM PASS,169/169 device PASS, lint29warnings/1info; to CI, nie odbiór telefonu O1.
- Contracts i local-integration PASS; ci-required SUCCESS. Issuance zamknięte przez421,0s;
  stare access401 i refresh400/invalid_grant, świeże PKCE i recovery mapowania PASS.

Pobrano lokalny pakiet `.tools/o2-zgodnosc-recovery-delivery/39026906997`:
cztery JSON, obraz i `delivery-manifest.json` z SHA256 wszystkich pięciu plików.
Artefakt neutralny12098714670 ma digest
`sha256:3d83f7946d98444538abaa09d22ec1dbcb5a9ca1f98c0536bd54b628013b0d87`;
artefakt obrazu12098704603 ma digest
`sha256:5816565801dd2abaafee75ff7b9a897b92dbcf85ebfdd446d0dd1e15f386f871`.
SHA256 samego `backend-image.tar`:
`f93cedcb7385dacfb423c77dedcd46d94233ba739f7989fa4426dd59a967639a`.
Backend/migration/recovery mają PASS; rollback ma BLOCKED. Pakiet nie autoryzuje deploymentu.
Niezależny odbiór kodu/runtime/pakietu: **9,4/10, bez otwartych P1/P2**;
przeliczono pięć SHA256 i odczytano config obrazu/OCI revision z tar.
Źródła i dokumentacja są w [PR116](https://github.com/Roseru/aplikacja-mobilna/pull/116).
Końcowy head D/CI jest raportowany w PR i callbacku; receipts C pozostają niezmienne.

## Mapa dowodów i decyzja rollbacku

[Macierz](ZGODNOSC_API_O2.md) wskazuje konkretne wersje i zakresy. Nie powielamy
[backup.py](../../infra/integration/backup.py) ani [release.py](../../infra/integration/release.py).
Istniejący [restore O3](../e8/ODTWORZENIE_SESJE_I_KLIENT_O3.md) dotyczył0021 i wagi;
nowy [runner](../../infra/integration/recovery_o2.py) uzupełnia aktualny head i posiłek.

Poprzednik: main E8 `a522471140150271d853d66aa06f11d868699e49`, schema0021.
W C2 odebrano własny immutable obraz z tego źródła i syntetyczny spójny zestaw
kopii. Strategia **restore**, `for_revision=0024_e9_history_graph`; rzeczywista
próba wróciła z upgrade0024 do0021 i potwierdziła startup/readiness/API/dane.
`compatible_image/schema_compatible=true` nie są deklarowane: ten obraz odmówił
readiness na0024. Nie stosujemy Alembic downgrade ani retagowania nowego obrazu.

**Scratch rollback0021 PASS** w opisanym zakresie. Nie było biznesowych zapisów
między kopią a restore; próba nie dowodzi utraty zerowej dla późniejszych zapisów
ani produkcyjnego RPO. **Rollback wdrożenia WAITING_EXTERNAL O3/O2**: potrzebny
konkretny odebrany obraz wdrożonego poprzednika oraz jego spójne kopie/konfiguracja,
repo digest i docelowe dowody. Własny build a522471 nie dowodzi historycznego
wydania APK/API ani odbioru instalacji zespołu. Historyczny receipt C miał BLOCKED;
nowy receipt C2 ma PASS wyłącznie dla wskazanego scratch restore.

Nowy `test_o2_populated_0021_to_current_graph_and_legacy_replay` wykonuje Alembic
na niepustym0021: dwa konta/role DB API, profil/wersję celu/14dni historii, pomiary,
kompletność, g/ml/null, snapshot zjedzonej pozycji racji i referencję produktu, zaakceptowany
Nemesis z niepustymi projekcjami, kolejkę zdjęcia/zgodę AI i legalną rezerwację
10240 tokenów mocka (claim/dispatch przez prawdziwy LOGIN workera, bez provider I/O),
sync ACK i tombstone. Payload posiłku reprezentuje import lokalnego gościa do A;
nie tworzy konta gościa. Porównanie wszystkich dawnych wartości/kolumn jest
oddzielone od przewidzianych metadanych migracji (4 releases, aktualny runtime
contract i zamknięty Nemesis). Niezależne oracles sprawdzają 15 posiłków, 4 żywe
wagi, 235.5kcal z dwóch jednostek, E=2595 bez affirmation, tożsamości/UUID i replay.
Nie zmodyfikowano0001–0024. Scope lokalnej migracji nie jest PKCE/APK.

## Powtarzalna próba server KO17/32

```text
uv sync --project backend --locked
uv run --project backend --locked python infra/integration/recovery_o2.py --state <nowy-prywatny-katalog> --port 19443
```

Wymaga działającego Docker Linux/Compose i czystego zatwierdzonego checkoutu.
Runner odrzuca istniejący katalog, losuje własny projekt, publikuje wyłącznie
loopback i tworzy własny CA/issuer/A/B. Stan wewnątrz repo musi być pod `.tools`.
Na hoście O2 Docker jest niedostępny; kontenerową próbę wykonuje istniejący job
`local-integration` na swoim runnerze. Limit35min obejmuje wcześniejsze kontrole
O3 oraz nową pełną próbę; żaden dotychczasowy test nie został pominięty.

Kolejność i oracles:

1. Prawdziwe HTTPS/PKCE A/B, bootstrap, checkpoint, przyjęty posiłek A.
   `backup.py capture` zatrzymuje wszystkich writers/issuance; verify i rehearse
   odtwarzają oba archiwa/globals/katalog w oddzielnym PG17 bez sieci.
2. Własne źródło przyjmuje kolejny posiłek; wymagane `accepted` i read-back.
   Istniejące begin→rzeczywiste Keycloak DELETE/GET404→confirm→purge usuwa B.
   Runner zapisuje prywatny rejestr obserwacji poza cofanym zestawem i przypina hash.
3. Przy zatrzymanych writers prawdziwe pg_restore obu baz odtwarza B oraz pierwszy
   posiłek, a gubi drugi potwierdzony posiłek. To reprodukcja zagrożenia, nie PASS
   samego bezpiecznego recovery. Restore ról/SCRAM jest wykonany w rehearse;
   dalsza próba cofa własne bazy tego samego zestawu, zachowując jego role.
4. Nowa epoka jest trwale zatwierdzona; snapshoty usunięte, AI/Nemesis zamknięte,
   bounded cleanup do pending0. Zamknięta bramka dopuszcza tylko admin/JWKS;
   API i user issuance503. Rejestr jest sprawdzony przed ponownym begin/confirm/
   purge dokładnego issuer/sub/account/generation; Keycloak GET404 i logout-all.
5. Bramka pozostaje zamknięta **co najmniej421 rzeczywistych sekund** od zamknięcia
   issuance po restore. Backend dopuszcza lifetime300s/skew60s; konserwatywny bound
   nieznanych tokenów wynosi420s z przyszłym iat i leeway. Nie zmieniamy zegarów
   ani tolerancji. Po lokalnym otwarciu każdy stary access401, refresh400/
   invalid_grant; świeże PKCE A działa, usunięte B nadal404. Nie wystarcza logout-all.
6. Stary bootstrap/key409; stary checkpoint odrzucony również z nową epoką
   żądania/operacji, bez resetowania idempotency. Pełny snapshot nie zawiera
   potwierdzonego posiłku po kopii. Dopiero jawne recreate_missing z bieżącą epoką
   i nowym entity/operation UUID tworzy mapowanie source→target. Ponowienie z
   drugiego urządzenia trafia do tego samego target. AI/Nemesis pozostają zamknięte.

Runner sprawdza posiłek i sesje oraz wywołuje osobny własny rehearsal poprzednika.
Pełny **serwerowy** oracle C2 składa się z tego wyniku i wykonanych regresji
E4/E7/E8/E9 na tym samym C2:

| Zakres | Istniejący wykonywalny dowód | Co musi przejść |
|---|---|---|
| Oryginały/outbox/recovery | `test_e4_client.py`, `test_e4_restore.py`, `test_e4_independent_regressions.py` | Zachowane wersje, brak automatycznego push, różna treść/target→konflikt |
| AI/niepewna wspólna pula | `test_e7_maintenance.py::test_real_dump_restore_new_epoch_never_replays_old_job_and_resume_requires_hold_and_fencing` | Real dump/restore, stare workers martwe, mock countTokens/generateContent=0, reserved_tokens10240 zachowane, permits/fencing/hold336h sprawdzone |
| Sharing/ranking/cleanup | `test_e8_3_integration_deletion.py::test_restore_new_epoch_bounded_cancellation_clears_old_payloads_without_reopen`, `test_actual_archive_cannot_resurrect_withdrawn_sharing_after_new_epoch` i `test_e8_history_restore.py` | Brak odtworzenia sharing/affirmation, bounded cleanup, brak automatycznego reopen |
| E9 zgoda/epoka | `test_e9_energy.py`, `test_e9_worker.py` | Stara affirmation i zadania nie dają nowej zgody, zmiana epoki/gate blokuje automat |

Nie uruchamiamy starego workera przeciw rzeczywistemu dostawcy. Testy wykonujące
hipotetyczny późniejszy reconcile/activate działają wyłącznie w bazach testowych;
nie stanowią polecenia reopen instalacji ani decyzji użytkownika.

## Granica niezależnego rejestru — dostawa O3

Prywatny rejestr runnera jest **lokalnym fixture** zakończonej rzeczywistej deletion,
nie wdrożonym autorytetem produkcyjnym. `verify_fixture_ledger` nie jest narzędziem
importu dowolnego JSON. Brak pliku, hash/target/origin mismatch, brak ukończenia lub
starsze coverage powodują FAIL; neutralne testy odmów są w `test_recovery_o2.py`.

Przed prawdziwym reopen O3 dostarcza: tożsamość właściciela i autentykowane źródło
strumienia poza cofanym zestawem; installation/issuer scope; nieprzerwany zakres
sekwencji/czasu od kopii do ostatniego dopuszczonego issuance/zapisu; ostatni
potwierdzony watermark, w tym pending/failed deletion i blokady; integralność,
retencję i niezależność magazynu. Rekord wiąże operation_id i dokładne
issuer/sub/account/expected_generation/deleting_generation oraz wynik provider/
confirm/purge. O2 porównuje te wartości i uruchamia istniejący protokół deletion;
O3 dowodzi kompletności/aktualności i fencing wszystkich replik. Niepewne,
brakujące albo sprzeczne wejście **utrzymuje zamknięty ruch**, nie jest pustą listą.
Wymagany kontrakt magazynu i odbiór O3 pozostają WAITING_EXTERNAL.

## Warunki późniejszego reopen — niczego tu nie otwieramy

| Warunek | Właściciel | Wymagany dowód |
|---|---|---|
| Zgodny zestaw C/image/schema, role i aktualna epoka | O2/O3 | Receipts z rzeczywistej próby, readiness, epoch commit; restore zmienia epokę, restart/zgodny obraz jej nie zmienia |
| Wszystkie stare workers/issuers/repliki fizycznie odcięte | O3, odbiór O2 | Inwentarz i fencing evidence; rzeczywiste stare JWT/refresh denied, sprawdzone zegary/lifetime/leeway |
| Deletions, snapshoty, sharing/ranking | O3 operacja, O2 odbiór | Kompletny zewnętrzny rejestr, zgodny issuer/sub/generacja, GET404, pending0, brak odtworzenia zgód |
| Pula AI i limity E7/E9 | O3 operacja, O2 reguły | Istniejący `e7_reconcile` z bieżącą epoką, poprawnym dowodem martwych workers i wymaganym hold; zachowane closed_at, wykorzystane/niepewne rezerwacje i limity użytkownika; wszystkie niepewne okna uzgodnione lub wygasłe, w tym Pacific RPD i14dni |
| Jawne potwierdzenia E8/E9 | Użytkownik poprzez O1, backend O2 | Nowe ranking/sharing/automatic consent/affirmation bieżącej epoki i aktualnych rewizji; skrypt nie zastępuje decyzji użytkownika |
| Włączenie danej capability | O3 po odbiorze O2/O1 | Istniejące entrypointy/kontrakty, aktualny release, źródła/Nemesis projekcje i role; osobna decyzja środowiskowa |
| Prawdziwy provider | Właściciele projektu/O3 | Rozwiązane wymagania11.6 i ograniczenia udostępnienia, datowane limity/model/projekt i jawna prywatna konfiguracja; w tym zadaniu Google I/O0 |

## Receipts i odbiór O3

Po sukcesie runner zapisuje neutralne `backend_acceptance.json`, `migration.json`
i `rollback.json` z jednym pełnym **C2**. Ten ostatni ma PASS wyłącznie dla
wykonanego synthetic predecessor restore, z osobnym predecessor_commit/image/schema. Testowany obraz jest osobnym CI artefaktem `o2-backend-image-<C2>`;
`docker image load -i backend-image.tar` pozwala O3 otrzymać ten sam imageID.
Drugi plik `predecessor-image.tar` ładuje historyczny obraz0021 o osobnym OCI revision.
Obrazy nie zawierają runtime credentials. Wspólny obraz/schema są sprawdzane, rollback
ma strategy=restore z odebranym scratch poprzednikiem i jawnym brakiem odbioru produkcji. Nie tworzy brakujących android_acceptance/restore receiptów
ani kompletu CANDIDATE_VALIDATED. [Checker wydania](../../infra/integration/WYDANIE.md)
pozostaje niezmieniony; release na przyszłym wspólnym M wymaga świeżych dowodów M.
Późniejszy commit dokumentacji D2 nie przepisuje receiptów C2.

Repo zawiera kod/formaty/raport, a prywatny lokalny katalog zawiera archiwa,
credentials/identity/tokeny i raw logs. CI publikuje wyłącznie neutralne receipts;
surowego stanu, kopii, CA keys lub rejestru nie publikujemy. Lokalną paczkę O3
złożono z odebranych neutralnych JSON i SHA256 jak wyżej; brak zewnętrznych dostaw
nie jest naprawiany fikcyjnym PASS. Czas scratch restore nie jest produkcyjnym RTO.

## Historia prób

Lokalne pierwsze RED: konflikt strefy posiłku fixture; oczekiwanie niezmiennej
liczby metadanych releases; pomylenie energii na100 z sumą spożycia; replay dwóch
operacji tej samej encji w jednej kopercie niedopuszczalnej v1. Naprawiono wyłącznie
harness i niezależne oracles. Końcowe nowe testy PG:2PASS; pełny właściwy zestaw E4 push/snapshots/restore i E9 migration/sync:47PASS w184,25s. Pierwszy pytest temp
Windows odmówił dostępu do zastanego katalogu; dalsze próby miały własny basetemp.
Własny PG uruchamiany i zatrzymywany w jednym procesie; cudzy checkout i untracked
pozostały zachowane. Pełny wynik CI jest zapisany powyżej; końcowy niezależny odbiór wskazuje PR.

Dalsze RED runnera: pierwszy przebieg39025612716 potwierdził backup i reprodukcję
po pg_restore, drugi39026099713 wskazał ConnectError pierwszego GET maintenance
przed startem listenera. Ograniczone oczekiwanie naprawia wyłącznie transport;
HTTP200/401/502 pozostają natychmiastowym FAIL (12affectedPASS). Przebieg
39026471041 doszedł do logout-all; poprawiono oczekiwanie204 na dokumentowane
200/GlobalRequestResult z kontrolą failedRequests według
[Keycloak26.8](https://www.keycloak.org/docs-api/26.8.0/rest-api/index.html#_post_adminrealmsrealmlogout_all).
Następny przebieg39026906997 potwierdził rzeczywiste421s i odmowę starychJWT/refresh.
Regresję istniejącego state sprawdzono kontrolowaną mutacją w izolowanej kopii:
przywrócony dawny zapis do odrzuconego katalogu → oczekiwany testFAIL;
normalne12przypadkówPASS. Prywatne raw logs i neutralne wcześniejszeFAIL zachowane.
