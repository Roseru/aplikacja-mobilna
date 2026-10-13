# Android — trwałe pobieranie kopii serwera, 0.8.3

Właściciel: O1 / agent 1. Gałąź `codex/android-sync-pull`, od main `bf868ecef836dbfa72781562f5949d8415bc9099`. Jest to pierwszy mobilny element E4: pełna kopia odpowiedzi serwera, zapisana osobno od lokalnego dziennika. Odczyt korzysta z istniejącego GET `/api/v1/sync/pull`; nie dodaje endpointów backendu.

## Działanie

Po potwierdzonym logowaniu i bootstrapie na ekranie Konto można wybrać **Pobierz kopię danych serwera**. Przycisk inicjuje pełny snapshot z `sync_epoch` i `limit=100`. Kontynuacja wysyła dokładnie zapisane `snapshot_token` i `page_token`. Po przerwaniu kolejna próba w tej samej generacji właściciela i kontekście wznawia pobieranie. Zmiana konta lub A→B→A wymaga nowej próby; wcześniejsze strony pozostają zachowane.

Każda strona i następny token zapisują się w jednej transakcji Room. Dopiero ostatnia strona zapisuje checkpoint oraz wskazanie aktywnej pełnej kopii. Wcześniejsza kompletna kopia pozostaje aktywna podczas pobierania kolejnej. Ponowienie identycznej kanonicznej odpowiedzi jest idempotentne; zmieniona powtórka, powtórzone UUID, zmiana tokenu lub osi celów oraz cykl tokenów przerywają stronę bez przesunięcia postępu.

Kopia jest **archiwum wire**, bez projekcji na lokalne posiłki, wagę czy cele. Przechowuje sześć rodzajów encji, tombstones, mappings i receipts w kanonicznym JSON. Walidacja struktury korzysta z przypiętych kopii normatywnych `common`, `domain` i `sync.schema.json` w assets; kopie testowe mają te same bajty. Interpreter obsługuje tylko słowa kluczowe użyte w tych schematach i odrzuca nieznane. Nie jest ogólnym silnikiem JSON Schema ani kompletną walidacją semantyki domenowej. Przyszłe projekcje muszą osobno sprawdzać relacje, daty/strefy, nutrition_v1 i decyzje celów.

Lokalne oryginały, profile, wersje celów i outbox pozostają nietknięte. Receipt w kopii nie oznacza ACK lokalnej operacji. Nie ma automatycznego importu gościa, wysyłki, materializacji wire, inkrementalnego pull, WorkManager ani zakończenia recovery. Checkpoint archiwum nie certyfikuje gotowości lokalnej kolejki do push.

## Kontekst, HTTP i błędy

- Przed wysyłką i zastosowaniem kontrolowane są potwierdzony ticket OIDC, rewizja sesji, lease, account_id/account_generation, sync_epoch i contextRevision. HTTP odbywa się poza mutexem. Logout, refresh lub nowe logowanie unieważniają starą odpowiedź.
- System TLS, wyłącznie skonfigurowana baza HTTPS `/api/v1`, brak redirect/cache, GET bez body i dodatkowych nagłówków sync. Query kodowane jako UTF-8; token nie staje się częścią ścieżki lub dodatkowym parametrem.
- Sukces ma limit 4 MiB, błędy 64 KiB; 15 s connect/read, budżet 30 s. Ścisłe UTF-8/JSON, kontrola Content-Type/Encoding i wielkości również bez Content-Length. Tekst serwera i tokeny nie trafiają do UI/logów. SyncError ma obiekt `details`, odrębny od błędów bootstrapu.
- 401 `unauthorized`: najwyżej jedno potwierdzone odnowienie i ponowienie tej samej strony. 429/503: wspólny trwały Retry-After w zaszyfrowanej pamięci sesji, również dla HTML proxy. Brak ukrytych pętli retry.
- 410 `snapshot_expired`/`sync_cursor_expired`: oznaczenie starej próby jako wygasłej i nowy pełny snapshot po świadomym ponowieniu. Poprzednie strony i aktywna kopia pozostają.
- 409 zmiany epoki/generacji lub wymaganego uzgodnienia: trwały requiresRecovery i nowa rewizja kontekstu bez podmiany mapowania. Trwała blokada pamięta ID dotychczasowego bootstrapu; tylko inne ID z potwierdzonym responseJson odblokowuje odczyt. Sam pending bootstrap lub ponowienie nie wystarcza. Należy ponownie wykonać bootstrap i uzgodnienie. Pełne pobieranie jest dozwolone także w recovery, lecz nie usuwa flagi ani nie zezwala na push.
- 403 `account_deleting`: trwała blokada kolejnych pobrań, zachowanie sesji offline i wszystkich danych. Ponowny bootstrap nie usuwa tej blokady. Przyszły adapter push musi również respektować tę blokadę.

## Room i granice magazynu

Migracja **6→7** dodaje `server_snapshot_runs`, `server_snapshot_pages`, `server_snapshot_identities` i `server_snapshot_access`. Nie przebudowuje wcześniejszych 18 tabel. Kontrola unikalnych tożsamości wykorzystuje indeksowany klucz zamiast ponownego skanowania całego archiwum przy każdej stronie. Idempotencja strony sprawdza zapisany query i canonical response; stan strony/token/checkpoint/pointer jest atomowy.

Budżet próby: 100000 rekordów, 2000 stron, 64 MiB kanonicznych odpowiedzi. Budżet właściciela: 8 zachowanych prób i 128 MiB odpowiedzi. Po wyczerpaniu pojawia się komunikat o pełnej pamięci, bez automatycznego kasowania kopii lub oryginałów. Do kolejnego etapu należy świadome porządkowanie archiwum z zachowaniem dowodów potrzebnych do uzgodnienia. Te limity dotyczą odpowiedzi; indeksy i SQLite wymagają dodatkowego miejsca. SQLITE_FULL ma wycofać całą stronę.

## Odbiór i dalsza praca

Domyślne issuer/API pozostają puste; zwykły APK działa offline. Testy zastępczego transportu nie zastępują rzeczywistego odbioru API/TLS/Keycloak. Potrzebne istniejące środowisko O3 i jego validation-only overlay, zgodnie z O1-015. Nie inicjalizować nowego środowiska, nie zmieniać issuer i nie wyłączać TLS.

Scenariusze manualne po konfiguracji: login A → bootstrap → pobranie co najmniej dwóch stron → odcięcie internetu → restart procesu → wznowienie → ostatnia strona; poprzednia kopia widoczna do końca, lokalne posiłki/waga/outbox bez zmiany. Osobno logout/B/A, refresh w trakcie, wygaśnięcie snapshotu i recovery. Gość zapisuje posiłki całkowicie offline.

Następne elementy E4: semantyczne projekcje i jawne konflikty/nieobecności, niezmienna wersjonowana materializacja lokalnego outbox, kompletne ACK push, inkrementalny pull, jawne przypisanie gościa, recovery mappings/receipts i WorkManager. Nie są zamknięte przez ten etap. Wyniki lokalnego odbioru znajdują się w raporcie 0.8.3.
