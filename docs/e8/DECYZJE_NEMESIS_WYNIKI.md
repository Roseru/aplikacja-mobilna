# Decyzje E8.4: projekcje i wynik Nemesis - osoba 2

Podstawa: 76546405d2c549278a9826c0223204e98698015c, master blob 3bb0ac4e366aa8983585a25d77da416aea43cfde. Gałąź codex/backend-e8-nemesis-wyniki. Migracja 0021 po odebranej 0020; 0001–0020 nie zmieniamy. To kontrakt implementacji, nie dowód odbioru.

## Trwałe fakty i inicjalizacja

Klucz dnia obejmuje challenge, immutable role inviter/invitee, accepted local_date oraz regularity_v1. Każda z obu stron dostaje wszystkie 7/30/90 dat. Granice UTC, maturity i resolver revision powstają przy accept. Prywatne NUMERIC intake, historyczne maintenance E i reprezentant masy wraz z source revisions są utrwalane; brak pozostaje null. Fakty kompletności i bonusu pochodzą ze wspólnego e8_day_facts, e8_day_facts zwraca zone/matures_at z DiaryDay lub null bez niego; maturity Nemesis pochodzi wyłącznie z utrwalonych accepted boundaries także dla weight-only. Masa używa utrwalonych przedziałów UTC dnia, a ostatni pomiar wybiera (occurred_at, UUID).

Proof seed jest oddzielny od pustych faktów. Brak proof lub pełnych zgodnych dat odmawia odczytu 503, nie wytwarza zer. Accept inicjalizuje obie strony wewnątrz SQL lifecycle przed slotami i receipt; failure cofa całe accept. Legacy accepted nie są uzupełniane z późniejszego dziennika.

## Transakcje i blokady

W source pozostaje caller-owned savepoint oraz account → counter → wszystkie challenges UUID ASC → projekcje. Jeden NemesisSourceProjection posiada pełny plan. Discovery konserwatywnie obejmuje wszystkie current-epoch accepted wyzwania właściciela z provisional result; po locks ponownie odrzuca zakończone final/cancelled i niewłaściwe generations, dzięki czemu przeniesione/usunięte wagi i pominięcie dat przez direct caller nie zawężają korekty. Po lock nie odkrywamy nowych IDs.

Jeden jawny SQL orchestrator przyjmuje provenance i exact source plan, rewaliduje generation/epoch, aktualną source revision oraz source position. Pozyskuje ten sam pełny lockset, wywołuje e8_refresh dokładnie raz i zapisuje Nemesis wewnętrznym writerem z tym samym q. Caller nie podaje q lub punktów. Python apply weryfikuje sesję, transakcję, savepoint, plan i konkretne zwrócone q; nie zapisuje SQL. Plain refresh pozostaje dla braku Nemesis extension. Błędy wycofują źródło, motivation, projections, change i receipt razem.

Finalizer bierze challenge, rewaliduje privacy i zegar > deadline, zapisuje oba role results i status atomowo. Jego dane wejściowe obejmują wyłącznie projections, immutable terms i minimalne privacy fences. Brak FK wyników do user_accounts chroni przed ukrytym odwróceniem lock order. Finalizacja na deadline jest niedozwolona; qualified source q <= deadline pozostaje uwzględnione po późniejszym COMMIT.

## Odczyt, prywatność i zgodność

Statistics używa jednego zablokowanego spójnego snapshotu. Account locks obu uczestników są sortowane przed challenge; fresh JWT/principal, oba generations i installation/control epoch oraz status są ponownie sprawdzane. Pending nie zawiera zerowych self/opponent/outcome. Ready provisional pochodzi z dojrzałych projections; final z trwałego result. Oddzielna read revision nie zmienia sync H lub starych receipts.

Metric hidden to wyłącznie state; insufficient_data ma null i właściwy count; available zawiera kanoniczny signed percentage i count, dla masy również skrajne daty. Średnia deficytu to średnia dziennych procentów, z rounding HALF_UP dopiero na końcu. SQL sumuje exact NUMERIC ułamki, a referencja Python stdlib Fraction; codzienne dzielenie ze skończoną precyzją nie rozstrzyga końcowych remisów. Dopiero finalny integer div/mod tworzy jednostki10^-12 i kanoniczny signed output. Właściwy odbiór22d opisuje RECENZJA_POPRAWKI_SREDNIEJ_NEMESIS.md. Zero jest kanonicznym stringiem "0". Brak danych i brak kcal nie są zerem. Opcjonalne zakresy wynikają z exact accepted terms.

Cancel, deletion i nowa epoka natychmiast odcinają statystyki. Purge usuwa projections/results obu stron i peer snapshots pod istniejącym scoped context. Restore nie seeduje starego challenge. No-store dotyczy sukcesów oraz wszystkich błędów. V1 wire, source hashes, sync receipts, sześć encji i historia pozostają zgodne.

## Gate i dostawa

Deploy pozostawia capability disabled. Aktywacja wyłącznie przez zaufanego operatora DB (nie właściciela konta lub admin JWT) wymaga rzeczywistych zgodnych schema/initializer/projector/finalizer i bieżącej epoki oraz skutecznych ACL; testowe revision pairs lub env nie wystarczają. Finalizer otrzymuje osobną minimalną rolę, lifecycle worker nie dziedziczy jej uprawnień. Worker ma bounded fair discovery, once/restart/backlog i schedule minutowy do osobnego wykonania O3.

Główny wykonawca E8.4 posiada SQL projections/lifecycle/source, migrację, modele oraz integrację Python i globalne contracts. Subagent contract posiada schemas/aggregates i przekazanie O1; sql_audit analizuje blokady i otrzyma wydzielone statistics/finalizer resources; integration_tests posiada wyłącznie nowe testy i własny PG55523/HTTP55533. Niezależny nieautor odbierze coherent freeze na innych zasobach. O2-027 jest jedynym wpisem wykonawcy; koordynator scala po niezależnym odbiorze i ośmiu current-head/base CI.
