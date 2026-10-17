# Macierz migracji Androida dla O3 — 17 października 2026

Autor: agent 1/O1. Odpowiedź na O3-059, O3-062 i O3-063.
Gałąź: `codex/android-migracja-narzedzi`, utworzona z main
`a6e239558a4ab664e3f9d3b6635657876878b412`.

Status: **kandydat do kwalifikacji**. Ten commit dostarcza wybór wersji,
źródła i plan odbioru. Nie zmienia konfiguracji Gradle/CI ani aplikacji.
POM-y potwierdzają istnienie artefaktów, nie poprawność całej aplikacji.
Wdrożenie migracji nastąpi po kolejce PR61→64→73→96→105 i dołączeniu
ówczesnego main zwykłym merge do tej gałęzi, z zachowaniem historii.

## Wybrany zestaw

| Element | Obecny zestaw | Kandydat migracji |
|---|---|---|
| Android Gradle Plugin | 8.9.2 | **9.1.1** |
| Gradle wrapper | 8.11.1 | **9.3.1**, dystrybucja bin |
| Kotlin/KGP | 2.1.20, osobny kotlin-android | **2.4.21**, built-in Kotlin AGP z jawnym podniesieniem KGP |
| Compose compiler plugin | 2.1.20 | **2.4.21**, ta sama wersja co Kotlin |
| KSP | 2.1.20-1.0.32 | **2.3.12**, KSP2 |
| Room runtime/ktx/compiler | 2.7.2 | **2.8.5**, wspólna wersja wszystkich artefaktów |
| Compose BOM | 2025.04.01 | **2026.09.00**, implementation i androidTestImplementation |
| compileSdk | 35 | **37** |
| SDK Build Tools | CI35.0.0; lokalny aapt35.0.1 | **36.0.0**, jawnie wspólne dla kompilacji i pakowania |
| JDK uruchamiający Gradle w CI | 17 | **17**, dystrybucja Temurin zgodnie z workflow |
| Java/Kotlin bytecode | 17 | **17** |
| minSdk / targetSdk | 26 / 35 | **26 / 35**, bez zmiany polityki wspieranych urządzeń |
| Urządzenie pełnych testów CI | API35/x86_64 | **API35/x86_64**, offline przed i po |

Lifecycle2.8.7, Navigation2.8.9, Activity1.10.1, DataStore1.1.4,
AppAuth0.11.1 oraz pozostałe zależności spoza tej macierzy zachowujemy
w pierwszym odbiorze, o ile metadane nie wykażą konkretnej niezgodności.
Po integracji zdjęć zachowujemy również ExifInterface1.4.2.
Każda wymuszona zmiana wersji dostaje uzasadnienie i aktualizację tej tabeli.
Nie przenosimy zbiorczo dziewięciu aktualizacji z PR81 bez analizy.

## Dlaczego ten zestaw

