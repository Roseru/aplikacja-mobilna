# Synchronizacja pomiarów wagi — O1

Etap0.8.25/code36/validation1036, Room15. Gałąź `codex/android-waga-sync`
zależy od dokładnego PR140/25f7e4c. Nie zawiera niezależnego drivera138.
Status: kod debug/validation i testy urządzenia skompilowane (10m2s),
schemat15 wygenerowany. Testów jednostkowych i urządzenia tego etapu
jeszcze nie wykonywano; następnie jeden końcowy odbiór całego etapu.

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
i rowid. Wyniki zostaną dopisane po końcowym uruchomieniu etapu.

Pozostają osobne: rzeczywisty APK/API, pełne pull/reconciliation i rozwiązanie
konfliktu w UI, import gościa/historycznych wpisów, inne typy dziennika,
WorkManager, używany schema24/epoka/konta, E4/E7-R/recovery/KO32. Ten etap nie
wywołuje Gemini, nie otwiera relay i nie zmienia środowiska Agenta3. Zwykły
APK0.8.24 i prywatny dziennik nie zostały podmienione przed kwalifikacją.
