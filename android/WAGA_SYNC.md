# Synchronizacja pomiarów wagi — O1

Etap0.8.25/code36/validation1036, Room15. Gałąź `codex/android-waga-sync`
powstała z PR140/25f7e4c; teraz dołącza main e1e28df po scaleniu140.
Nie zawiera niezależnego drivera138.
Status odbioru lokalnego22.10.2026: build debug/validation PASS,30 wybranych
JVM PASS uruchomione raz na końcu etapu; lint0error/4warning/1info. Po poprawkach
testów pełny native API35 offline336/336PASS,0fail/0skip,2179,09s; obejmuje5
nowych scenariuszy Weight. [Metadane odbioru](ODBIOR_0_8_25.json) utrwalają źródła i SHA.
Zwykła aplikacja0.8.24/code35/Room14 została zaktualizowana do0.8.25/code36/
Room15 bez clear/uninstall. Wszystkie27starych tabel, ich wartości i rowid
pozostały identyczne; FK czyste. Aplikacja otwarta do prób ręcznych.

Pierwszy pełny przebieg miał334/336PASS; po poprawkach opcjonalnych indices
fixture i odsłonięciu podglądu zdjęcia6/7PASS, oba testy zdjęć PASS. Następnie
naprawiono kopiowanie REAL w fixture przez getDouble().toString() i sprawdzono
dokładną wartość również przed migracją. Ścisłe asercje po migracji pozostały.
Końcowe336/336PASS dotyczą tej poprawki; wcześniejszych błędów nie usunięto z dowodów.

Produkcja pochodzi zff0d766caad85803784e572d67cd52dfcce36c1e, testAPK z
d624712b332bf57bc032a12d9fc79442dd013d91. Po poprawkach wyłącznie testów
nie ponawiano JVM i nie przebudowano produkcji; APK identyczne bajtowo.
Zwykły merge aktualnego main po140 zachowuje całe przetestowane android/app
i Gradle. Odbiór własnego CI nowego head/base141 pozostaje osobnym warunkiem merge.

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
i rowid. Wszystkie te przypadki są objęte końcowym336/336PASS.

Pozostają osobne: rzeczywisty APK/API, pełne pull/reconciliation i rozwiązanie
konfliktu w UI, import gościa/historycznych wpisów, inne typy dziennika,
WorkManager, używany schema24/epoka/konta, E4/E7-R/recovery/KO32. Ten etap nie
wywołuje Gemini, nie otwiera relay i nie zmienia środowiska Agenta3. Zwykły
APK zaktualizowano do0.8.25 dopiero po kwalifikacji; prywatny dziennik zachowany.


Artefakt lokalny: `Racje-i-kalorie-0.8.25-debug.apk`, źródło `ff0d766caad85803784e572d67cd52dfcce36c1e`, SHA-256 `167082026db6d89ccbecc6989f8457bd0ef6bd2942d8b9b4b8699395fd61d9a9`. APK/manifest/SHA256SUMS pozostają lokalną dostawą, bez publikowania buildów w repozytorium. Pierwszy podgląd zasłonił komunikat Android System UI; następna obserwacja potwierdziła samoistne ustąpienie komunikatu i gotową aplikację, bez jej restartu lub wyboru Wait.
