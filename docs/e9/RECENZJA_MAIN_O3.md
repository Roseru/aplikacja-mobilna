# Uzupełniający niezależny odbiór scalonego E9

13.10.2026. Niezależny nieautor rzeczywistego runtime Agenta2; zakres uzupełniający, bez pisania produktu. Zamrożony scalony source: `2b4073e05d800fe3abc2388c17308323adf5ed56`, PR54. Czysty detached checkout `e9-merged-review`; własny venv CPython3.13.13, `uv sync/run --locked --offline`. Źródła/SQL/testy autora pozostają nietknięte, brak publikacji lub merge.

**Sprawdzony zakres PASS, brak zidentyfikowanych otwartych P1/P2 w poniższych seams. Ocena uzupełniającego zakresu: 9,3/10.** Nie jest to nowa ocena całego E9, pełny PG, E9/R, main CI, Android/O1, publiczny Keycloak/TLS, Google/live, rollout lub produkcja. Nie przenosimy review mastera lub prywatnego prototypu do dowodów scalonego runtime.

## Faktycznie wykonane próby

1. Istniejące istotne unit E9 (rules/schema/provider): **56 PASS, 3,24 s**, zero failures/errors/skips. To samodzielnie uruchomiona właściwa regresja autora, oddzielna od nowych oczekiwań recenzenta.
2. Trzy własne nowe oracles rzeczywistego PG17/HTTP: **3 PASS, 23,56 s**, zero failures/errors/skips.
   - Signed synthetic JWT/JWKS + production factory, real API LOGIN i źródła przez rzeczywisty sync HTTP:14 kompletnych dat/kcal2810/historicalE2700/cztery pomiary80. Sam true wyraża requested, nie effective. Świadoma afirmacja uruchamia effective; nowy ranking-only PUT z true resetuje notice/baseline/effective. Replay wcześniejszego udanego affirmation receipt zwraca200, lecz pozostawia effective=false; nowy klucz ze starą revision daje409. Nowa osobna afirmacja z aktualną revision działa. Odczyt/PUT/retry nie utworzyły żadnego provider attempt.
   - Własna świeża0023: zmieniono wyłącznie prywatny guard source_in_transaction na true i podrobiono jego stored hash. Actual upgrade0024 odmawia literalnym parent Nemesis contract drift; wersja pozostaje0023 i nie powstaje release0024. Dowód, że rehash stored digest nie legalizuje obcego actual prosrc. Nie modyfikowano pakietowych SQL.
   - Własny ready2810 utworzony ze źródeł HTTP i przetworzony przez rzeczywisty Runner/mock subprocess. Świadoma aktywacja Nemesis dotyczyła tylko tej prywatnej bazy. Prywatna błędna wartość manifestu projectora powoduje manual accept503 i identyczny snapshot energy_versions/axis/receipts/changes/H/nullSyncChanges/projections; nie ma częściowego E lub receipt. Resolver jutra pozostaje2700. Rzeczywisty worker LOGIN nie ma EXECUTE e9_apply.
3. Ostatni przypadek rozszerzono o powrót właściwego prywatnego manifestu i ponowiono tylko ten zmieniony zakres: **1 PASS, 2 deselected, 16,97 s**. Ta sama niewycofana ready propozycja po usunięciu faultu daje200. Powstaje dokładnie jedna nowa wersja/receipt/energy_change; E dnia bieżącego pozostaje2700, jutro2810 i effective_from jutro. GoalVersion cały JSON/kolumny pozostają identyczne, punkty/kompletność/in_goal Nemesis nie zmieniają się, ostatni SyncChange jest SQL NULL. To dowód daty i zachowania historii po rollback, nie dodatkowy czwarty unikalny test.

Nie sumujemy retry do liczby przypadków: zakres ma56unit autora + trzy własne różne oracles. Nie ponawiano pełnej regresji produktu po wyniku green.

## Odczyt krytycznych połączeń

