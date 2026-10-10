# Poprawki po recenzji Androida

## PR #1 — kompletność energii, 10 października 2026

Odczytano [review O2](https://github.com/Roseru/aplikacja-mobilna/pull/1#pullrequestreview-5479214773) do 20f474e. Poprawka jest na właściwej gałęzi codex/android-offline-racje, w Room 4, bez przenoszenia całego zależnego etapu analityki.

Dziennik, repozytorium i przycisk potwierdzenia korzystają ze wspólnej reguły completeDiary: deklaracja, co najmniej jeden składnik, dodatnia suma oraz znana energia wszystkich pozycji. Znana dolna granica nie wystarcza. Dodanie pozycji bez kcal unieważnia efektywną kompletność; deklaracja pozostaje zapisana i można ją wyłączyć.

Pełny assembleDebug/testDebugUnitTest/lintDebug/connectedValidationAndroidTest PASS: 40 JVM i 28/28 urządzenia API 35, zero błędów/pominięć. Lint 0 błędów, 26 ostrzeżeń, 1 informacja. Nowy test JVM obejmuje wszystkie pięć wektorów dnia E0. Dwie próby urządzenia potwierdzają zmianę efektywnego stanu, odrzucenie ponownej deklaracji bez dopisania outbox, rzeczywiste ponowne otwarcie bazy oraz natychmiastową aktualizację UI i odtworzenie aktywności. Cały wcześniejszy zestaw, migracje i SQLITE_FULL też zaliczony w tym jednym przebiegu.

Nie zmieniono schematu/wersji aplikacji ani danych użytkownika. Zwykły zainstalowany APK pozostaje 0.7; testy używają oddzielnej instalacji validation. Wynik nie zamyka formalnej recenzji; wymagany ponowny odbiór O2 i mobilne CI O3. Odbiór zależnych PR pozostaje osobny, bez force-push lub samodzielnego merge.
