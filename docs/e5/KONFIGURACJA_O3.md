# Konfiguracja odczytów E5 - osoba 2

Migrator wykonuje upgrade head do0012_e5_reads po odebranym0011_e4_deletion. Migracje0001–0011 są niezmienione. Readiness wymaga0012 oraz dotychczasowego trwałego CATALOG_PAGE_TOKEN_SECRET. API zachowuje DATABASE_URL/OIDC_ISSUER/OIDC_JWKS_URL; nie dodajemy sekretu do APK. Klucz32losowe bajty jako hex musi być ten sam między replikami/restartami; read1 ma osobną pochodną domenę HMAC. Rotacja unieważnia tokeny stron, nie encje/outbox/checkpointy.

## Modele i ACL

Nowe read_sessions/read_session_items to prywatne techniczne kopie; właściciel/FK, indeks owner/expiry, fixed TTL60min i DB checks dat/liczności/rozmiaru. API ma SELECT/INSERT i tylko UPDATE liczników sesji, bez DELETE, zmiany context lub kopii. Worker nie czyta payloadów; ma jedną funkcję sprzątania SECURITY DEFINER ze stałym search_path i kontrolą active owner. Operator deletion nie dostaje nowych praw tabel.

Techniczna bramka przyjęcia sesji serializuje limit4 przy REPEATABLE READ. Właściciel nowej kopii/admission ma FK CASCADE do konta, a elementy CASCADE do sesji; istniejąca potwierdzona procedura purge konta usuwa wszystkie nowe dane. Usunięcie/restore odcina stary token przez sprawdzenie dostępu/kontekstu przed lookup. Downgrade usuwa wyłącznie te odtwarzalne kopie/bramkę, zachowując wszystkie dane E4 i epokę; strony wymagają ponownego odczytu. Stary obraz przy0012/readiness wymaga uzgodnionego rollbacku, nie automatycznego pominięcia sprawdzenia.

## Retencja i limity

Dotychczasowa komenda `python -m calorie_app.modules.sync.retention OWNER_UUID --batch1000` (pisownia CLI: `--batch 1000`) w jednej transakcji wywołuje prune_sync oraz prune_read_sessions. Worker uruchamia ją okresowo również dla kont bez ruchu HTTP. Read_items/read_sessions w wyniku opisują tylko techniczne usunięcia; minimalne receipts/żywe encje pozostają. Przy większym backlogu powtarzaj ograniczone partie aż wynik spadnie poniżej limitu, z monitorowaniem latency/backlog i bez payloadu. Blokada konta/licznika poprzedza sprzątanie.

Limit sesji4,100000elementów/64MiB, TTL60min, rekord512KiB, strona1MiB UTF-8/<=500 rekordów. Błąd503 read_resources_exhausted wymaga backoff/nowego odczytu po wygaśnięciu, bez zwiększania limitu na ślepo. Diary-day completeness ma osobne granice pracy; statystyki100000wierszy wejścia i10000wersji celu,15s SQL/5s blokady. Monitoruj503/422 statistics_resource_limit; nie prezentuj fragmentu jako pełnej historii.

Reverse proxy zachowuje Cache-Control:no-store również dla401/403/409/410/422/503 oraz redirect/middleware; nie przechowuje tokenu ani prywatnego payloadu. HTTPS/issuer osiągalny z APK pozostają oddzielnym odbiorem O3. Nie wdrożono produkcji.

[Procedura E4](../e4/KONFIGURACJA_O3.md) nadal wymaga odcięcia ruchu/workerów na restore, nowej epoki i zewnętrznego rejestru deletion. Nowe read tokeny/sesje nie są checkpointami ani zgodą na replay starej kolejki.

Jednostronicowa pierwsza odpowiedź bez next_page_token nie zachowuje niepotrzebnej kopii: API wywołuje wyłącznie wąskie discard z kontrolą właściciela/generacji/epoki w tej samej transakcji. Admission tuple pozostaje. Puste/single odświeżenia nie zajmują slotów ani nie tworzą rosnącego backlogu; stronicowane kopie nadal istnieją do TTL dla retry końcowej strony. Granice pracy kompletności dni: do 10000 posiłków, 100000 pozycji i 8 MiB UTF-8 na partię do 32 lokalnych dat.
