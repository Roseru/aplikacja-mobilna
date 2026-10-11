# Raport motywacji E8.1 + E8.2 - osoba 2

12 października 2026. Dostawa: `codex/backend-e8-motywacja-ranking`, [PR35](https://github.com/Roseru/aplikacja-mobilna/pull/35). Autor nie scala PR; odbiór integracyjny należy do koordynatora. Master wejściowy: `af8df9af9bfd32aa8145eac6114fdfc7261a8477`. Kod poddany końcowym testom: `44986a5986c778d0dd3f7529db155197940bb73b`; head integracji `3080de5a7e0d1c0c6a09cb56b36db2a811f2b2d2`, base `e93e38e02fed9663217b9036e5831cbc934e1baf`. Zwykły merge zmienił wyłącznie dokumenty; kod, migracje, kontrakty i testy są identyczne z 44986a5. Końcowy SHA dokumentacji i jego osobne osiem kontroli zostaną zapisane w opisie PR.

## Wynik i zgodność

Backend dostarcza regularity_v1, rangi, cztery odznaki z reaktywacją, trwałe prywatne projekcje oraz ranking ze świadomym opt-in i nieprzezroczystą paginacją live. Atomowy hook działa w savepoincie źródłowej mutacji przed receipt; rollback cofa również projekcje. Ograniczony porcjami worker odbudowuje dowolnie długą historię, rozpoznaje zamknięcie daty w zachowanej strefie oraz korekty, replay, purge i zmianę epoki po restore. Pochodne nie zastępują źródeł, brak danych pozostaje null, alternatywnych wariantów nie sumujemy.

[Decyzje](DECYZJE_MOTYWACJA.md), [interfejs projekcji](INTERFEJS_PROJEKCJI.md), [przekazanie O1](INTEGRACJA_O1_MOTYWACJA.md) i [konfiguracja O3](KONFIGURACJA_O3_MOTYWACJA.md) opisują reguły i integrację. Dodano migrację `0016_e8_motivation` po `0015_e7_ai`; opublikowana 0016 i stare 0001–0015 są niezmienne. Osobny LOGIN workera ma minimalne effective ACL, bez bezpośredniego odczytu dziennika/projekcji i zapisu punktów. API również nie zapisuje dowolnych punktów, odznak lub afirmacji.

Istniejące ConsentInput/Consent/ProfileRead, receipts, sześć encji wire v1, ACK i snapshoty zachowują zgodność. Nowy opcjonalny nagłówek istniejącego PUT zgód nie zmienia hasha dawnych żądań. Read, replay, energy-only i rebuild nie ustanawiają nowej afirmacji. E5 korzysta z tych samych źródłowych faktów SQL, zachowując kalendarzową klasyfikację pustych dat i wcześniejsze no_data/null.

## Dowody autora

- Pełne unit w dokładnym uv.lock: **1370 PASS**, 79,40 s, bez skips. Pełny właściwy przebieg PG17.11: **1041 PASS**, 1114,28 s, bez skips.
- Odrębne zakresy realnego PG/HTTP: 21 źródło/worker, 31 ranking/zgody, 59 E4 push/E5, 36 historia/restore/migracje, 35 poprawka afirmacji i 172 właściwych regresji dawnych etapów. Zakresy zachodzą na pełny zestaw; nie dodajemy ich do łącznej liczby.
- Rzeczywiste procesy CLI, restart i nadrabianie po braku procesu; hardened provision CLI dwukrotnie i odrębne SCRAM LOGIN, --status/--once, effective ACL oraz aktualność Alembic/ORM: PASS.
- 10001 źródłowych dat wag, batch 97, 104 wywołania i nowy zapis za checkpointem: pełne nadrabianie bez obcięcia; brak fikcyjnego DiaryDay/punktów. 10001 wersji celów plus zwykły przyjęty zapis 10002: brak limitu osi celu w Pythonie. Actual archive restore i nowa epoka: PASS.
- Ranking 10103 syntetycznych uczestników, 102 strony, remisy 1/1/3, głęboka kontynuacja bez nowej sesji, quota/TTL/ownership/epoch/generation, bariery konkurencji, opt-out i purge anchor: PASS.
- E0: 8 schematów, 95 valid, 35 invalid, 18 scenariuszy; Decimal, kompletność i normalizacje PASS. Ruff, format i diff check PASS. Końcowe E0 dokumentacji: 435 lokalnych linków PASS.
- Wheel/sdist z kodu 44986a5/head 3080: 139 plików pakietu zgodnych ze źródłem, zamrożone zasoby SQL obecne w sdist, 38 zależności zgodnych z lock i smoke instalacji `python -I`: PASS. SHA-256 wheel: `e28591eac869285abada6737fade6fa3bc7127af849f83ac54ba0b9d00090615`; sdist: `f7d3510ec99f5ba537a228b9290e89b7727860c415ec82463d527803bef4cd77`. Prywatne artefakty i logi pozostają poza Git.

## Niezależny odbiór i CI

Niezależny nieautor: **9,3/10, zero otwartych P1/P2**. Własne zamrożone źródło 44986a5, PG17, loginy i procesy: **1370 unit, 1041 PG oraz 44 unikalne własne oracles PASS**, bez skips. [Recenzja](RECENZJA_MOTYWACJA.md) zawiera manifesty, identyfikatory przypadków i niezależne red/green obu P2. Autorzy domeny, rankingu i migracji nie stanowią niezależnego odbioru. Odbiór mastera lub samego seam nie zastępuje runtime PASS.

[CI38183803047](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38183803047), exact head 3080de5/base e93e38e: **osiem success** — quality, contracts, local-integration, postgres, keycloak-pkce, android-build, android-device, ci-required. Odczytane logi: 1370 unit, 1041 PG, 28 Keycloak, 21 infra, 87 JVM i 86 device, bez skipped testów w raportach JVM/device. Wynik finalnego commita dokumentacji wymaga osobnego exact-head CI.

## Znalezione błędy i poprawki

Nieautor i autor odtworzyli dwa P2 i wykonali red/green:

1. Świeży świadomy PUT po restore, wykonany przed backfill, tracił afirmację podczas resetu starej epoki projekcji. Nowa operacja z aktualnym nagłówkiem uzgadnia starą projekcję przez istniejące e8_refresh(owner,[]) przed ustawieniem markeru, w tej samej transakcji. Legacy/replay/energy-only nie wykonują tego kroku; SQL0016 pozostaje niezmienione.
2. Puste minione daty E5 miały closed=false po przejściu na wspólne source facts. Przy braku zachowanej strefy DiaryDay przywrócono kalendarzowe closed dla dat minionych; znana historyczna strefa i nieprzedstawialny termin nadal są wiążące. Kompletność/in_goal/null, średnie i punkty nie zmieniły reguł. Trzy realne PG dla okien 7/30/90 oraz dwa unit potwierdzają poprawkę bez tworzenia źródeł podczas odczytu.

Wcześniejsze niepełne przebiegi i CI6606 nie były PASS. CI6606: 1033/1038 PG, pięć porażek historycznych fixtures/table-set/head; quality przeszło unit/infra/installed smoke, lecz Docker ECR odmówił 429. Poprawiono wyłącznie przygotowanie testów dla nowej migracji: strict helper usuwa dowiedzione untouched pending placeholders przed historycznym downgrade, expected set uwzględnia sześć tabel E8, historyczne head i bootstrap są jawne. Nie osłabiono nonempty downgrade ani źródłowych guardów. Nowe pełne CI1041 przeszło; nie sumujemy powtórek lub błędów harnessu.

## Granice przekazania

Duża historia testowa ma syntetyczne źródła. Bulkseed znanych UTC i osi celu pomija wyłącznie dawne powtarzane per-row guardy, po walidacji całej osi i dat; guardy wracają przed normalnym przyjętym zapisem. Wszystkie E8/FK/CHECK/owner/revision constraints pozostają. Rankingowy bulkseed punktów sprawdza zapytania/paginację, a nie naliczanie z 10103 dzienników. Pełnohistoryczne agregacje mogą używać work_mem/spill; porcje nie są limitem historii.

O1 osobno integruje APK/Room, offline UI, cache, nowe odczyty i świadomy nagłówek. O3 osobno odbiera provision, deployment, monitoring, backup/restore i RPO/RTO. E8.3 ma rezerwację 0017 i własny izolowany etap; dokładnie jeden zbiorczy Nemesis SourceProjection będzie właścicielem całego zbioru challenge locks UUID ASC. W tej dostawie nie podłączono pustego Nemesis. E8.3/4, E9, Google, billing, produkcja i automatyzacje są poza zakresem. Główny historyczny E4 checkout oraz Random Data zachowano. Własny autorowy PG i procesy CLI zatrzymano po odbiorze; nie zatrzymywano usług innych etapów.
