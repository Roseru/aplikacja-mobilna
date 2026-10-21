# Spożycie produktów katalogowych i składników racji w synchronizacji

Agent 1, 21.10.2026, `codex/android-posilki-katalogowe-sync`.
Zależność: dokładny `a1f547a398e878b4f6429ffdb1b7a99f0903e51d` / PR139.
Implementacja do odbioru końcowego; testy nowego etapu jeszcze niewykonane.

Po bootstrapie konta zwykły wybór produktu z pakietu E2 lub zaznaczonych
składników racji zapisuje Meal i operację sync-v1 w jednej transakcji Room.
Wysyłka odbywa się później przez istniejący panel synchronizacji; dodawanie
posiłku nie wywołuje API i nie wymaga aktualnego tokenu ani połączenia.

Snapshot pochodzi z dokładnego produktu i rewizji katalogowej. Zachowuje
ilość, jednostkę g/ml, wartości na 100, null i zero oraz rzeczywiste źródło
gęstości. Nie odtwarza danych z przybliżonych pól Double. Racja zawiera tylko
zjedzone składniki i ich oryginalne pozycje; referencje produktów, rewizje,
jednostki i limit porcji są sprawdzane względem składników tej wersji racji.
Nie sumuje się alternatywnych wariantów ani pozycji niezaznaczonych.

Lokalne klucze produktu/racji, ID składnika, pełny snapshot i źródła pozostają
w dzienniku. Wire używa osobno UUID i rewizji serwera, bez publikowania lub
zmieniania katalogu. Edycja kanoniczna nadal zachowuje lokalne metadane.
Zapis posiłku i jego operacji jest atomowy; błąd kolejki wycofuje całość.

Gość, konto bez bootstrapu, recovery, starsze produkty bez tożsamości E2
oraz ilości niewyrażalne w wire-v1 zachowują dotychczasowy zapis lokalny.
Nie wymyślamy UUID, nie nadajemy pochodzenia manual produktom katalogowym
i nie zaokrąglamy ilości dla wymuszenia wysyłki. Późniejszy adapter legacy,
import gościa i recovery są osobnymi częściami synchronizacji.

Pochodzenie `catalog_snapshot` nie potwierdza weryfikacji źródeł. Demo nadal
pozostaje demo. Obecność lokalnej rewizji nie dowodzi jej dostępności na
konkretnym serwerze; odrzucenie API musi zachować dane/kolejkę. Ten etap nie
zmienia usług O3, schematu, epoki, kont ani katalogu serwera.

Bez migracji Room (14). Odbiór końcowy obejmie raz testy nowej konwersji
i bezpośredniej regresji MealWire oraz scenariusze Room zapisu, wybranych
składników, edycji, rollback i lokalnego fallback. Jednostkowych testów
nie uruchamiamy po każdej edycji. Pełny zdalny CI będzie wymagany przy
integracji stosu do main; lokalne sprawdzenie nie zastępuje tego CI.
