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
  suma przypadków jest innym przebiegiem i wymaga własnego wyniku.

Dockerfile wspiera etykietę źródła; CI przekazuje rzeczywisty checkout SHA
i weryfikuje ją po buildzie. To źródło buildów, nie publikacja registry/CD.
Zdalne CI końcowego PR i scalenie są odrębnymi warunkami.

## Dostawy niezbędne do rzeczywistego wydania

[Instrukcja i format](../../infra/integration/WYDANIE.md) podają pola manifestu,
neutralnych dowodów, komendy narzędzi i procedurę migracji/rollbacku. O1 dostarcza
regularny podpisany APK oraz odbiór Room/API/katalogu, O2 zgodność API/schematu
i zaakceptowaną strategię rollbacku. O3 składa rzeczywisty zestaw z ich dostaw.
Offsite, pełny restore z telefonem i skonfigurowany cel wdrożenia pozostają otwarte.

Pozytywny wynik checkera potwierdza spójność artefaktów i dostarczonych receipt;
nie weryfikuje samodzielnie prawdziwości opisanych w receipt prób ani nie nadaje
zgody na deployment. Akceptacja merytoryczna i końcowe wydanie pozostają jawne.
