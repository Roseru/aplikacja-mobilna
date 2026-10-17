# O2 — odbiór ciągłego rejestru usunięć v1

Zlecenie O2_LEDGER_20261017_V1, 17.10.2026, agent2.
Gałąź `codex/backend-ciagly-rejestr-usuniec`, baza `615fb6b3f875bef8a0c04c95a1a87e32af20e9e3`.
Migracja `0024_e9_history_graph` → `0025_deletion_ledger`.
PR/head i rzeczywisty wynik CI zostaną przypięte w dzienniku po publikacji;
poniższe liczby są lokalnymi dowodami, nie potwierdzeniem zdalnego CI.

## Wynik i granica

Transakcyjny outbox PostgreSQL, commitowane sekwencje/hash, oddzielny eksporter,
uwierzytelnienie źródła i zewnętrznego ACK, bariery begin/provider/confirm/purge.
Intencja i ACK są wymagane przed efektem. Finalny lokalny purge nie oznacza
zakończenia, dopóki nie ma ACK jego wyniku. Standardowy HMAC-SHA256 z odrębnymi
kluczami źródła/ACK; administrator/migrator i odbiorca pozostają granicą zaufania.
[Dokładny protokół, role, komendy, cutoff i warunki O3](REJESTR_USUNIEC_O2.md).

Odczytano O3-066 na PR123 `dd39050b69711a91023e20d7b6cfb9dad53bef44`,
bez scalenia jego gałęzi. Używana instalacja, jej konta/issuer/CA/epoka,
backupy i zadania O3 pozostają poza tym wykonaniem. Własny PG17 słuchał wyłącznie
na loopback; wszystkie konta i dane testów są syntetyczne.

## Powtarzalne kontrole lokalne

Komendy używają Python3.13, zależności `uv sync --project backend --locked`,
`PYTHONUTF8=1`, własnego `TEST_DATABASE_URL` do bazy `*_test` na PG17.
Hostowy klient backupu: `E8_3_POSTGRES_BIN=<katalog bin PostgreSQL17>`.
Windows wymaga jawnego prywatnego `--basetemp`; nie współdzielimy baz między
równoczesnymi zestawami. Role przygotowuje istniejący init-db.

| Zakres / polecenie | Rzeczywisty dowód lokalny |
|---|---|
| L0: commit intencji, trwały odbiorca po restarcie, crash po efekcie providera | PASS; brak ACK → 0 wywołań; niepewność zachowana; retry tego samego celu |
| `python -m pytest backend/tests/unit` | 1742 PASS/0skip,85,23s; osobne końcowe uruchomienie z jawnym scratch |
| `python -m pytest backend/tests/unit/test_deletion_ledger_contract.py backend/tests/integration/test_deletion_ledger.py --basetemp <nowy> -q` | 53 PASS:28unit/25PG, bez skipów,12,11s; podpisany cutoff + niezależny pin |
| `python infra/integration/rehearse_deletion_ledger.py --state <nowy>` | Końcowy runner53 PASS/0fail/0skip; lokalny receipt jawnie dirty_source=true na bazie615fb6b3 |
| Regresje E3/E4/E5/E6/E7 na head i osobno historyczne downgrade | 170 PASS,2 błędy konfiguracji metadata; po poprawce jawnego schematu app oba2 PASS |
| E8.4 purge/restore + E9 migration | 11 PASS/0skip,87,32s; własne credentials/PG17 |
| Mutacje w izolowanej bazie/procesie: ACK, outbox, cutoff-prefix | 3/3 wykryte; każdy właściwy test1FAIL/0error/0skip i pytest exit1; produkcyjny kod bez mutacji |
| E0/OpenAPI/schema/examples/linki | PASS:11schematów,98valid/35invalid,18scenarios,16Decimal,72normalizations,693linki |

Testy sprawdzają pusty upgrade, zapełnione0024/legacy unknown, downgrade0024
z zachowaniem dowodów i odmowę głębszego downgrade, faktyczne LOGINS oraz
ACL tabel/kolumn/funkcji. Stary CLI odmawia przed providerem; API/worker nie
uzyskują ścieżki operatora. Konkurencja obejmuje rollback sekwencji, blokadę
commitów, post-lock freeze, tokeny i wygaśnięcie lease. Nemesis zachowuje
preconditions/gate/release projekcji0024 przy markerze schematu0025.

## Macierz awarii

