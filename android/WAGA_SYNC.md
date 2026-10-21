# Synchronizacja pomiarów wagi — O1

Etap0.8.25/code36/validation1036, Room15. Gałąź `codex/android-waga-sync`
zależy od dokładnego PR140/25f7e4c. Nie zawiera niezależnego drivera138.
Status checkpointu 21.10.2026: build debug/validation PASS, 30 wybranych
testów JVM PASS (jedno uruchomienie na koniec etapu), lint bez błędów.
Pierwszy pełny przebieg urządzenia: 334/336 PASS, dwa błędy testów.
Po poprawieniu obsługi brakujących indeksów w fixture oraz przewinięcia
podglądu zdjęcia: 6/7 PASS, w tym oba testy zdjęć. Pozostały test migracji
wykazał utratę precyzji podczas kopiowania REAL przez Cursor.getString.
Fixture używa teraz getDouble().toString() i sprawdza wartość również
przed migracją. Ta ostatnia poprawka wymaga kompilacji i wykonania testu;
ponowny pełny odbiór 336 testów pozostaje do zrobienia. Etap nie jest odebrany.
Produkcja pozostaje na ff0d766; poprawki po tym commicie dotyczą testów
i dokumentacji. Zwykły APK użytkownika nie został podmieniony.

Nowy pomiar konta po zdrowym bootstrapie zapisuje pomiar, dokładny payload
Weight i operację sync-v1 w jednej transakcji. UI zachowuje zakres20–400kg;
wire waliduje istniejący kontrakt E0, Decimal jako tekst, UTC z mikrosekundami,
strefę i zgodność daty lokalnej. Lokalny zapis o precyzji przekraczającej
kontrakt pozostaje w dotychczasowym formacie, bez zaokrąglania. Gość,
niepowiązane konto i dane legacy również zachowują lokalną ścieżkę.

Osobna tabela `canonical_weights` zawiera wyłącznie metadane nowych
kanonicznych pomiarów. Migracja14→15 tworzy tabelę i indeks; nie przebudowuje
starych tabel ani nie zmienia istniejących pomiarów, kolejki lub rowid.
Wszystkie starsze ścieżki migracji mają dołączony nowy krok. Historyczne
pomiary nie są automatycznie uznawane za potwierdzone lub przepisane na wire.

Zapisana partia może zawierać posiłki i pomiary. Po pierwszej próbie jej
bajty, hash, operation_id i pierwotny checkpoint są niezmienne. Nowa poprawka
w czasie lotu czeka na ACK pierwotnej operacji, następnie otrzymuje prawdziwą
rewizję bazową. Odbiór aktualizuje stan obu typów oraz kolejkę i partię atomowo.
Usunięcie przed pierwszą próbą pozostaje lokalnym tombstone, a po zapisie
serwerowym tworzy operację delete z rewizją. Konflikt/rejected zachowują dane.
Zmiana konta/kontekstu i recovery blokują zwykłe wysyłanie; lokalna poprawka
kanonicznego pomiaru zostaje zachowana jako oczekująca na uzgodnienie.

Przygotowane scenariusze: dokładne Decimal/data/strefa, identyczna koperta,
łączenie zmian przed wysłaniem, restart i utrata ACK z późniejszą poprawką,
delete po ACK, mieszana partia Meal+Weight i rollback późniejszego zapisu,
gość/unlinked/precyzja/recovery/izolacja oraz14→15 z zachowaniem starych tabel
i rowid. Końcowy wynik po ostatniej poprawce pozostaje do uzupełnienia.

Pozostają osobne: rzeczywisty APK/API, pełne pull/reconciliation i rozwiązanie
konfliktu w UI, import gościa/historycznych wpisów, inne typy dziennika,
WorkManager, używany schema24/epoka/konta, E4/E7-R/recovery/KO32. Ten etap nie
wywołuje Gemini, nie otwiera relay i nie zmienia środowiska Agenta3. Zwykły
APK0.8.24 i prywatny dziennik nie zostały podmienione przed kwalifikacją.
