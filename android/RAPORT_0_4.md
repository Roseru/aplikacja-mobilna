# Android 0.4.0 — importer E2 i obliczenia

Agent 1 / O1, 10 października 2026 r. Kod: [PR #1](https://github.com/Roseru/aplikacja-mobilna/pull/1), gałąź `codex/android-offline-racje`. Raport opisuje lokalne dowody Androida; recenzja, zdalne CI i pełny odbiór zespołowy są odrębnymi krokami.

## Rezultat

Pierwszy start bez konta i sieci importuje eksport E2 do Room. Użytkownik może wybrać jego produkty oraz zjedzone części racji, poprawić ilość i odtworzyć ekran bez utraty wartości. Nowy katalog nie zmienia już zapisanych spożyć. Zachowane są także dawne produkty i zestawy demonstracyjne, prywatne wpisy, profil, masa, kompletność dni, datowane cele i cała kolejka.

Pakiet: demo `47bdff67-e58b-5437-919b-ec00159afbc5`, release/schema/reader 1, 18 produktów / 1 racja / 18 komponentów / 1 źródło. Racja S-RG-1 pozostaje `unverified`, `complete=false`. Łącznie z poprzednim demo aplikacja pokazuje 33 produkty i 3 racje; dane MRE 2026 nie zostały dodane tym importem.

Źródło niezmienionych schematów, wektorów i eksportu: [`229a2b8`](https://github.com/Roseru/aplikacja-mobilna/tree/229a2b8). Wczytano również [aktualizację przekazania E2](https://github.com/Roseru/aplikacja-mobilna/blob/52f3547/docs/e2/INTEGRACJA_O1.md) z 10 października; poprawne znaczniki czasu z 1–6 cyframi ułamka sekund są zachowywane bez normalizacji pliku przed hashem.

## Wykonane kontrole

| Kontrola | Wynik i zakres |
|---|---|
| Build i lint | `assembleDebug`, `testDebugUnitTest` i `lintDebug` zakończone powodzeniem; lint: 0 błędów, 26 ostrzeżeń |
| JVM | 39 zaliczonych: 6 dotychczasowych, 6 wejścia Decimal, wszystkie 16 normatywnych wektorów nutrition_v1, 11 pakietu/JSON/gzip/schematu i kalendarza |
| Urządzenie API 35 | 26 różnych przypadków zaliczonych: 25 w pełnym przebiegu, ostatni SQLITE_FULL w osobnym powtórzeniu po naprawie konfiguracji próby. Nie jest to jeden zielony przebieg wszystkich 26 |
| Room | Rzeczywiste schematy 1/2/3 → 4, walidacja docelowego schematu przez Room; dla migracji 3 → 4 porównano wszystkie stare kolumny wszystkich tabel przed importem |
| Katalog | Staging niewidoczny dla ekranów, aktywacja i restart, no-op ponowienia, inna treść tego samego release/UUID+revision, starsza aktywacja po nowszej, zachowanie dawnych wersji i outbox |
| Obliczenia/snapshot | Części racji dają dokładnie 213 kcal, B/T/W 18,5/5,5/20,7; ilość 12,123456789123 zachowana po edycji/restartach. Napój w ml, nieznana energia i znane zero zachowane w Room |
| Awarie | Wstrzyknięte przerwanie przed commit staging/aktywacji; rollback i ponowienie. Osobna baza z ograniczeniem max_page_count rzeczywiście zgłosiła SQLiteFullException; aktywny katalog, dziennik i outbox zachowane |
| UI | Zwykły produkt, częściowa dawna racja, prywatny produkt, profil/waga, częściowa racja E2 z odtworzeniem aktywności i korektą pełnego snapshotu. Test profilu używa akcji dostępności przycisku pomiaru po przewinięciu i zamknięciu IME |
| Offline | Tryb samolotowy emulatora włączony przed instalacją testową i pierwszym startem; aplikacja nie ma uprawnienia INTERNET. Import korzysta z rzeczywistych assets APK |
| Bajty APK | Osadzony gzip: 3099 B, zgodny hash eksportu; JSON po rozpakowaniu 15691 B. Manifest i źródłowe schematy pozostają niezmienione |

Komendy: `:app:assembleDebug :app:testDebugUnitTest :app:lintDebug`, `:app:connectedValidationAndroidTest` oraz ostatnie powtórzenie z `-Pandroid.testInstrumentationRunnerArguments.class=pl.roseru.kalorie.CatalogStorageTest#actualSqliteFullDuringStagePreservesPreviousCatalogDiaryAndOutbox`.

Raporty generują się w `app/build/test-results/`, `app/build/reports/` i `app/build/outputs/androidTest-results/`. Testy urządzenia działają w `pl.roseru.kalorie.validation`; nie usuwają zwykłego dziennika. Dla rzeczywistego SQLITE_FULL limit ustawiono na sesji piszącej Room: PRAGMA wykonane na osobnej sesji odczytu nie ograniczały importu. SQLite przerywa transakcję przy FULL; test przechwytuje pierwotny błąd, zanim zewnętrzna próba rollbacku Room może zastąpić jego komunikat.

## APK i pakiet

- Wersja: `0.4.0`, versionCode 4, applicationId `pl.roseru.kalorie`, Room 4.
- APK debug: `app/build/outputs/apk/debug/app-debug.apk`; kopia do ręcznej instalacji: `output-apk/Racje-i-kalorie-0.4.0-debug.apk` w katalogu roboczym poza Git.
- SHA-256 APK: `d068c190ed068b7d2e91607d7e770e3a7a18f82b4c0e49ea8379b8ffbf5d12e2`.
- APK zainstalowano jako aktualizację zachowującą dane; ręcznie potwierdzono otwarcie ekranu dziennika na emulatorze API 35.
- SHA-256 gzip: `65f4aae8002fd5522d0edb4689e05682103b80fbe3e6dbc68f4bf02c645b2bef`.
- MergeAssets automatycznie rozpakowywał asset z końcówką `.gz`; wykrył to pierwszy przebieg urządzenia. Końcówka fizycznego pliku `.gz.bin` zachowuje oryginalne bajty gzip w APK. Manifest ma nadal logiczny kontraktowy path `base-pl.1.json.gz`.

## Granice tego etapu

Nie wykonano zabicia procesu w trakcie otwartej transakcji ani prób pobierania official przez HTTPS. Wykonano restart po zapisanym stagingu oraz kontrolowane wyjątki przed commitami; nie opisujemy ich jako testu twardego zabicia procesu. Próba braku miejsca ogranicza liczbę stron osobnej bazy i wywołuje prawdziwy błąd SQLite, bez zapełniania dysku użytkownika. Pełny KO-30 wymaga pozostałych prób i dostawy O2/O3.

Nowe dane katalogu i snapshoty E2 mają dokładne TEXT oraz BigDecimal. Stare REAL nie są przepisywane ani przedstawiane jako odzyskana precyzja. Prywatne produkty, cele, profil i masa nadal używają wcześniejszego zapisu. Porcje lokalne dopuszczają do 12 miejsc; przyszły adapter Quantity E0 do synchronizacji musi jawnie obsłużyć limit 6 miejsc. Kolejka nadal jest roboczym formatem lokalnym i nie trafia na API; nie ma kont, sieci, Gemini ani synchronizacji. Historyczne operacje outbox nie zostały zmienione.

Następny etap O1: analityka 7/30/90 dni z jawnymi brakami, datowanym celem i kompletnością dnia. O3 podłącza rzeczywiste komendy budowania/testów do CI; lokalne wyniki nie potwierdzają zdalnego CI.
