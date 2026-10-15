# Odbiór kontroli pakietu wydania O3 — 15.10.2026

Źródło `codex/devops-pakiet-wydania`; obraz próby z rzeczywistego commita
`a342fb9c991693a97e540db3e9cd5c7c8a96b95a`. Kod i instrukcja przygotowują odbiór
artefaktów; nie przeprowadzono produkcyjnego wdrożenia lub publikacji.

## Wykonane lokalnie

- Kontrola release.json zbiera osobne wyniki Androida, backendu, katalogu
  i kompletu odbiorów. Wymaga zgodnych commitów, immutable obrazu i sum plików.
- Android: rzeczywiste aapt i apksigner/Java potwierdziły package/version
  i podpis istniejącego APK validation0.8.10. Zmieniono bajt zasobu w osobnej
  kopii APK: weryfikacja podpisu odrzuciła plik. Oryginał pozostał zachowany.
- Próba ujawniła problem absolutnej ścieżki Unicode i logicznej lokalizacji SDK.
  Inspector używa katalogu roboczego APK i fizycznej ścieżki narzędzi.
  Po poprawce rzeczywisty odczyt i podpis PASS; test regresji polskiego katalogu.
- Zbudowano osobny obraz z VCS_REF wskazującym faktyczne źródło. Sprawdzenie
  OCI revision i uruchomiona bez sieci/sekretów sonda EXPECTED_REVISION PASS:
  `0024_e9_history_graph`. Aktywnego obrazu API nie podmieniano.
- Import istniejącego katalogu demo do osobnego tymczasowego SQLite PASS.
- Rzeczywisty próbny zestaw zwraca poprawne **BLOCKED**: validation nie jest
  regularnym APK; historyczny commit APK nie pasuje do nowo zbudowanego obrazu;
  nie dostarczono wymaganych odbiorów O1/O2/restore. Nie wygenerowano fikcyjnych
  receipt PASS w celu zamknięcia tych braków.
-15 nowych przypadków regresji; pełny zestaw infrastruktury tej niezależnej
  gałęzi116PASS, Ruff lint/format i E0 PASS. Po dołączeniu lokalnego utrzymania
  z main4fa2bc4 wykonano osobny wspólny przebieg: **129PASS**.

Dockerfile wspiera etykietę źródła; CI przekazuje rzeczywisty checkout SHA
i weryfikuje ją po buildzie. To źródło buildów, nie publikacja registry/CD.
Zdalne CI końcowego PR i scalenie są odrębnymi warunkami.

## Naprawa gotowości restore po błędzie CI

CI38759312001/head88160da zakończył local-integration failure w kroku rehearse
po poprawnym capture. Log nie zawierał przyczyny wewnętrznej; nie przypisujemy
jej automatycznie do później znalezionego wyścigu. Źródło oficjalnego obrazu
PostgreSQL potwierdza tymczasowy serwer inicjalizacyjny z listen_addresses=''.
Kontrolowany realny PG17 z opóźnionym init pokazał socket-ready/TCP-not-ready.
Poprzednia sonda socketowa mogła uruchomić restore przed końcem inicjalizacji.

W d81d27a sonda oczekuje na docelowy TCP127.0.0.1. Rzeczywista próba tego
warunku PASS; odtworzenie istniejącej kopii nowym kodem PASS16,879s, bez
zatrzymywania oryginalnej instalacji. Dołożono4regresje: init-only, bounded
timeout, redakcja błędu i neutralny JSON błędu z CLI. Wspólny zestaw **133PASS**.
Runtime d81d27a wdrożono lokalnie: pełne zadanie Windows17:29–17:30 PASS,
restore18,709s, stan konfiguracji/epoki/tożsamości i kontenerów zachowany.
Przy błędzie CI dostaje etap/klasę/exitcode, a komenda/SQL/traceback zostają
w prywatnym stanie. Nie pomijamy restore i nie zastępujemy failure wynikiem PASS.
Nowy końcowy head musi przejść własny pełny CI.

## Przygotowanie emulatora po kolejnym błędzie CI

Headf4c7428 zaliczył zdalny local-integration/restore, lecz android-device
przerwał przygotowanie offline z exit1 przed Gradle. Zweryfikowany artefakt
11985692815 zawierał wyłącznie boot1 i pięć zarejestrowanych usług; nie zachowano
etapu konkretnego polecenia. To nie był wykonany test APK ani jego regresja.

Przygotowanie idempotentnych ustawień sieci czeka teraz maksymalnie30prób
na poprawne wykonanie wszystkich poleceń i rzeczywistą utratę łączności.
Nie zmieniono wymagań offline ani nie dodano powtarzania testów aplikacji.
Neutralny setup-status/setup-attempts trafia do artefaktów także przy błędzie.
6/6 lokalnych testów Linux bez sieci PASS: również chwilowa odmowa polecenia
oraz trwała odmowa z boundedFAIL/Gradle NOT_RUN. Końcowy CI sprawdza realny AVD.

## Granice harmonogramu

Poprawiono rozpoznawanie wykonanych okien03/15, aby czas kończenia kopii nie
pomijał kolejnego terminu. Trwająca operacja zachowuje dowód poprzedniej kopii;
stan running nie jest sukcesem nowej i nie zamyka istniejącego incydentu.
Stary/brakujący poprzedni dowód lub operacja ponad45min nadal dają awarię.
Cztery dalsze regresje okien/DST/stale/progress: pełna infra **137PASS**.
Runtime eda8c46 wdrożono: pełny lokalny przebieg17:53/restore13,877s PASS,
config/epoka/tożsamości/containerIDs zachowane. Ponowne zadanie Windows17:54
zakończyło się0 bez zmiany receipt i bez drugiej kopii; due-check NOT_DUE.
Poprzedni head d5b844c ma realny zdalny device169/169,0fail/0skip, zgodny
digest artefaktu11985774635 i offline przed/po; nowy head potrzebuje własnegoCI.

## Dostawy niezbędne do rzeczywistego wydania

[Instrukcja i format](../../infra/integration/WYDANIE.md) podają pola manifestu,
neutralnych dowodów, komendy narzędzi i procedurę migracji/rollbacku. O1 dostarcza
regularny podpisany APK oraz odbiór Room/API/katalogu, O2 zgodność API/schematu
i zaakceptowaną strategię rollbacku. O3 składa rzeczywisty zestaw z ich dostaw.
Offsite, pełny restore z telefonem i skonfigurowany cel wdrożenia pozostają otwarte.

Pozytywny wynik checkera potwierdza spójność artefaktów i dostarczonych receipt;
nie weryfikuje samodzielnie prawdziwości opisanych w receipt prób ani nie nadaje
zgody na deployment. Akceptacja merytoryczna i końcowe wydanie pozostają jawne.
