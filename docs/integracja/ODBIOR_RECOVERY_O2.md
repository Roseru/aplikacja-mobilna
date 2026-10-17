# Odbiór migracji i recovery — O2

Stan 17.10.2026: **serwerowy KO17/32 PASS**: runner HTTPS/Keycloak/paired restore
oraz pełne regresje E4/E7/E8/E9 zakończyły się sukcesem w CI39026906997.
Migracja0021→0024 i regresja61dni PASS również na własnym PG17.11/SCRAM.
**Pełne KO32 WAITING_EXTERNAL**: O1 telefon/Room/UI, O3 offsite, ciągły autorytatywny
rejestr, issuer/repliki i rzeczywiste RPO/RTO. Nie wykonano Google ani zmian usług zespołu.
Bieżący krok: dokumentacyjny commit D i jego osiem CI, następnie odbiór koordynatora; bez merge.

## Odebrany zestaw wykonawczy C

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

Poprzednik: main E8 `a522471140150271d853d66aa06f11d868699e49`, schema0021;
nie twierdzimy, że to istniejący wydany APK/API. Nie mamy odebranego immutable
obrazu tego poprzednika. Strategia **restore**, `for_revision=0024_e9_history_graph`.
`compatible_image/schema_compatible=true` nie są deklarowane. Obraz z aktualnego C
jest budowany z prawdziwym OCI revision i zapisany jako immutable sha256 imageID.
Dla produkcji O3 musi dostarczyć repo digest i właściwe kopie/sekrety docelowego zestawu.
Nie stosujemy dowolnego Alembic downgrade jako rollbacku danych.

**Rollback poprzednika0021: BLOCKED**, O3/O2: potrzebny konkretny odebrany obraz
0021 oraz spójny zestaw kopii tego poprzednika do próby startup/readiness/API.
Nowe pg_restore wykonuje0024→0024, więc daje PASS recovery obecnego schematu,
a nie dowód cofnięcia migracji0021→0024. Receipt rollback ma `result=BLOCKED`
i jawny zakres wykonanej próby; checker poprawnie odrzuci go jako brak pełnego
odbioru rollbacku. O2 wznowi ten zakres po dostawie O3. Brak nie blokuje
publikacji macierzy/migracji i odebranego recovery serwera.

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

Runner sprawdza zakres posiłku i sesji. Pełny **serwerowy** oracle składamy dopiero
z tego wyniku oraz aktualnie wykonanych regresji E4/E7/E8/E9 na tym samym C:

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
i `rollback.json` z jednym pełnym **C**. Ten ostatni pozostaje BLOCKED dla
cofnięcia migracji poprzednika, nawet gdy recovery0024 uzyska PASS. Testowany obraz jest osobnym CI artefaktem `o2-backend-image-<C>`;
`docker image load -i backend-image.tar` pozwala O3 otrzymać ten sam imageID.
Obraz nie zawiera runtime credentials. Wspólny obraz/schema są sprawdzane, rollback
ma strategy=restore z jawnym brakującym odbiorem poprzednika. Nie tworzy brakujących android_acceptance/restore receiptów
ani kompletu CANDIDATE_VALIDATED. [Checker wydania](../../infra/integration/WYDANIE.md)
pozostaje niezmieniony; release na przyszłym wspólnym M wymaga świeżych dowodów M.
Późniejszy commit dokumentacji D nie przepisuje receiptów C.

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
