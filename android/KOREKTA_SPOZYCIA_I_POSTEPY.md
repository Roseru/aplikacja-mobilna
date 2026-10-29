# Korekta zapisanego spożycia i aktualność Postępów

Zakres: WF-03, WF-10, KO-07/11/12/23/25/31. Dane gościa i kont pozostają
rozdzielone. Nie zmienia się kontrakt API, Room 27 ani historia migracji.

## Korekta składnika

W Dzienniku dotknij składnika. Dotychczasowa edycja ilości skaluje zapisane
wartości. Przycisk „Popraw składnik, kcal i B/T/W” otwiera osobny formularz
wartości własnych tego spożycia. Podstawa każdego pola jest jawna: **100 g
albo 100 ml**, niezależnie od zjedzonej ilości. Podgląd pokazuje spożycie
po zastosowaniu ilości. Puste pole pozostaje `null`, jawne `0` jest zerem.
Walidacja używa Decimal (maksymalnie sześć miejsc); końcowe sumy używają
wspólnego `nutrition_v1` i `HALF_UP`, z normatywną precyzją konwersji
i bez zaokrąglania prezentacyjnego poszczególnych składników.

Jednostka ilości i podstawa wartości są osobne. Różne jednostki wymagają
udokumentowanej gęstości zachowanego składnika. Zmiana nazwy jest świadomym
zastąpieniem go własnym składnikiem i odłącza gęstość starego produktu;
wówczas można podać ilość i wartości w tej samej jednostce. Formularz
nie wylicza sam nowych wartości po zmianie jednostki. „Dodaj składnik do
posiłku” dodaje ręczny składnik do istniejącego wpisu. Nie publikuje produktu.
Zastąpienie usuwa znacznik pozycji racji; sama korekta wartości go zachowuje.

Identyfikator zachowanego składnika i posiłku, data, czas i strefa pozostają.
Bieżący `MealItem.wirePayload` jest dokładnym autorytetem obliczeń, także
dla lokalnego legacy. Ręczna korekta ma `nutrition_origin=manual` oraz
`product=null`; nie udaje nowej wersji katalogu lub ponownej analizy AI.
Istniejące źródłowe kolumny odżywcze i `snapshotJson` nie są przeliczane.
Jeżeli źródłowego snapshotu nie było, pierwsza korekta zapisuje w istniejącym
`snapshotJson` kotwicę `{formula_version, quantity, original_consumption}`:
pierwotny wire składnika albo pierwotne wartości lokalne. To źródło archiwalne,
nie nowy format synchronizacji. Przy kolejnych korektach, zastosowaniu PULL
lub wyborze wersji serwera tej samej pozycji kotwica pozostaje zachowana,
a obliczenia nadal czytają bieżący wire. Usuwanie pozycji nadal usuwa jej
bieżącą projekcję; ten etap nie dodaje pełnego rejestru undo usuniętych źródeł.
Zamrożone próby, receipts, źródła importu i potwierdzenia zdjęć zachowują
swoje dotychczasowe trwałe reguły.

## Kolejka, odmowy i import

Zapis korekty i nowy outbox są jedną transakcją właściciela. Edycja
zwiększa lokalną rewizję; odczyt ze starym lease po A→B→A jest odrzucany.
Zmiana reprezentacji legacy→canonical pomiędzy odczytem a zapisem również
odrzuca całą lokalną próbę, którą można ponowić.

- Nierozpoczęte intencje są zastępowane nową operacją. Rozpoczęte UUID,
  body, hash, checkpoint i receipt pozostają niezmienne.
- Podczas oczekiwania na ACK nowa intencja czeka na rewizję poprzednika.
  Potwierdzenie poprzednika podaje bazę nowej operacji; nie zastępuje jej
  poprawionych wartości starym payloadem.
- Konflikt nadal wymaga wyboru w istniejącym ekranie konta. Wybór lokalny
  obejmuje najnowszą korektę, a bazę ustala z dowodu serwera.
- Po trwałym `rejected` popraw wpis w dzienniku, a na ekranie uzgadniania
  wybierz „Wyślij poprawioną wersję” i potwierdź. Nowy UUID korzysta ze znanej
  bieżącej lub pierwotnej bazy (`null` dla odrzuconego create). Stara odmowa
  i wynik pozostają zachowane w historii decyzji. Niezmieniona odmowa,
  nierozstrzygnięta próba i konflikt nie otrzymują automatycznego ponowienia.
- Podczas recovery zapis pozostaje lokalny i czeka na dotychczasową ścieżkę
  uzgodnienia. Nie powstaje drugi protokół lub automatyczna zgoda na import.

Import gościa/legacy, porównanie i formularz importu czytają bieżący wire
składnika przed pierwotnym snapshotem. Istniejące mapowanie identyfikatorów
i potwierdzanie źródeł racji pozostają obowiązkowe. Źródło i zamrożone
operacje importu nie są zmieniane przy poprawianiu wersji pochodnej.

## Postępy

Raport nadal liczy lokalne okna 7/30/90, znane dni i rzeczywiste pomiary.
Metadane są wyłącznie odczytem tych samych trwałych faktów synchronizacji,
pod istniejącym owner lease i kontekstem konta:

- gość: dane tylko na urządzeniu, bez sugerowania kopii serwerowej;
- konto bez zastosowanego pobrania: jawnie możliwa niepełna historia;
- konto z kopią: czas ostatniego ukończonego pobrania **i zastosowania**
  oraz osobno czas stanu serwera; surowa ukończona kopia bez zastosowania
  nie podnosi aktualności raportu;
- oczekujące, odrzucone i konfliktowe zmiany: liczniki całego konta,
  także spoza oglądanego okresu; osobno niepotwierdzona próba,
  niezastosowane rekordy, kopia czekająca na zastosowanie i recovery;
- blokada lub niedostępna polityka sieci: jawny stan offline/wstrzymania.
  `Allowed` oznacza zgodę na sieć, nie potwierdzenie Internetu lub ACK;
- nieaktualny lease: także liczby starego raportu są ukrywane.

Czas kopii ani dozwolona sieć nie potwierdzają całej kolejki. Nie powstaje
nowa maszyna synchronizacji, sesja, gate lub definicja kompletności dnia.

## Regresje

Nowe JVM: `MealIngredientInputTest`, `LegacyMealCorrectionImportTest`,
`AnalyticsSyncPresentationTest`. Room/Compose: `MealIngredientStorageTest`,
`MealIngredientFlowTest`, `CorrectedRejectionStorageTest`,
`AnalyticsSyncStorageTest`, `AnalyticsSyncFlowTest` oraz przypadki
zachowania źródła i potwierdzenia poprawionej odmowy. Testy używają
niezależnie ustalonych sum, rzeczywistej plikowej Room, triggerów rollback
i syntetycznych receipts. Nie są dowodem PKCE/HTTPS/API/PG lub Gemini.
Wynik dostawy i zakres wykonanych kontroli są w jedynym
[dzienniku zespołu](../docs/KOMUNIKACJA_AGENTOW.md).
