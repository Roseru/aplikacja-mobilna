# Android — Racje i kalorie

Wersja `0.7.0` dodaje przygotowanie bootstrapu E3 oraz niezmienne wersje lokalnych celów. Rejestr właścicieli i ochrona zapisu pozostają z 0.6; Room 6 zachowuje dotychczasowe wartości i kolejkę. Ekrany nadal działają jako gość bez konta i internetu, z Postępami 7/30/90 dni. Logowanie i HTTP nie są jeszcze podłączone.

## Co zawiera

- Jasny i ciemny motyw oraz wybór zgodny z systemem, zapisany w DataStore.
- Dziennik według dni, wybór daty, suma kcal i B/T/W oraz realizacja celu.
- Wbudowany katalog: 15 dawnych produktów oraz 18 produktów pakietu E2; wyszukiwanie także bez polskich znaków, aliasy E2 i ostatnio używane produkty.
- Dwa zestawy demonstracyjne dostępne w „Dodaj posiłek → Racje”. Zaznaczanie tylko zjedzonych składników, gramatura części opakowania, skróty ¼/½/całość oraz wspólny bilans zaznaczenia. Początkowo nic nie jest zaznaczone.
- Racja jest jednym wpisem z wieloma składnikami. Można poprawić lub usunąć jeden składnik albo usunąć całą rację; usunięcie ostatniego składnika usuwa wpis z dziennika.
- Wybór grupy posiłku, gramatury, podgląd kcal, zapis, edycja i usunięcie wpisu.
- Własny produkt z nazwą, źródłem i wartościami na 100 g, opcjonalnymi makrami oraz gramaturą spożycia. Produkt jest prywatny i dostępny do ponownego wyboru; zapis szkicu i pierwszego posiłku jest transakcją.
- Lokalny profil: pseudonim, wzrost, klasa Garnizon/Linia/Komandos i cel redukcja/utrzymanie/nadwyżka. Kcal/B/T/W ustawia się oddzielnie; zapis profilu ich nie zmienia.
- Pomiary wagi z datą, historią, korektą i usunięciem. Kilka pomiarów jednego dnia jest dozwolone. Po poprawnym zapisie pole masy jest czyszczone, aby ponowny przypadkowy klik nie zapisał kolejnego pomiaru.
- Deklaracja kompletności dnia. Efektywna kompletność wymaga deklaracji, nieusuniętych składników, dodatniej sumy kcal i znanej energii wszystkich pozycji. Brak makr pozostaje brakiem danych. Usunięcie ostatniego posiłku lub dodanie pozycji bez kcal cofa efektywną kompletność; wcześniejsza deklaracja pozostaje w historii i można ją wyłączyć.
- Postępy dla 7/30/90 dni: wykresy kcal/B/T/W i rzeczywistych pomiarów wagi, średnie, kompletność oraz realizacja celu obowiązującego każdego dnia. Historia pozwala otworzyć dziennik wybranej daty, także pustego dnia.
- Cele kcal/B/T/W obowiązujące od dnia zmiany; każda decyzja zachowuje wcześniejszą wersję, także przy kolejnej zmianie tego samego dnia. Korekta wskazuje poprzedni cel tego właściciela. Brak makr nie jest traktowany jak zero.
- Room z wersjonowanym schematem, identyfikatorami UUID, odżywczymi wartościami zapisanymi przy spożyciu i transakcyjną kolejką zmian.
- Zapis lokalnej daty, strefy czasowej i czasu UTC. Ponowienie lokalnego zapisu z tym samym ID nie tworzy drugiego posiłku.

Katalog i początkowy cel 2800 kcal są **danymi demonstracyjnymi**, nie zweryfikowaną bazą żywieniową ani wyliczonym zapotrzebowaniem użytkownika. Dawne zestawy A/B nie odwzorowują specyfikacji S-R/S-RG ani żadnego producenta. Nowy pakiet E2 dodaje osobną niezweryfikowaną, niepełną rację S-RG-1 z 18 policzalnymi komponentami i informacją o pozycjach poza obliczeniami. Nie łączymy zestawów po nazwie lub kalorii. Dawne napoje pozostają w gramach; nowy katalog obsługuje g/ml, bez założenia, że 1 ml = 1 g.

