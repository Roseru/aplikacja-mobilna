# Spożycie produktów katalogowych i składników racji w synchronizacji

Agent 1, 21.10.2026, `codex/android-posilki-katalogowe-sync`.
Zależność: dokładny `a1f547a398e878b4f6429ffdb1b7a99f0903e51d` / PR139.
Odbiór lokalny zakończony21.10.2026; etap pozostaje zależny od niescalonego PR139.
Wersja0.8.24/code35, validation1035; Room14 bez nowej migracji.

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


## Odbiór lokalny 21.10.2026 — O1-093

Źródło APK: `e68c4e56b691d782fb7c3c72a3f1d9a82c274cb4`.
Kod funkcji0f0a811, wersja0.8.24/code35/validation1035/Room14; bez migracji.

- Build debug/validation/testAPK PASS w 680.95s. Wybrany
  zestaw **13/13 JVM PASS**:3 nowe przypadki konwersji i10 bezpośrednich
  regresji MealWire,0fail/errors/skips. Uruchomiony raz na koniec etapu;
  nie wykonywano ponownie pełnych zestawów JVM obu wariantów.
- **11/11 native PASS**,0fail/0skip,28.75s:
  3 nowe scenariusze katalogu i8 regresji ręcznych posiłków. Sprawdzają
  rzeczywisty DiaryRepository/Room: atomowy zapis i rollback, tożsamość
  katalogu, wybrane składniki, edycję z zachowaniem źródeł, idempotencję
  oraz fallback gościa, braku bootstrapu, recovery i nadmiernej precyzji.
  To wybrane scenariusze, nie pełny przebieg331 skompilowanych testów.
- Lint0error/0fatal,4warning/1info. O1Tests35/5556 offline; install-r
  zachował29tabel SQLite (także techniczne),Room14/FK clean. SHA rzeczywiście
  zainstalowanych APK zgodne z artefaktami.
- Zwykły CodexCalories/5554 zaktualizowano z0.8.23/code34 do0.8.24/code35.
  Wszystkie wartości27tabel aplikacji i rowid składników zachowane przed/po
  instalacji; prywatne kopie poza Git/OneDrive,Room14/FK clean. MainActivity
  uruchomiona. Bez clear/uninstall/wipe, restartu PC lub podmiany API5558.

| Artefakt | SHA-256 |
|---|---|
| debug/code35 | `91f3061f1d952b4ae2d8e8d6b4d77bf82cda0eb550fc33b202a29aed3a431fe7` |
| validation/code1035 | `64aa09f2fdd39a3a793c0a633a84b76a0d110cb477e2a45ee4ac37ee2638cd9c` |
| testAPK | `6c4c005cf96a82282cc1cabf41d975296dda0ea8027bb5d9c4e18d851fc28f68` |

Log11native SHA256:`31d43cd4fc5e1285b21fc263311b797ed6fa664b335e96b2dd23ac89a333f015`.
Pakiet debug poza Git:output-apk/catalog-meals-e68c4e5, APK/manifest/SHA256SUMS.
Wejścia i wszystkie3APK sprawdzono po zakończeniu odbioru.

To APK offline bez issuer/API. Nie wykonywano rzeczywistego katalogowego
POST/replay ani Gemini. Zgodność z konkretnym serwerem, połączenie z driverem
E4 i pełny zdalny CI po integracji rodziców pozostają osobnymi odbiorami.
Nowy katalog nie został opublikowany ani zmieniony na serwerze.
