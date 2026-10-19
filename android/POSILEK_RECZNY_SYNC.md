# Nowy ręczny posiłek w kolejce synchronizacji

Agent1, 19.10.2026, `codex/android-posilek-reczny-sync`.
Zależność: dokładny `9a3a9a9c0cd03817f95cf6f504237288c8998d0c` /
[PR129](https://github.com/Roseru/aplikacja-mobilna/pull/129).
To niezależna gałąź funkcji dziennika, bez przenoszenia kodu drivera PR138.
Najnowszy własny dziennik przeniesiono osobno, aby zachować przekazania O1.

## Zachowanie aplikacji

Po połączeniu konta z serwerem, dodanie własnego produktu wraz z posiłkiem
zapisuje spożycie jako kanoniczny Meal i jedną operację upsert/create
sync-v1. Ta sama ścieżka obejmuje późniejszy wybór tego prywatnego produktu
z listy. Produkt pozostaje lokalny, z nazwą, źródłem i właścicielem; jego
dotychczasowy szkic produktu jest oddzielną operacją lokalną. Nie publikuje
się produktu ani nie wymyśla dla niego referencji katalogowej na serwerze.

Wysyłanie posiłków działa przez istniejący panel PR129. Sam zapis nie wykonuje
HTTP, nie wymaga aktualnego tokenu i nie czeka na pełny pull. Wymaga znanego,
zdrowego powiązania konta; pełna kopia serwera i ważna sesja są nadal sprawdzane
przed wysyłką. Produkty gościa nie są automatycznie przypisywane do konta.

Meal/Item i operacja powstają w jednej transakcji ownerTransaction, razem
z nowym prywatnym produktem i szkicem, jeśli dodawane są równocześnie.
Wyjątek zapisu wycofuje całość. Powtórne dodanie z tym samym mealId nie tworzy
drugiego produktu/posiłku/operacji; stare ID nie są nadpisywane.
Zmiana aktywnego właściciela unieważnia wcześniejsze repozytorium.

## Dane i dokładność

Payload ma nutrition_origin=manual, product=null, dokładne ilości i wartości
na100g, null dla brakujących makr i jawne zero dla podanego zera. Wspólny
MealWire/schema oraz nutrition_v1 weryfikują całość. Lokalny productId i źródło
pozostają w bazie urządzenia. Edytor kanoniczny zachowuje je wraz z itemId
i pozostałymi lokalnymi metadanymi, również po zmianie porcji. Usunięcie
niewysłanego posiłku nie tworzy próby skasowania nieistniejącego rekordu serwera.

Nowy czas spożycia zostaje zapisany z precyzją mikrosekund wymaganą przez
kontrakt, z tą samą strefą i lokalną datą. Jeżeli wynik zmieniłby wybraną datę
(np. historyczna pominięta data w strefie), pozostaje dotychczasowy zapis lokalny.
Nie modyfikuje to wcześniej zapisanych czasów lub celów.

Jeśli danych nie da się przedstawić bezstratnie w sync-v1 (np. rzeczywista
ilość z7–12 miejscami po przecinku), zapis pozostaje w dotychczasowym formacie
lokalnym i kolejce. Nie zaokrągla się wejścia dla wymuszenia wysyłki. Analogicznie
działa konto bez bootstrapu lub wymagające recovery oraz gość. Licznik formatu
lokalnego nie jest potwierdzeniem synchronizacji. Ograniczenie jest jawne;
pełny adapter precyzji/importu pozostaje kolejną częścią synchronizacji.
Późniejsza edycja wpisu już kanonicznego wymaga ilości zgodnej z kontraktem
do6 miejsc; przekroczenie jest odrzucane bez zmiany istniejącego posiłku.

## Zakres pozostający osobno

Ten krok obejmuje **prywatne ręczne produkty**, bez catalogueJson.
Produkty/racje katalogowe, w tym lokalne demo, nie są przemianowywane na manual
ani publikowane pod nieznanymi referencjami serwera. Mają osobny adapter
pochodzenia i kolejne zadanie. Wcześniejsze wpisy i format legacy nie są
masowo przepisywane. Profil, cele, waga, kompletność, import gościa,
konflikty/recovery/retencja i WorkManager pozostają niezależnymi częściami E4.

Przyszła wspólna próba może dzięki tej funkcji przygotować syntetyczny Meal
z normalnego formularza aplikacji, bez Gemini i seedowania SQL. Wymaga to
integracji obu oddzielnych gałęzi: tej funkcji oraz
[drivera PR138](https://github.com/Roseru/aplikacja-mobilna/pull/138), nowego
skonfigurowanego APK i osobnego odbioru. Obecne APK nie zawierają tej zmiany.

## Weryfikacja lokalna i granice dowodów

**18/18 JVM PASS**:8 nowych testów manual payload i10 regresji MealWire.
Obejmują Decimal/null/zero, g/ml, mikrosekundy, DST, wszystkie typy posiłku,
zachowanie identyfikatorów, odrzucenie nadmiernej precyzji i błędnych pól
przez rzeczywisty kontrakt oraz poprawną operację z base_revision=null.
Testy wykonały się w0,618s; lekka kompilacja8,27s/exit0.

Repozytorium, edytor i8 nowych testów Room skompilowano razem w12,8s/exit0
na wcześniej zbudowanych klasach zależnych. Testy Room obejmują atomowy zapis
i rollback, powtórzenie, izolację kont/stary lease, fallback offline/precyzji,
edycję/usunięcie, ochronę katalogu i ponowne otwarcie bazy. **Ich wykonanie
na urządzeniu pozostaje NOT_RUN**; kompilacja nie potwierdza działania Room.

SHA256 logu18 JVM: `8b2d4b2196fcc4364f961bd629c1bb84a02fa997a0848f5ec725cfe98e8da111`.
Receipt kompilacji i hashy źródeł:
`2eaf2953a4fc444131d5609b5b6bfeb967cc7896420f671c987ef074430742ec`.

Sprawdzono hashe wejść przed/po oraz255 niezmienionych wcześniejszych wejść.
Jedno CPU, heap256MiB, obniżony priorytet. Bez Gradle, nowego APK, emulatora,
HTTP lub Gemini. Numer wersji i schemat Room bez zmiany; historyczny manifest
0.8.23 oraz jego320native nie kwalifikują nowej funkcji. Pełny build, regresja
urządzenia, aktualizacja bez utraty danych i rzeczywisty push są osobnymi
warunkami odbioru przed wydaniem. To praca przygotowana podczas gry właściciela.