| Przerwanie lub błąd | Oczekiwany i sprawdzony wynik |
|---|---|
| Begin rollback / brak ACK begin lub provider intent | Brak osieroconego eventu; provider0; konto/job/event atomowe |
| Timeout/utrata wyniku po provider DELETE | Pending/uncertain; trwały job i exact cel; nowa próba z nową intencją/ACK, bez exactly-once |
| Spóźniony token starej próby | Nie zatwierdza nowego lease ani innego celu |
| Brak ACK provider result / confirm / purge intent | Następny etap odmawia; brak zakończenia |
| Błąd grafu purge lub rollback transakcji | Graf i event wyniku cofnięte atomowo; żadnego potwierdzenia sukcesu |
| Purge commit / utrata odpowiedzi / brak finalnego ACK | Idempotentne wznowienie; `ledger_complete=false` aż do trwałego ACK |
| Powtórzony eksport / restart odbiorcy | Ten sam prefiks idempotentny; SQLite FULL/WAL tylko jako niezależny testowy sink |
| Luka/zmiana/reverse/fork/obca kotwica lub receiver | Odmowa uwierzytelnienia, łańcucha lub semantyki |
| Zwykły/stary ACK jako cutoff, brak pin, obcy/stary fence lub zmiana scope/hash/MAC | Odmowa; cutoff ma oddzielną domenę i niezależny FencePin |
| Backup sprzed usunięcia → późniejszy delete → sink restart → rzeczywisty pg_dump/restore | Reconcile blokuje usunięte konto/generację/subject; inne konto zachowane; source frozen; ruch nieotwierany |

## Kompatybilność i dalszy odbiór

Stare migracje pozostają niezmienne; nowy wrapper wywołuje rzeczywisty pełny
łańcuch rodziców E9/E8/E7/E6/E4. Kontrakt mobilny/30dni i OpenAPI nie zmieniają
się. Testy dawnych migracji mają jawne osobne historyczne bazy0024; nie cofają
dowodów0025. Ich zamrożony testowy driver nie jest ścieżką produkcyjną.

Downgrade0025→0024 zachowuje ledger i bariery; starszy operator jest niezgodny.
Nie deklarujemy działającego rollbacku całego obrazu/instalacji. Rehearsal recovery
używa nowego uwierzytelnionego blokowania celu, zachowując oddzielny wcześniejszy
fixture i zakres odtworzenia posiłku A. Nie wykonuje ponownego, niechronionego
provider DELETE/purge po restore. B pozostaje zablokowane, source zamrożony.

| Otwarty warunek | Właściciel / artefakt i warunek wznowienia |
|---|---|
| Niezależny magazyn poza hostem, chronione klucze/transport/retencja | O3: odbiór zgodności batch/ACK/cutoff i odporności/restartu; bez tego WAITING_EXTERNAL |
| Fizyczne odcięcie starych procesów, provider credentials i issuance/ostatnich zapisów | O3: niezależny fence_id/hash/scope production i przypięty cutoff; sam podpis tego nie dowodzi |
| Odzyskanie kluczy, kotwicy i przypięcia backup_point | O3: sprawdzona procedura poufnego recovery oraz odczytu niezależnego prefiksu |
| Ponowne otwarcie niepustego źródła i provider/purge po restore | Osobny etap O2/O3 po odbiorze magazynu/fencing; ten kod nigdy nie autoryzuje reopen |
| APK/Room/UI i wspólna próba pełnego KO32/RPO/RTO | O1/O3: dokładny APK/head/receipty; obecne kontrakty i próba własnej PG nie są pełnym KO32 |

Niezależny końcowy przegląd:9/10, brak otwartych P0/P1/P2; reviewer osobno
uruchomił28unit kontraktu i1restart pin, diff--check PASS. SQL ledger SHA256:
`8f7ced9ba3df2558b422d76c06f163ed2b5c5a8f882b1d2d13af63318a1e76de`.
Dodatkowy head/historyczny E6 graph2/2PASS, zachowane bytes i kontoB.
Pełne testy runnerów180PASS/0skip; Ruff/format i uv build PASS.
Lokalny Docker/Keycloak/full Compose nieuruchomiony; rzeczywista pełna macierz
PostgreSQL/Keycloak/Android/Compose jest obowiązkiem zdalnego CI tego PR.

Najbliższe kroki: jeden PR, rzeczywiste8kontroli
aktualnego head/base, potem osobny odbiór koordynatora. Bez merge/wdrożenia.