Schemat Room 6 zawiera migracje 1 → 2 → 3 → 4 → 5 → 6 zachowujące posiłki, racje, cele, prywatne produkty, profil, pomiary, deklaracje dni, właścicieli i całą kolejkę. Ostatnia migracja przebudowuje tabelę celów z zachowaniem wszystkich wcześniejszych kolumn i ID, dodaje metadane wersji/złożony FK korekty oraz dwie tabele bootstrapu. Nie zmienia wartości REAL ani dawnych payloadów outbox. Prywatne dane mają zakres właściciela. Usuwanie spożycia pozostawia znacznik i operację kolejki; wersje celów są niezmienne.

## Przygotowanie E3 i niezmienne cele

`AccountBootstrapStore` utrwala klucz niezakończonego żądania, powiązanie lokalnego właściciela z `account_id` oraz niezależne `account_generation`/`sync_epoch`. Sprawdza właściciela, generację lease i żądanie przy przyjmowaniu odpowiedzi; powiązanie i potwierdzenie zapisują się atomowo. Restart nie zmienia klucza ponowienia. Zmiana kontekstu serwera ustawia trwałą blokadę wymagającą uzgodnienia E4; nie resetuje dziennika lub kolejki. Nie ma jeszcze wywołania sieciowego ani klienta sesji.

Zmiana celu tworzy nowy UUID zamiast nadpisania poprzedniego wiersza. Wersja ma lokalną sekwencję, czas/strefę decyzji i referencję korekty z własnością wymuszoną w SQLite. Odczyty dziennika i analityki wybierają najnowszą wersję dla daty. Callback `DATABASE_GUARDS` chroni treść przed UPDATE/DELETE oraz zmieniającym INSERT OR REPLACE, także po ponownym otwarciu bazy; przy tworzeniu bazy poza aplikacją należy go dołączyć. Lokalne sekwencje i kolejka wymagają osobnego adaptera serwerowej osi/Decimal.

[Przekazanie E3 dla O2/O3](INTEGRACJA_E3.md) podaje dokładne przyszłe callbacki APK, reguły bootstrapu, granice i kolejne kroki. [Raport 0.7.0](RAPORT_0_7.md) opisuje walidację.

## Fundament kont i izolacji

`LocalOwnerStore` utrwala UUID gościa, rejestruje dokładną parę wystawcy i podmiotu oraz przechowuje aktywny zakres wraz z generacją. Rejestracja metadanych nie zmienia aktywnego właściciela. Każdy wybór, także ponowny wybór tego samego konta, unieważnia stare `OwnerLease`.

`DiaryRepository` wiąże się z jednym właścicielem. Wszystkie jego mutacje sprawdzają zakres i generację wewnątrz tej samej transakcji co zapis danych oraz outbox. ViewModel przekazuje zakres repozytorium także do odczytów i analityki. Katalog pozostaje wspólny; prywatne produkty, spożycia, profile, cele, waga, kompletność i operacje pozostają osobne. Obce ID nie pozwala nadpisać pomiaru wagi ani zmienić cudzego posiłku. Kolizje istniejących globalnych ID kończą się błędem bez przeniesienia rekordu.

Stare rekordy i payloady nadal mają `ownerScope=guest`; nowy UUID gościa jest związany z tym aliasem w rejestrze. Nie zmieniamy identyfikatorów ani treści zaległych operacji. Konto ma zakres równy swojemu lokalnemu UUID, odrębny od `sub` i serwerowego identyfikatora użytkownika. Żadne przełączenie nie przypisuje ani nie wysyła danych gościa.

To wewnętrzny fundament, bez logowania lub wyboru konta w UI. Rejestr metadanych nie uwierzytelnia użytkownika. Przy integracji trzeba utworzyć go z potwierdzonej sesji OIDC, odtworzyć ViewModel i wyczyścić pamięć ekranów po zmianie konta oraz dodać analogiczne kontrole przed wysyłką i zapisem odpowiedzi HTTP. Aktualne klucze tabel pozostają globalnymi UUID; docelowe klucze z właścicielem, jawne przypisanie gościa i adapter E0 wymagają kolejnego etapu. [Raport 0.6.0](RAPORT_0_6.md) podaje odbiór oraz te granice.