- [AGP9.1.1](https://developer.android.com/build/releases/agp-9-1-0-release-notes)
  obsługuje API37; wymaga Gradle9.3.1, Build Tools36.0.0 i JDK17.
- [Tabela KGP](https://kotlinlang.org/docs/gradle-configure-project.html)
  obejmuje dla2.4.20–2.4.21 Gradle7.6.3–9.7.0 i AGP8.5.2–9.3.1.
  Wybrany Gradle9.3.1/AGP9.1.1 mieści się w obu zakresach.
  Sam domyślny KGP2.2.10 z AGP nie jest docelowym kompilatorem tej migracji.
- [Compose compiler](https://developer.android.com/develop/ui/compose/setup-compose-dependencies-and-compiler)
  ma wersję Kotlin; Compose1.12 wymaga compileSdk37 i AGP9.
- [KSP2.3.12](https://github.com/google/ksp/releases/tag/2.3.12)
  wymaga AGP co najmniej8.12; wybrany9.1.1 spełnia to minimum.
  Zgodność procesora Room z wybranym kompilatorem sprawdzamy rzeczywistym KSP/build.
- [Room2.8.5](https://developer.android.com/jetpack/androidx/releases/room)
  jest stabilny. Minimum API23 z linii2.8 mieści się w naszym minSdk26.
  Nowe zachowanie zapytań po zamknięciu bazy wymaga szczególnego sprawdzenia
  cleanup testów i zakresów korutyn; nie ukrywamy takich błędów retry.

17.10 wykonano HTTPS GET publicznych POM-ów Kotlin2.4.21, KSP2.3.12,
Room compiler2.8.5 i Compose BOM2026.09.00; wszystkie HTTP200, dokładne
wersje sprawdzone w XML. Bez pobrania binarnych dystrybucji lub instalacji SDK.

Oficjalny [SHA-256 Gradle9.3.1 bin](https://services.gradle.org/distributions/gradle-9.3.1-bin.zip.sha256),
pobrany17.10 i sprawdzony jako64 znaki hex:

```text
b266d5ff6b90eada6dc3b20cb090e3731302e553a27c5d3e4df1f0d76beaff06
```

## Zmiany implementacyjne O1 po kolejce PR

1. Zaktualizować wersje i wrapper jednym spójnym etapem. Zachować weryfikację
   dystrybucji, standardowy cache i jawne logi błędów konfiguracji.
2. Zastosować [migrację built-in Kotlin](https://developer.android.com/build/migrate-to-built-in-kotlin):
   usunąć plugin `org.jetbrains.kotlin.android`, jawnie ustawić KGP2.4.21
   w classpath według instrukcji AGP, pozostawić Compose compiler2.4.21/KSP2.
   Zastąpić `android.kotlinOptions` przez `kotlin.compilerOptions`/JvmTarget17.
   Dodatkowe Kotlin sourceSets standard/validation/liveReceipt zarejestrować
   jako katalogi Kotlin; nie zgubić separacji zwykłego APK i drivera opt-in.
   Nie wyłączać built-in Kotlin lub nowego DSL, aby ominąć migrację.
3. Zachować applicationId, kanał validation, klucze podpisu development,
   wersjonowanie, API35 urządzenia i publiczną konfigurację API/CA.
   Sam upgrade bibliotek nie podnosi wersji schematu Room.
4. Nie dodawać fallbackToDestructiveMigration, clear/uninstall/wipe ani
   wyłączenia kontroli AAR. Konflikt schema identity lub wygenerowanego kodu
   musi mieć ustaloną przyczynę i zgodną ścieżkę zachowania danych.

## Dostawa O3 i kryteria odbioru

O3 może przygotować instalację `platforms;android-37` oraz
`build-tools;36.0.0` i kontrolę SHA wrappera. Zmianę wspólnych zmiennych
`ANDROID_COMPILE_SDK`/`ANDROID_BUILD_TOOLS` w obu jobach łączymy z gotowym
kodem migracji O1. Do tego czasu działający workflow zachowuje35/35.0.0.
Nie zmieniamy obrazu emulatora na37 tylko dlatego, że kompilujemy przeciw37.

Odbiór docelowego head obejmuje:

1. Assemble debug, validation i domyślnego testAPK, lint oraz pełne JVM obu
   wariantów. Zapis rzeczywistych logów także przed XML. Wynik zależności
   potwierdza dokładnie jedną wersję Kotlin/Compose compiler/KSP/Room/BOM.
2. Wszystkie testy urządzenia API35, bez pominięć i automatycznego retry.
   Brak sieci potwierdzony przed/po; przygotowanie emulatora rozliczane osobno.
3. Wszystkie ścieżki migracji Room oraz otwarcie istniejącej bazy bieżącego
   wydania: prywatny baseline poza Git/OneDrive, install-r, identyczne stare
   kolumny wszystkich tabel, historyczne posiłki/cele/waga/zdjęcia/outbox,
   FK clean i zachowane własności kont. Dokładna liczba tabel według schematu
   po integracji105, nie założona na podstawie starego main.
4. Zgoda na analizę i jej reset, podgląd/wysyłka, formularze Nemesis,
   edycja racji, klawiatura/Done, ciemny/jasny motyw i duża czcionka.
   Osobno brak drivera/bramki obserwacji w zwykłym APK.
5. Własne osiem kontroli CI po integracji oraz osobny CI main po merge.
   Nowe APK mają commit, wersję i SHA-256; stare artefakty/CI nie zaliczają
   nowej konfiguracji. Dopiero wtedy rozliczamy zastąpione PR81/82.

Aktualny odbiór tej dostawy: dokumentacja, oficjalne metadane i kontrola E0/diff.
**Build/KSP/JVM/native kandydata: NOT_RUN.** Późniejszy zielony CI dokumentacji
wykonujący stary zestaw nie kwalifikuje powyższej macierzy. Realny APK/API,
Gemini, release i KO32 zachowują osobne kryteria.
