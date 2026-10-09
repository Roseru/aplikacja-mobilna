# Android — Racje i kalorie

Wersja `0.3.0` realizuje lokalny przepływ osoby 1: dziennik → produkt, własny wpis lub racja → zapis w Room → aktualizacja bilansu. Profil, pomiary wagi i deklaracja kompletności dnia również działają bez konta i internetu.

## Co zawiera

- Jasny i ciemny motyw oraz wybór zgodny z systemem, zapisany w DataStore.
- Dziennik według dni, wybór daty, suma kcal i B/T/W oraz realizacja celu.
- Wbudowany katalog 15 produktów demonstracyjnych, wyszukiwanie także bez polskich znaków i ostatnio używane produkty.
- Dwa zestawy demonstracyjne dostępne w „Dodaj posiłek → Racje”. Zaznaczanie tylko zjedzonych składników, gramatura części opakowania, skróty ¼/½/całość oraz wspólny bilans zaznaczenia. Początkowo nic nie jest zaznaczone.
- Racja jest jednym wpisem z wieloma składnikami. Można poprawić lub usunąć jeden składnik albo usunąć całą rację; usunięcie ostatniego składnika usuwa wpis z dziennika.
- Wybór grupy posiłku, gramatury, podgląd kcal, zapis, edycja i usunięcie wpisu.
- Własny produkt z nazwą, źródłem i wartościami na 100 g, opcjonalnymi makrami oraz gramaturą spożycia. Produkt jest prywatny i dostępny do ponownego wyboru; zapis szkicu i pierwszego posiłku jest transakcją.
- Lokalny profil: pseudonim, wzrost, klasa Garnizon/Linia/Komandos i cel redukcja/utrzymanie/nadwyżka. Kcal/B/T/W ustawia się oddzielnie; zapis profilu ich nie zmienia.
- Pomiary wagi z datą, historią, korektą i usunięciem. Kilka pomiarów jednego dnia jest dozwolone. Po poprawnym zapisie pole masy jest czyszczone, aby ponowny przypadkowy klik nie zapisał kolejnego pomiaru.
- Deklaracja kompletności dnia. Efektywna kompletność wymaga deklaracji, nieusuniętego posiłku i dodatniej sumy kcal. Brak makr pozostaje brakiem danych. Usunięcie ostatniego posiłku cofa efektywną kompletność; deklarację można wyłączyć.
- Cele kcal/B/T/W obowiązujące od dnia zmiany; brak makr nie jest traktowany jak zero.
- Room z wersjonowanym schematem, identyfikatorami UUID, odżywczymi wartościami zapisanymi przy spożyciu i transakcyjną kolejką zmian.
- Zapis lokalnej daty, strefy czasowej i czasu UTC. Ponowienie lokalnego zapisu z tym samym ID nie tworzy drugiego posiłku.

Katalog, oba zestawy i początkowy cel 2800 kcal są **danymi demonstracyjnymi**, nie zweryfikowaną bazą żywieniową ani wyliczonym zapotrzebowaniem użytkownika. Zestawy A/B nie odwzorowują specyfikacji S-R/S-RG ani żadnego producenta. Napoje są rozliczane w gramach, bez założenia, że 1 ml = 1 g.

Schemat Room 3 zawiera migracje 1 → 2 → 3 zachowujące dotychczasowe posiłki, racje, cele i kolejkę. Prywatne produkty, profil, pomiary i deklaracje dni mają zakres właściciela. Nowy katalog jest importowany bez duplikowania danych. W kolejce wpis racji zawiera `ration_id`, nazwę oraz identyfikatory składników; wartości odżywcze nadal są zapisane w historii jako niezmienny snapshot. Nowe typy kolejki: `product_draft`, `profile`, `weight`, `diary_day`.

Katalog w zasobach i payload kolejki są roboczym formatem tej lokalnej wersji. Integracja z [kontraktami E0 osoby 2](../docs/e0/KONTRAKTY_I_INTEGRACJA.md) jest następnym etapem: adapter pakietu JSON gzip/manifest, UUID i rewizje produktów, generacje katalogu oraz wspólne wektory Decimal/BigDecimal. Bieżące obliczenia używają `Double` i nie stanowią kontraktu obliczeń z API. Nie wysyłamy roboczych identyfikatorów demo na serwer. Formularze v0.3 mają lokalne limity opisane przy polach; adapter kontraktu będzie odpowiadał za jego kanoniczne liczby i jednostki.

## Co pozostaje na następne etapy

Docelowy importer i zweryfikowane pakiety rzeczywistych racji, obliczenia kontraktowe, historia/wykresy 7/30/90 dni, kalkulator zapotrzebowania, konto, rzeczywista synchronizacja z API, zdjęcia/Gemini, produkty społeczności, ranking i Nemesis. Istnieje lokalna kolejka, ale ta wersja **nie wysyła danych na serwer**. Usuwanie posiłku lub pomiaru tworzy znacznik usunięcia zamiast kasować historię operacji. Prywatne produkty nie są publikowane w katalogu społeczności.

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

Walidacja 0.3.0: zbudowano APK debug, przeszło 6 testów jednostkowych i 17 przypadków na API 35. Pełny przebieg urządzenia zaliczył 16 przypadków; test profilu/wagi zaliczono w osobnym powtórzeniu po poprawieniu obsługi klawiatury w teście. Ręczny zapis pomiaru z otwartą klawiaturą również sprawdzono. Lint: 0 błędów, 25 ostrzeżeń o wersjach zależności i regułach kopii urządzenia.

Testy obejmują obliczenia i brak makr, trwałość Room, izolację właścicieli, transakcyjność i rollback, idempotencję, znaczniki usunięcia, cele, prywatne produkty, profil/wagę i kompletność dnia. Sprawdzono migracje 1 → 3 i 2 → 3 oraz cztery przepływy UI z odtworzeniem aktywności: zwykły posiłek, częściową rację, własny produkt i profil/pomiar.

## Architektura

`MainActivity` tworzy ViewModel i uruchamia Compose. `DiaryViewModel` udostępnia obserwowalny stan. `DiaryRepository` realizuje transakcyjne operacje zapisu. `CalorieDao` jest lokalnym źródłem danych ekranów. `core/Nutrition.kt` zawiera obliczenia niezależne od Androida. `ui/` zawiera wspólne motywy i ekrany.

Nie ma uprawnienia INTERNET, kluczy API ani danych konta w APK pierwszej wersji. Dodamy warstwę sieciową wraz z etapem synchronizacji.