## Import katalogu i dokładność

Pakiet E2 pochodzi z rzeczywistego eksportu PostgreSQL osoby 2, commit [`229a2b8`](https://github.com/Roseru/aplikacja-mobilna/tree/229a2b8/backend/data/demo/export). Artefakty i normatywne schematy E0 są osadzone w `app/src/main/assets/catalog/e2/`; wektory w zasobach testowych. SHA-256 gzip: `65f4aae8002fd5522d0edb4689e05682103b80fbe3e6dbc68f4bf02c645b2bef`; gzip 3099 B, JSON 15691 B. To eksport E2, a nie starszy fixture E0. Fizyczny asset APK ma nazwę `base-pl.1.json.gz.bin`, ponieważ etap MergeAssets automatycznie rozpakowywał rozszerzenie `.gz`. Sufiks `.bin` zachowuje oryginalne skompresowane bajty; manifest nadal ma kontraktowy logiczny path `base-pl.1.json.gz`.

- `CatalogPackageReader` sprawdza zaufaną tożsamość demo `47bdff67-e58b-5437-919b-ec00159afbc5`, kind/release/schema/reader, dokładne bajty i rozmiary, CRC i pojedynczy strumień gzip, ścisły UTF-8/JSON, schemat oraz graf referencji. Limity: manifest 1 MiB, gzip 10 MiB, JSON 50 MiB. Czytnik schematów obsługuje słowa kluczowe użyte w przypiętych dwóch schematach; nie jest ogólnym silnikiem JSON Schema.
- Hash jest liczony przed rozpakowaniem. Daty `published_at` z 1–6 cyframi ułamka sekund pozostają w oryginalnej pisowni zgodnie z poprawką E2 z 10 października. SHA nie uwierzytelnia pakietu; obecny kanał dostawy to APK, a pobieranie przez HTTPS będzie osobnym etapem.
- `CatalogStore.stage()` zapisuje nieaktywną generację w transakcji; `activate()` przełącza ją krótką transakcją tylko na nowszy kompletny release. Ponowienie jest no-op; inna treść pod tym samym release albo UUID+revision jest błędem. Ekrany czytają aktywne członkostwo, a stare wersje pozostają dla historii. Sprzątanie generacji nie jest zaimplementowane.
- Dokładne wartości, metadane produktów/racji/źródeł i ilości komponentów są przechowywane jako TEXT. Wewnętrzne klucze zawierają typ, dokładny UUID i rewizję; pozycje składników E2 wynoszą 1..N. Kolumny REAL pozostają projekcjami dla zgodności wcześniejszych ekranów, nie źródłem nowych obliczeń.
- Nowe spożycie z E2 zapisuje pełny produkt z rewizją, jednostkę i tekst ilości, źródła/gęstość oraz `nutrition_v1` w snapshot i lokalnej kolejce. Edycja zmienia ilość snapshotu, zachowując jego produkt; aktualizacja katalogu nie przelicza historii.
- `NutritionV1` liczy przez BigDecimal: per100 × ilość / 100; dzielenie przy g→ml ma skalę 12 HALF_UP, konwersja wymaga udokumentowanej gęstości. Sumowanie następuje przed zaokrągleniem wyświetlania (0 miejsc kcal / 1 miejsce makr HALF_UP); energia nie jest wyliczana z 4/4/9. Każde pole ma known_sum, missing_count i complete. Niepełne sumy pokazują `≥` oraz liczbę braków.

Stare dane REAL są odczytywane przez `BigDecimal.valueOf` bez nadpisania oryginału i bez twierdzenia, że odzyskano utraconą dokładność. Prywatne produkty, cele, profil i pomiary nadal mają dawną reprezentację zapisu. Ich pełny adapter Decimal do API pozostaje do wykonania. Formy porcji dopuszczają lokalnie do 12 miejsc, aby nie obcinać wyliczonych ułamków opakowania; przyszły adapter synchronizacji musi jawnie obsłużyć ograniczenie Quantity E0 do 6 miejsc. Nie obcinamy kolejki w miejscu ani nie wysyłamy jej w obecnym formacie.

## Postępy i historia

Dolna zakładka **Postępy** pokazuje ostatnie 7, 30 lub 90 dat kalendarzowych włącznie z dzisiaj. Strzałki przesuwają okno o wybrany okres; „Do dzisiaj” przywraca bieżący zakres. Okres i wybrany wykres pozostają po odtworzeniu aktywności.

- Cel pobieramy z ostatniej wersji obowiązującej w danym dniu, również sprzed początku okna. Przyszłe cele nie wpływają na wcześniejsze dni. `goal_band_v1` stosuje granice ±10% włącznie, przed zaokrągleniem wyświetlania. Do oceny potrzebny jest kompletny dzień i dodatni cel; brak celu oznacza brak oceny.
- Dni bez wpisów pozostają bez danych. Dni niepotwierdzone lub z nieznaną energią pozostają niekompletne. Ich znane wartości są widoczne w historii i na wykresie jako niepełne, ale nie sugerujemy deficytu ani nie dodajemy ich do średniej.
- Średnia każdego pola obejmuje kompletne dni ze znaną wartością tego pola; obok wyniku pokazujemy własny mianownik. Dzień z brakującym białkiem może mieć znane kcal, a białko nie trafia do jego średniej. Znane zero pozostaje zerem. Sumy są dokładne; średnia jest dzielona w skali 12 HALF_UP i zaokrąglana dopiero do prezentacji.
- Wykres wagi i zmiana masy używają ostatniego rzeczywistego pomiaru każdej daty w oknie; czas UTC i ID rozstrzygają kolejność. Licznik obejmuje wszystkie nieusunięte pomiary. Do zmiany masy potrzebne są co najmniej dwie daty z pomiarem. Nie interpolujemy ani nie przenosimy pomiarów z innych dni lub spoza okna.
- Odczyty Room są ograniczone do właściciela i zakresu; pomijają znaczniki usunięcia. Edycje, usunięcia, nowe cele, pomiary i deklaracje aktualizują obserwowany wynik. Analityka nie zapisuje operacji outbox ani nie modyfikuje dziennika. Aktualność dotyczy wyłącznie danych na urządzeniu; synchronizacja nadal nie jest podłączona.

## Co pozostaje na następne etapy

Zweryfikowane pakiety rzeczywistych racji i osobny import materiałów MRE 2026, kalkulator zapotrzebowania, konto, rzeczywista synchronizacja z API, zdjęcia/Gemini, produkty społeczności, ranking i Nemesis. Istnieje lokalna kolejka, ale ta wersja **nie wysyła danych na serwer**. Prywatne produkty nie są publikowane w katalogu społeczności. API katalogu E2 udostępnia wyłącznie official; demo jest lokalne w APK i nie powoduje oczekiwania na konto/API.

## Uruchomienie w Android Studio

1. Otwórz katalog `android/` jako projekt.
2. Użyj JDK 17 lub 21 i zainstalowanego SDK Platform 35 / Build Tools 35.0.0. Minimalna wersja urządzenia: Android 8.0 (API 26).
3. Poczekaj na synchronizację Gradle. Wrapper i wersje bibliotek są przypięte w repozytorium.
4. Uruchom moduł `app` na emulatorze lub telefonie. Pierwszy dziennik jest pusty, bez fikcyjnie zjedzonych posiłków.

Android Studio zwykle tworzy ignorowany `local.properties` z własną ścieżką SDK. Nie kopiuj do repozytorium konfiguracji ścieżek innego komputera.

## Komendy dla osoby 3 / CI

Uruchom z katalogu `android/`, przy ustawionym `JAVA_HOME` i dostępnym SDK:

```powershell
.\gradlew.bat :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
.\gradlew.bat :app:connectedValidationAndroidTest
```

Na Linuxie: `./gradlew` z tymi samymi zadaniami. Druga komenda wymaga uruchomionego emulatora lub podłączonego urządzenia. Testy urządzenia działają w osobnej aplikacji `pl.roseru.kalorie.validation`; instalacja i sprzątanie testów nie usuwa zwykłego dziennika `pl.roseru.kalorie`. Pierwsza kompilacja pobiera zależności; gotowa aplikacja do działania nie wymaga sieci.

APK debug: `app/build/outputs/apk/debug/app-debug.apk`. Raporty: `app/build/reports/`. Schemat Room: `app/schemas/` (należy wersjonować, nie stosować migracji kasujących dane).

## Kontrole odbioru

1. W trybie samolotowym dodaj produkt z ilością `120,5 g`. Sprawdź kcal i pozycję w wybranej grupie.
2. Zamknij aplikację i otwórz ponownie. Wpis pozostaje.
3. Edytuj ilość, a potem usuń wpis. Bilans i kolejka reagują na obie zmiany.
4. Zmień motyw i uruchom aplikację ponownie. Ustawienie pozostaje.
5. Ustaw nowy cel. Wczorajszy cel pozostaje wcześniejszy.
6. Dodaj produkt bez makr. Kalorie są policzone, a B/T/W pokazują brak danych.
7. Dodaj rację A z 50 g konserwy i 22,5 g sucharów. Pozostałe składniki pozostają niezaznaczone. Wpis ma 222 kcal.
8. Przed zapisem obróć ekran lub odtwórz aktywność: wybór i gramatura pozostają. Pusta lista zaznaczeń i ilość ponad masę opakowania blokują zapis.
9. Edytuj jeden składnik zapisanej racji. Pozostałe nie zmieniają się. Usuń składnik i sprawdź bilans; usuń całą rację po potwierdzeniu.
10. Zainstaluj aktualizację na wersji 0.1.0: stare posiłki, cele i kolejka pozostają.
11. Własny produkt: podaj 100 kcal/100 g, źródło i 150,5 g spożycia, pozostaw makra puste. Dziennik zwiększa sumę o 150,5 kcal, pokazuje brak makr i zachowuje produkt do ponownego wyboru.
12. Zapisz profil, a potem dwa pomiary z tą samą datą. Wpisy pozostają osobne, korekta zachowuje datę, a usunięcie jednego nie usuwa drugiego ani nie zmienia celu kalorii.
13. Oznacz niepusty dzień jako kompletny, zamknij aplikację i otwórz ponownie. Następnie usuń wszystkie jego posiłki: pusty dzień nie jest kompletny mimo wcześniejszej deklaracji.
14. Zainstaluj aktualizację na wersji 0.2.0: składniki racji i wartości historyczne pozostają.
15. W Postępach przełącz 7/30/90 dni i kcal/B/T/W, sprawdź mianowniki średnich, wcześniejsze cele oraz niepełne/puste dni. Otwórz dzień z historii i popraw wpis: wynik po powrocie się aktualizuje.
16. Zapisz kilka pomiarów tej samej daty, popraw lub usuń ostatni. Wykres używa ostatniego dostępnego pomiaru i zachowuje przerwy. Przesuń okres strzałkami i odtwórz aktywność.

Szczegółowy wynik walidacji 0.4.0, zakres prób awarii i ograniczenia odbioru E2: [raport Androida](RAPORT_0_4.md). Testy urządzenia obejmują migracje 1/2/3 → 4, zachowanie historii/kolejki, generacje, niezmienność wersji, rzeczywisty SQLITE_FULL oraz przepływy UI z odtworzeniem aktywności. Pełny odbiór zespołowy KO-30 wymaga również środowiska i dostawy O2/O3; raport lokalny go nie zastępuje.

Wynik etapu analityki i zasady zależnego PR: [raport 0.5.0](RAPORT_0_5.md). Bieżąca migracja i izolacja: [raport 0.6.0](RAPORT_0_6.md); testy obejmują ścieżki 1/2/3/4 → 5.

## Architektura

`MainActivity` tworzy ViewModel i uruchamia Compose. `DiaryViewModel` udostępnia obserwowalny stan. `DiaryRepository` realizuje transakcyjne operacje zapisu, `data/LocalOwners.kt` utrwala właścicieli i chroni zapis przed zmianą aktywnego zakresu. `CalorieDao` jest lokalnym źródłem ekranów. `core/NutritionV1.kt` zawiera dokładne obliczenia, `core/catalog/` walidację pakietu, `data/CatalogStore.kt` staging i aktywację. `ui/` zawiera wspólne motywy i ekrany.

Nie ma uprawnienia INTERNET, kluczy API ani danych konta w APK pierwszej wersji. Dodamy warstwę sieciową wraz z etapem synchronizacji.