Przeczytano aktualne AGENTS, raport E9, niezależny raport autora dostawy, przekazanie O1/O3, schematy i SQL0022/23/24. Requested/effective jest celowo związane z consent_revision i oddzielnym notice; historyczny receipt może zwrócić historyczną odpowiedź, bez reaktywacji aktualnej afirmacji. Klient musi po PUT odczytać state, bez automatycznej energii z ekranu rankingu.

Resolver004 zachowuje explicit history_correction i graf dat, deduplikuje wyłącznie zwykłe klony identycznego artefaktu; literalne10 parent hashes odcinają rehash drift. Własne próby nie powtarzają wszystkich rozgałęzionych korekt grafu lub backfill — wcześniejszy raport jest oddzielnym dowodem, nie naszym wynikiem.

Nowy e9_apply jest prywatny (ACL bez PUBLIC/API/worker EXECUTE), kwalifikuje faktyczny version/counter xmin z bieżącej transakcji i używa DB q pod kompletnymi challenge locks. Sam konstruuje null marker i energy_change, bez przyjmowania source ticketu lub zmiany starej wire encji. Runtime manifest weryfikuje projector; błąd cofa również nowe E/pozycję/receipt. Nowy opt-in sync energy_estimates jest osobnym rozszerzeniem ze signed scope; nie twierdzimy, że w tej recenzji wykonano pełny recovery/token matrix.

## Środowisko, ograniczenia, cleanup

Każdy nowy PG zakres korzystał z własnego oznakowanego fixture kontenera PG17/SCRAM i świeżych *_test baz; nie współdzielono klastra z rodzicem, autorem lub usługami użytkownika. Zegar E8 był kontrolowany wyłącznie w prywatnym fixture, E9 zastosowanie korzysta z rzeczywistego DB clock. Iniekcje dotyczyły prywatnych stanów/funkcji bazy i miały ownership/cleanup; żadnego źródła produktu nie edytowano. Oba własne kontenery zakończyły label-verified finally cleanup, role worker testowego usunięto po dispose. W końcowym filtrze wspólnej etykiety widoczny jest jeden inny kontener; nie usuwano go i nie przedstawiamy wspólnej etykiety jako wyłącznej własności recenzenta. Checkout był czysty przy zamrożeniu i diff-check PASS; na końcu rodzic rozpoczął autoryzowaną publikację docs (PLAN_PRAC i ODBIOR_MAIN_O3). Recenzent nie zmienił tracked plików; runtime/schema/testy nadal freeze2b407. Bez watchers lub automatyzacji.

Worker LOGIN helper ma fixture membership z SET ROLE dozwolonym; dowód powyżej dotyczy konkretnego braku EXECUTE apply i rzeczywistego przetwarzania, nie produkcyjnego hardening noSETROLE. JWT jest syntetyczny podpisany, nie Google lub produkcyjny Keycloak. Własny wheel/installed-I nie był budowany. Ukryte raw logs/credentials/XML są poza Git. Dwa ostrzeżenia: istniejąca Starlette deprecacja oraz unknown integration marker przy imporcie fixture z prywatnego pliku poza pytest ini; brak skip lub zmian oczekiwań.

Prywatne artefakty:

- e9-merged-unit-review.xml SHA256 `0bccc452195b611dbf000faa734e4a406c214d1f6ca4eb5880ea170cab28fafb`
- e9-merged-independent-review.xml SHA256 `e1471bc8fad5e7d1e5b1601fd94d78a8030647c5898c7bdabe3cedb1ccee6fdc`
- własny finalny plik e9_merged_independent_probes.py SHA256 `ad80d252b80d8d8eeedb20a921d25bdcdaf47deca997906385eb6d191dc3e0c3`
- rozszerzony apply XML SHA256 `f44a0c72d17b77b3973f99a0803bec9cd33699ef6e2f9bec70daf83bad08a19a`

Raport ten nie zamyka wymaganej odrębnej kontroli zdalnego main CI lub pełnegoE9/R.
