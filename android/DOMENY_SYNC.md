# Sześć domen trwałej kolejki — Android O2-A

Kandydat 0.8.28/code39, validation1039, Room18. Rozszerza istniejący
`MealPushStore` i ten sam transport sesji o profil, cel, kompletność dnia
i prywatny produkt. Posiłki i waga zachowują publiczne wejścia oraz protokół.

## Zapis i potwierdzenie

Nowe kwalifikujące się zapisy konta tworzą projekcję lokalną, dokładny stan
kanoniczny i operację w jednej transakcji Room. Gość, starsza kolejka i dane
niemieszczące się w wire pozostają lokalnie do osobnego świadomego uzgodnienia.
Brak wartości jest nullem; ilości do 12 miejsc nie są zaokrąglane do 6.
Wysłanie prywatnego produktu nie publikuje katalogu. Posiłek ma własny snapshot
i pozostaje niezmieniony po edycji lub usunięciu produktu.

Każda domena przechowuje rewizję encji i pełny kontekst konta. Cel ma ponadto
osobną potwierdzoną rewizję osi. Nowe wersje celu czekają na potwierdzenie
poprzedniej; odmowa zatrzymuje zależne wersje. Rewizja encji celu nie jest
rewizją osi. Decyzje, daty i korekty niezmiennych wersji pozostają zachowane. Jawna zmiana
typu celu (redukcja/utrzymanie/nadwyżka) tworzy nową wersję także przy tej samej
klasie aktywności, z zachowaniem kcal i B/T/W. Sama zmiana pseudonimu lub wzrostu
nie tworzy celu ani nie przelicza kalorii.

Profil delete/recreate tworzy nowy UUID. Nowy profil czeka na ACK usunięcia
poprzednika; stary tombstone lub opóźniony ACK nie usuwa nowego profilu.
Jawny nowy DiaryDay w przygotowywanej paczce poprzedza Meal, który inaczej
mógłby automatycznie utworzyć dzień o innym UUID. Po pierwszej próbie nie
zmieniamy kolejności, operacji, identyfikatorów ani bajtów zapisanej koperty.

Pełna odpowiedź HTTP200 jest sprawdzana przed pierwszą mutacją. Błędny dalszy
wynik nie daje ACK prefiksu. Utrata odpowiedzi i restart wznawiają identyczną
partię. Późniejsza edycja ma nową operację oczekującą na pierwotną rewizję;
ACK poprzednika nie potwierdza tej edycji. Przy zastosowaniu odpowiedzi ponownie
sprawdzane są lease, generacja, epoka, kontekst i przechwycone wiersze.

## Migracja i interfejs

Room17→18 dodaje `canonical_domains` i `canonical_goal_timelines`. Zachowuje
dotychczasowe tabele, wartości, rowid, FK, historię i requesty. Kanoniczne
sidecar powstają tylko dla udowodnionych zastosowanych projekcji serwera;
legacy i wstrzymane obserwacje nie są automatycznie konwertowane. Każdy builder
migracyjny obejmuje nowy krok; brak destructive migration.

Konto pokazuje osobno gotowe, oczekujące i wymagające uzgodnienia pozycje
każdej z sześciu domen. Starsze wpisy mają osobny licznik. Potwierdzenie
lokalnych testów nie oznacza rzeczywistego przesłania do API.

## Zakres odbioru

Końcowy lokalny build debug/validation/test APK, pełne **357 debug JVM,
372 validation JVM** oraz **73 celowane native API35** przeszły bez błędów
i pominięć. Lint: 0 błędów, 28 ostrzeżeń, 1 informacja. Nie jest to pełna
regresja wszystkich testów urządzenia; pełny CI dokładnego head/base jest
osobnym warunkiem odbioru PR.

W odrębnej kopii wyłączenie wiązania operation_id w rzeczywistym parserze ACK
dało czerwony test; właściwy parser i jego źródło pozostały nienaruszone.
Koperta sześciu domen wygenerowana przez test na Androidzie przeszła rzeczywiste
PushRequest/preflight_structure backendu; trzy niekanoniczne warianty Decimal
zostały odrzucone. To kontrola DTO/preflight bez HTTP, PostgreSQL i usług.
Celowany niezależny review: PASS po poprawce pierwszego tombstone po ACK
i regresji jawnej zmiany typu celu, bez nierozwiązanych P1/P2.

Pierwszy build zatrzymał narzędziowy błąd publikacji transform cache przed
kompilacją Kotlin. Izolacja prywatnego cache przy zachowanych wersjach narzędzi
umożliwiła build. Pierwszy native miał 64/70 PASS i sześć błędów starych fixture
zakładających dwie domeny/jedną operację; poprawiono ich jawne oczekiwania,
zachowując asercje atomowości i niezmienności. Końcowy wynik to 73/73.

Testy obejmują mieszany batch, lost ACK/restart, późniejsze edycje, odmowy,
wadliwy ostatni wynik, rollback zapisu, A→B→A, profil delete/recreate,
timeline, prywatny produkt oraz migrację z danych i kolejki schematu17.

Import gościa/legacy oraz pełne uzgadnianie expiry/epoki należą do O2-B;
WorkManager i retencja archiwów do O2-C. Granica sesji została przekazana O1
w [PR146](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6362901101).
Nie skopiowano OAuth, vaulta ani klienta HTTP. Live E4/E7-R/recovery/KO32
pozostają odrębnymi odbiorami; ten etap ich nie wykonuje.
