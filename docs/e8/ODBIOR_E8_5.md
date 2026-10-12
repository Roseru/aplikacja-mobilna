# Odbiór E8.5: backend i otwarte odbiory zespołu - osoba 2

13 października 2026 r. **Backend E8-O2 / E8.5: PASS w odebranym zakresie. Pełne zespołowe E8: WAITING_EXTERNAL.** PR42 i osobny CI main są odebrane; gate pozostaje domyślnie zamknięty, bez produkcyjnej aktywacji.

## Stan i dokładne źródło

| Pozycja | Stan / dowód |
| --- | --- |
| Koordynator E8.5 | Agent 2, istniejący czat koordynacji; poprawki wracają do właściwych wykonawców |
| E8.1 + E8.2 | PR35, odebrane/scalone; main `2b3ac613` i jego osobne CI opisane w O2-024/025 |
| E8.3-I | PR37, odebrane/scalone; main b68d645 i osobny push CI38236250411 |
| E8.4 | [PR42](https://github.com/Roseru/aplikacja-mobilna/pull/42), branch `codex/backend-e8-nemesis-wyniki`, scalony przez koordynatora |
| Końcowy head PR42 | `415780afccfb1f55453ac781e19f46cce5207894` |
| Źródło implementacji | `22d6bc99f9292f248e31c4d433339fb44d6601bc` |
| Base PR42 | `ce8a326c7f745a00583745b90b164496073a0a61` |
| CI PR42 | [CI PR42](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38312042765): osiem completed/success, wszystkie rzeczywiste logi odczytane przez koordynatora |
| Scalony main | `59157db28e22bac7710b0d70f02821f30fc17c30`; rodzice `ce8a326` i `415780a`, całe drzewo identyczne `415780a` (`c05a5ca55f8183c6125083aada69edd730bc445d`) |
| Osobny CI push main | [CI38313766249](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38313766249), dla `59157db`; osiem completed/success, rzeczywiste logi wszystkich jobów odczytane |
| Liczności CI PR42 | 1658 unit, 1265 PG, 21 infra, 28 Keycloak, 126 JVM, 130 device; odrębne zestawy, bez sumowania |
| Wynik backendu E8.5 | **PASS w zakresie backendu; brak zidentyfikowanych otwartych P1/P2 w sprawdzonych zakresach** |
| Pełne zespołowe E8 | **WAITING_EXTERNAL: rzeczywiste odbiory O1/O3 wymienione niżej** |

## Wykonany odbiór backendu E8.5

Koordynator sprawdził końcowe źródło, dowody i integrację, zachowując osobne zakresy oraz historyczne RED.

1. PR42 oraz osobny push main mają po osiem completed/success. Logi każdego joba odczytano; dla main: **1658 unit, 1265 PG (785,61s), 21 infra, 28 Keycloak, 126 JVM, 130 device**, bez sumowania zestawów. Przeszły contracts/E0, installed wheel i Docker bez editable/fallback `/app/src`, rzeczywisty eksport/import w obrazie oraz lokalne HTTPS/PKCE i restart.
2. Właściwy odbiór dotyczy `22d6bc9`. Diff `415780a` → `22d6bc9` obejmuje tylko cztery dokumenty. Guard przed zwykłym merge sprawdził head `415780a` i base `ce8a326`, brak zmian wymagających poprawy oraz osiem sukcesów. Main `59157db` ma rodziców `ce8a326` i `415780a` i całe drzewo identyczne `415780a`.
3. Diff migracji do przyjętej bazy zawiera wyłącznie nową0021; 0001–0020 są immutable. Jedna linia Alembic, ORM/readiness, sync-v1/hash/receipt/checkpoint i instalowany pakiet zostały sprawdzone. Regresja zachowuje E0–E7; nie zamyka ich E5-C/E7-R lub zewnętrznych bramek wydania.
4. Root odebrał niezależne source/provenance, czas/blokady, prywatność/finalizer oraz właściwy zmieniony agregat SQL07/Python22d. Dawny pełny przebieg1261 z1241PASS/18FAIL/2ERROR pozostał RED; konkretne poprawki/targeted closures są opisane w raporcie, a finalne pełne PR/main1265 mają PASS. Własne precision RED mają niezmienione Fraction oczekiwania przed/po. Powtórki i błędy harnessu są jawne.
5. Utrzymano default-closed gate, role operatora/workera, zakończenie własnych usług i osobne przekazania O1/O3. Wydanie, aktywacja i rzeczywisty klient wymagają dowodów zespołu wymienionych poniżej.

## Wymagania i właściwe dowody

| Zakres | Właściwe dowody i granica |
| --- | --- |
| WF-10/11, kompletność i regularity_v1 | Motywacja PR35: maturity/catch-up bez klienta, korekty/rangi/odznaki, ranking opt-in i revocation; regresja finalnego main potwierdza integrację |
| WF-12 / KO-14 | Atomowy seed2N, dokładne terms/scopes, hidden/null/zero/counts, uczestnictwo i brak cudzych surowych danych; cancel/deletion/restore odcinają odczyt |
| KO-22/26/27 | Jeden autorytatywny q i pełny lockset, commit po deadline, rollback/retry, późny source i projection-only finalizer z fizyczną blokadą źródeł |
| KO-29 / kalendarz | Accepted zone, DST, maturity bez klienta, restart/fair discovery, finalizer niezależny od motivation worker |
| Agregaty | Mean z historycznego maintenance E, dokładne ułamki SQL07 i Python22d, końcowe HALF_UP i signed wire; wynik gry zależy tylko od punktów |
| Historia / role / usuwanie | Source savepoint/replay/provenance, minimalny SCRAM LOGIN i role graph, immutable migracje, scoped E4–E8 purge/COMMIT/retry, epoch fence i rzeczywisty archive/restore |
| Dostarczalność i regresja | Actual CI: PG17, unit/infra, contracts, installed wheel/Docker-I, Keycloak/HTTPS/local-integration i Android jobs; zakres środowiska odróżniony od produkcji/APK odbioru E8 |

[Raport E8.4](RAPORT_NEMESIS_WYNIKI.md), [recenzja E8.4](RECENZJA_NEMESIS_WYNIKI.md) i [recenzja poprawki średniej](RECENZJA_POPRAWKI_SREDNIEJ_NEMESIS.md) zachowują poprzednie RED i przypisanie do źródeł. O3-012 jest autorskim dowodem poprawki SQL, nie niezależnym odbiorem tej poprawki.

Koordynator odebrał osobno18 prób kwalifikacji i12 prywatności/finalizera na605, dotyczących niezmienionych granic. Nowy suplement średniej na22d ma10 odrębnych przypadków PG/HTTP/Python/Fraction i ocenę9,3 bez zidentyfikowanych otwartych P1/P2. Niezależny odbiór wykonawcy obejmuje19 targeted w39,21s:4 niezmienione legalne HTTP RED→GREEN,12 nowych wektorów i3 właściwe wcześniejsze próby SQL. Nie jest to19 nowych unikalnych testów. [Odbiór koordynatora PR42](https://github.com/Roseru/aplikacja-mobilna/pull/42#issuecomment-6133347311) podaje wykonane zakresy i manifesty.

Własne próby używają PostgreSQL17.11/SCRAM, produkcyjnej factory/router i TestClient z syntetycznym JWT/JWKS. Lokalne HTTPS/PKCE/Keycloak mają osobne rzeczywiste CI; public origin/API/issuer/CA dla Androida pozostają odbiorem O1/O3. Suplement średniej wykonano przez `python -I run.py` i affected-only permutation, a własny niezmieniony oracle przez `python -I` poza checkoutem, bez fallback src. Root wheel76b603 i SQLbody33e4 powiązano z22d; źródła odpowiadają finalnemu59157. Własne PG15701/15702 zatrzymane,15703 nie uruchamiano. Credentials, raw logi i buildy pozostają poza repo.

## Otwarte odbiory zespołu

| Właściciel | Brakujący rzeczywisty dowód | Warunek wznowienia / zamknięcia |
| --- | --- | --- |
| O1 + O3, O1-015 | Działające public origin/API, issuer i zaufane CA dla klienta | O3 przekazuje istniejącą bezpieczną konfigurację; O1 sprawdza realny HTTPS/OIDC bez osłabiania TLS |
| O1, motywacja/ranking | Realny GET/API, status/revision, świadoma afirmacja zgody i skuteczne odcięcie publikacji | Zgodne APK/API, A/B/logout/epoch, opt-in/opt-out i spóźnione odpowiedzi; O1-021 fixtures/Android0.8.6 nie zastępują próby |
| O1, Nemesis | Pairing/terms/accept/cancel, pending/provisional/final, hidden/null/signed metrics, cache/session/no-store | Własny UI/API/APK odbiór według [przekazania wyników](INTEGRACJA_O1_NEMESIS_WYNIKI.md) i lifecycle; także cancel/deletion/restore po final oraz A→B |
| O1, E4 | Rzeczywisty push/ACK/replay/import/WorkManager i KO-31 | Własny odbiór na zgodnych APK/API; zachowanie kolejek, właścicieli i starych hash/receipts, bez fikcyjnych partnerów w Room |
| O3 | Rollout/migracje/minimalne role, świadoma activation, motivation/lifecycle/finalizer workers | Wykonane komendy, minutowy schedule, backlog/health i restart na właściwym środowisku według [konfiguracji](KONFIGURACJA_O3_NEMESIS_WYNIKI.md) oraz wcześniejszych przekazań |
| O3 + O1/O2 | Backup/restore, RPO/RTO i klient po nowej epoce | Rzeczywisty spójny restore, fencing przed reopen, brak starego sharing/ranking regrant, reconciliation klienta; lokalny PG/archive i CI nie zastępują tego odbioru |

Odbiorcy sami potwierdzają odczyt i wykonanie w `KOMUNIKACJA_AGENTOW.md`. Nie tworzymy drugiej tablicy. Raport opisuje dowody; nie uruchamia wdrożenia, automatyzacji Codex ani zewnętrznych wiadomości.

## Wynik końcowy

- Backend E8-O2 / E8.5: **PASS**: source22d, PR415/CI38312042765, main59157/CI38313766249; brak zidentyfikowanych otwartych P1/P2 w sprawdzonych zakresach.
- Pełne E8: **WAITING_EXTERNAL**, do czasu własnych dowodów O1/O3; nie nazywać go PASS na podstawie backendu.
- Następny krok: O1/O3 dostarczają własne brakujące dowody; koordynator publikuje ten dokumentacyjny odbiór; poprawki wracają do obecnych wykonawców. E9 nie jest zlecone, harmonogramy Codex pozostają PAUSED, nowego głównego czatu implementacyjnego nie tworzymy.
