# Android — Racje i kalorie

Wersja `0.2.0` realizuje lokalny przepływ osoby 1: dziennik → produkt lub racja ze składnikami → zapis w Room → aktualizacja bilansu. Aplikacja działa bez konta i bez internetu.

## Co zawiera

- Jasny i ciemny motyw oraz wybór zgodny z systemem, zapisany w DataStore.
- Dziennik według dni, wybór daty, suma kcal i B/T/W oraz realizacja celu.
- Wbudowany katalog 15 produktów demonstracyjnych, wyszukiwanie także bez polskich znaków i ostatnio używane produkty.
- Dwa zestawy demonstracyjne dostępne w „Dodaj posiłek → Racje”. Zaznaczanie tylko zjedzonych składników, gramatura części opakowania, skróty ¼/½/całość oraz wspólny bilans zaznaczenia. Początkowo nic nie jest zaznaczone.
- Racja jest jednym wpisem z wieloma składnikami. Można poprawić lub usunąć jeden składnik albo usunąć całą rację; usunięcie ostatniego składnika usuwa wpis z dziennika.
- Wybór grupy posiłku, gramatury, podgląd kcal, zapis, edycja i usunięcie wpisu.
- Cele kcal/B/T/W obowiązujące od dnia zmiany; brak makr nie jest traktowany jak zero.
- Room z wersjonowanym schematem, identyfikatorami UUID, odżywczymi wartościami zapisanymi przy spożyciu i transakcyjną kolejką zmian.
- Zapis lokalnej daty, strefy czasowej i czasu UTC. Ponowienie lokalnego zapisu z tym samym ID nie tworzy drugiego posiłku.

Katalog, oba zestawy i początkowy cel 2800 kcal są **danymi demonstracyjnymi**, nie zweryfikowaną bazą żywieniową ani wyliczonym zapotrzebowaniem użytkownika. Zestawy A/B nie odwzorowują specyfikacji S-R/S-RG ani żadnego producenta. Napoje są rozliczane w gramach, bez założenia, że 1 ml = 1 g.

Schemat Room 2 zawiera migrację 1 → 2 zachowującą dotychczasowe posiłki, cele i kolejkę. Nowy katalog jest importowany bez duplikowania danych. W kolejce wpis racji zawiera `ration_id`, nazwę oraz identyfikatory składników; wartości odżywcze nadal są zapisane w historii jako niezmienny snapshot.

Katalog w zasobach i payload kolejki są roboczym formatem tej lokalnej wersji. Integracja z [architekturą osoby 2](../docs/ARCHITEKTURA.md) wymaga adaptera pakietu JSON gzip z manifestem, UUID i rewizjami produktów, generacji katalogu oraz wspólnych wektorów Decimal/BigDecimal. Bieżące obliczenia używają `Double` i nie stanowią uzgodnionego kontraktu obliczeń z API. Nie wysyłamy roboczych identyfikatorów demo na serwer.

## Co pozostaje na następne etapy

Zweryfikowane pakiety rzeczywistych racji wojskowych, ręczny produkt, profil wzrost/waga, pomiary wagi i wykresy, oznaczanie kompletnych dni, konto, rzeczywista synchronizacja z API, zdjęcia/Gemini, produkty społeczności, ranking i Nemesis. Istnieje lokalna kolejka, ale ta wersja **nie wysyła danych na serwer**. Jej format jest propozycją do uzgodnienia z osobą 2. Usuwanie posiłku tworzy znacznik usunięcia zamiast kasować historię operacji.

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

Testy jednostkowe obejmują obliczenia, sumowanie bez przedwczesnego zaokrąglania, niepełne makra, walidację i wyszukiwanie. Testy na urządzeniu obejmują trwałość Room, idempotencję lokalnego dodania, znaczniki usunięcia, izolację właścicieli, wersjonowanie celu, oba przepływy dodania przez UI, odtworzenie wyboru części racji, wycofanie całego zapisu po błędzie kolejki oraz migrację rzeczywistego schematu 1 z zachowaniem danych.

## Architektura

`MainActivity` tworzy ViewModel i uruchamia Compose. `DiaryViewModel` udostępnia obserwowalny stan. `DiaryRepository` realizuje transakcyjne operacje zapisu. `CalorieDao` jest lokalnym źródłem danych ekranów. `core/Nutrition.kt` zawiera obliczenia niezależne od Androida. `ui/` zawiera wspólne motywy i ekrany.

Nie ma uprawnienia INTERNET, kluczy API ani danych konta w APK pierwszej wersji. Dodamy warstwę sieciową wraz z etapem synchronizacji.
