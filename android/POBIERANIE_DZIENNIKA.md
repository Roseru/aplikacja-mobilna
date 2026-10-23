# Pełna kopia serwera w lokalnym dzienniku — 0.8.27

Wersja 0.8.27 / code 38 / validation 1038 / Room 17. Odbiór lokalny opisano poniżej. Testy uruchamiano po zakończeniu etapu oraz po poprawkach ujawnionych podczas odbioru.

## Działanie

Po zakończeniu pobierania pełnej kopii aplikacja uzupełnia lokalny dziennik: posiłki i ich dokładne składniki, pomiary wagi, profil, wersje celów, kompletność dni oraz prywatne produkty. Najpierw musi otrzymać i sprawdzić wszystkie strony, ich kolejność, tożsamości, dane domenowe i końcowy checkpoint. Nie zapisuje poprawnego prefiksu niepełnej lub błędnej kopii.

Zapis odbywa się w jednej transakcji wraz z metadanymi obserwowanych wersji i potwierdzeniem lokalnego zastosowania kopii. Błąd dowolnego rekordu lub końcowego zapisu cofa cały ten krok; poprawne archiwum stron pozostaje zachowane. Powtórne zastosowanie tej samej kopii zwraca wcześniejszy wynik i nie cofa późniejszych edycji użytkownika.

Ekran **Konto i logowanie → Kopia danych serwera** pokazuje czas uzupełnienia, liczbę uwzględnionych rekordów oraz liczbę lokalnych zmian zachowanych do uzgodnienia. Przycisk **Uzupełnij dziennik z zapisanej kopii** działa bez HTTP i bez świeżego tokenu dostępu, jeśli aktywne jest to samo zdrowo powiązane konto i zachowano pełną kopię. Zmiana konta, blokada konta lub konieczność odzyskiwania epoki uniemożliwiają zastosowanie niewłaściwego archiwum.

## Niewysłane zmiany i historia

- Żadna operacja kolejki nie otrzymuje ACK tylko dlatego, że znalazła się lub nie znalazła w kopii. Zamrożone żądania, odpowiedzi, identyfikatory i treści operacji pozostają niezmienne.
- Niewysłane zmiany, starsza kolejka oraz lokalne usunięcia zachowują lokalną projekcję. Dokładna wersja serwera jest przechowywana obok niej. Obsługa konfliktu Meal/Weight po odpowiedzi push pozostaje w panelu porównania z0.8.26.
- Jeżeli lokalny cel wymaga uzgodnienia, zachowana jest cała lokalna oś celów. Kopia nie ukrywa po cichu lokalnej decyzji przez wstawienie serwerowego celu o większej sekwencji.
- Usunięcia w pełnej kopii obejmują tylko znane rekordy. Brak wcześniej obserwowanego rekordu w kolejnej pełnej kopii tej samej epoki oznacza usunięcie; metadane odróżniają tę nieobecność od tombstone z jawną rewizją. Nie jest wymyślana rewizja usunięcia.
- Wersje celów pozostają niezmienne. Wycofana wersja jest pomijana w bieżących odczytach przez metadane; jej historyczny rekord nie jest aktualizowany ani usuwany.
- Starsza kopia lub rewizja niż już lokalnie potwierdzona nie cofa dziennika. Konflikt tożsamości z innym właścicielem cofa całą projekcję.
- Usunięty profil jest rozpatrywany przed jego nową wersją pod innym UUID. Dawny tombstone nie usuwa innego, aktualnego profilu i nie tworzy fikcyjnego konfliktu. Niewysłana lokalna zmiana profilu nadal zatrzymuje obie serwerowe wersje do uzgodnienia.

## Jednostki, braki i migracja

Prywatny produkt zachowuje dokładny payload, jednostkę g/ml, gramaturę opakowania, źródło i udokumentowaną gęstość. Brak kcal lub B/T/W pozostaje brakiem danych. Wybranie takiego produktu zapisuje dokładny posiłek bez wymyślania oficjalnego identyfikatora katalogu i bez publikacji szkicu. Przy obliczeniach dokładny payload ma pierwszeństwo przed techniczną projekcją REAL używaną przez katalog.

Lokalna porcja może zachować12miejsc po przecinku. Obliczenia i lokalny snapshot `private_product` utrzymują pełną ilość, jednostkę, źródło i pola null również podczas późniejszej edycji. Kanoniczny producent nadal respektuje limit6miejsc kontraktuAPI; dokładniejszy wpis pozostaje w formacie legacy z pełnym snapshotem, bez zaokrąglenia i bez zamiany brakujących kcal na zero. Taki snapshot nie jest oficjalnym produktem katalogu i wymaga uwzględnienia w przyszłym adapterze legacy.

Wzrost profilu może pozostać pusty. Migracja16→17 dodaje dwie tabele metadanych oraz nullable products.wirePayload, a profiles przebudowuje z nullable heightCm. Przenosi wszystkie wcześniejsze kolumny oraz jawne rowid. Nie przelicza starych wartości, nie konwertuje kolejki legacy i nie zmienia reguł niezmienności celów.

## Granice etapu

To pełny odczyt w aktualnym zdrowym kontekście konta. Specjalne uzgadnianie po zmianie epoki, przypisywanie gościa i konwersja kolejki legacy, kanoniczne wysyłanie profilu/celów/kompletności/szkiców oraz WorkManager pozostają kolejnymi etapami. Zachowane lokalne zmiany tych starszych typów nie są przedstawiane jako wysłane. Odczyt nie udziela zgód rankingu, Gemini ani automatycznej korekty celu. Nie uruchamia nowego testu live E4, wdrożenia lub zmian środowiska O3.

Archiwum stron nadal ma wcześniejsze limity: maksymalnie osiem prób i128MiB na właściciela,64MiB/100000rekordów/2000stron na pojedynczą próbę. Przekroczenie limitu zatrzymuje kolejne pobranie, zachowując poprzednią kopię, dziennik i kolejkę. Bezpieczne zwalnianie archiwów z uwzględnieniem odwołań niepewnych partii oraz historii konfliktów wymaga osobnego etapu; nie należy usuwać ich ręcznie z bazy.

## Odbiór lokalny — 23.10.2026

- Debug, validation i test APK: build PASS; lint: 0 błędów, 4 ostrzeżenia.
- Pierwszy zestaw: 40 wybranych JVM PASS; na urządzeniu 54/55 PASS. Jedyny błąd dotyczył asercji tekstu licznika w UI — wyświetlana wartość 4/2 była poprawna. Zachowano raport nieudanego przebiegu.
- Po przeglądzie usunięto również błąd kolejności usunięcia/odtworzenia profilu i utratę precyzji prywatnej porcji. Końcowe 6 JVM zmienionego protokołu oraz 13/13 przypadków urządzenia API 35 offline: PASS, bez pominięć. Pozostałych 35 niezmienionych JVM nie powtarzano.
- Końcowe 13 obejmuje 10 testów składowania, migrację 16→17 i 2 przepływy UI. Testy potwierdzają wszystkie sześć domen, wycofanie całej transakcji, ochronę kolejki, idempotencję, starsze kopie, odtworzenie profilu, dokładną porcję i brakujące kcal. Nie stanowią pełnej regresji całej aplikacji.
- SHA-256 końcowego logu urządzenia: `88868ca0a2387f37d4be8776cd50eb8153b45bb984242fd8056546127eb0f4a2`.
- Zdalny CI, instalacja zwykłej aplikacji i rzeczywisty test APK/API są osobnymi wynikami.
