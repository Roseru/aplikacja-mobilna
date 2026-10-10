# Android 0.5.0 — lokalna analityka

Agent 1 / O1, 10 października 2026 r. Gałąź `codex/android-analityka` wydziela WF-10 / UC-09. Zależy od Androida 0.4, commit `20f474e` w [PR #1](https://github.com/Roseru/aplikacja-mobilna/pull/1), jeszcze poza main. Nowy PR porównuje się z `codex/android-offline-racje`, aby recenzja obejmowała tylko analitykę. Najpierw należy odebrać/scalić PR #1, następnie skierować PR analityki na aktualny main, zachowując zwykłą historię Git i ponownie sprawdzając integrację. Nie scalono samodzielnie wcześniejszego PR.

## Zachowanie

- Zakładka Postępy: okres 7/30/90 dat kalendarzowych, poprzedni/następny okres, powrót do dzisiaj. Kcal/B/T/W i pomiary wagi mają wykresy oraz wartości tekstowe w historii. Dotknięcie daty otwiera jej rzeczywisty dziennik. Okres, miara i nawigacja przetrwają odtworzenie aktywności.
- Dodatni cel obowiązujący danego dnia jest oceniany według `goal_band_v1`, ±10% włącznie, na dokładnej sumie przed prezentacją. Zachowane są cele sprzed okna; przyszłe wersje nie zmieniają historii.
- Efektywna kompletność jest wspólna dla dziennika i analityki: deklaracja, obecne składniki, dodatnia i całkowicie znana energia. Pokrywa pięć normatywnych wektorów dni E0. Doprecyzowano wcześniejszy dziennik, który nie wykluczał pozycji z brakującymi kcal.
- Średnia jest liczona osobno dla każdego pola z kompletnych dni o znanej wartości. Braki nie stają się zerem. Wynik podaje własną liczbę dni; brak pomiaru/spożycia pozostaje brakiem. Dzień niepełny ma widoczną znaną część, bez oceny deficytu czy celu.
- Waga: ostatni rzeczywisty pomiar daty według UTC, przy remisie ID; licznik wszystkich nieusuniętych pomiarów. Zmiana masy wymaga dwóch dat w oknie. Nie interpolujemy ani nie przenosimy pomiarów.
- Odczyty Room są ograniczone do zakresu i właściciela, pomijają tombstones i reagują na zmiany. Sam odczyt nie zapisuje kolejki. Room pozostaje 4, bez zmiany schematu i migracji.

## Walidacja

- Build debug, 51 testów JVM (39 wcześniejszych i 12 analityki), lint 0 błędów / 26 ostrzeżeń: zaliczone.
- Testy urządzenia API 35: pełny końcowy przebieg 31/31, 0 błędów i 0 pominięć. Wcześniejszy przebieg 30/31 ujawnił brak oczekiwania testu UI na odczyt nowego okresu; po poprawce wykonano cały zestaw ponownie.
- Nowe przypadki Room: zakres/właściciel/tombstones/historyczne cele, aktualizacje Flow po edycji/usunięciu/ważeniu, restart i zachowana kolejka, brak energii po wcześniejszej deklaracji.
- Nowe UI: 7/30/90, wybór makra i odtworzenie aktywności, starsze okno oraz otwarcie dnia; rzeczywiste historyczne spożycie i waga offline.

Komendy: `:app:assembleDebug :app:testDebugUnitTest :app:lintDebug` oraz `:app:connectedValidationAndroidTest`. Testy urządzenia używają oddzielnego `pl.roseru.kalorie.validation`, bez kasowania zwykłego dziennika. Raporty w `app/build/test-results/`, `app/build/reports/` oraz `app/build/outputs/androidTest-results/`.

## Artefakt i ograniczenia

APK 0.5.0, versionCode 5, applicationId `pl.roseru.kalorie`; lokalny artefakt poza Git: `output-apk/Racje-i-kalorie-0.5.0-debug.apk`. SHA-256: `be5937edc1344fc7dec1d3cbd678288d11fd13bdc0691df2138ed2cea7f6c3a6`.

APK zainstalowano jako aktualizację bez kasowania danych. Potwierdzono tryb samolotowy i wersję 0.5.0. Ręcznie obejrzano podsumowanie i przewijane wykresy w motywie jasnym/ciemnym oraz podsumowanie przy skali tekstu 130%; przywrócono skalę emulatora 100%. Nie jest to odbiór wszystkich urządzeń ani pełny audyt dostępności.

Analityka jest lokalna; ekran jawnie informuje, że synchronizacja nie jest podłączona. Nie ma zapotrzebowania wyliczonego przez AI, rywalizacji ani naliczania osiągnięć. Cel nie jest utożsamiany z zapotrzebowaniem czy deficytem. Zasady Decimal, legacy REAL, katalogu demo oraz braki odbioru KO-30 pozostają zgodne z [raportem 0.4](RAPORT_0_4.md). Wyniki lokalne nie potwierdzają zdalnego CI ani zatwierdzenia/scalenia PR. Konta/sync wymagają dalszej dostawy O2/O3.
