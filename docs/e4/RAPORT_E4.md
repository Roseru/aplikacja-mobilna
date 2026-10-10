# Raport synchronizacji E4 - osoba 2

Data: 10 października 2026. Agent 2 / O2. Gałąź:
`codex/backend-e4-synchronizacja`; baza `fa5684b` po dozwolonym merge
odebranego PR #11 (head7669f2a, wszystkie pięć jobów finalnego CI success,
ponowny odbiór poprawki DELETE). Zastane nieśledzone materiały, `.review-o2/`
i Random Data zachowano. PR E4 pozostaje do osobnego odbioru; bez merge/E5.

## Wynik i architektura

POST /api/v1/sync/push i GET /api/v1/sync/pull realizują sześć prywatnych
typów, trwałe receipts, commit-order ChangeLog, checkpointy, materializowane
snapshoty/incremental, ograniczoną retencję i RecoveryMapping. Router obsługuje
transport i commit; service/repository reguły i owner queries; E3 pozostaje
źródłem reguł encji. Szczegóły decyzji, transakcji i granic:
[v1](DECYZJE_V1.md). DTO normatywne są zasobami wheel/obrazu, runtime nie
importuje walidatora E0; draft HTTP sync usunięto z aktywnego design OpenAPI.

Trwały [klient SQLite](../../tools/sync_client/README.md) demonstruje dwa
urządzenia, immutable wire, oryginały, shadow/staging, ACK/restart, Decimal,
guest binding, konflikty i świadome recovery. [CLI deletion](USUNIECIE_KONTA.md)
kończy konto przez oddzielny service account Keycloak i wąski potwierdzony
purge. Brak endpointu samousunięcia, Androida, produkcyjnego deploymentu,
statystyk E5, Gemini lub funkcji późniejszych etapów.

## Migracje, kompatybilność i retencja

0009_e4_sync → 0010_e4_retention → 0011_e4_deletion rozszerzają odebrane
0008. Stare migracje pozostają niezmienne. ACL API/worker nie poszerzono
o fizyczne DELETE rodziców/DDL/TRUNCATE; retencja i purge mają oddzielne
SECURITY DEFINER z fixed search_path, bez runtime GUC lub wyłączania guardów.
Compatible rollback do 0008 zachowuje minimalne dowody i zabezpieczenia.
Stary obraz E3 nie obsługuje sync; powrót wymaga świadomego zamknięcia ruchu E4.

Minimalne dowody, mapowania i rezerwacje trwają do usunięcia konta. Rodzice
i tombstones są konserwatywnie zachowane także po zminimalizowaniu szczegółów
>=60dni. Aktywne kopie i ważne checkpointy pozostają chronione. Cele/katalog
oraz historyczne snapshoty nie są przepisywane.

## Wykonanie i odbiór

Autor: pełne **469 unit + 401 PostgreSQL17.11 + 9 real Keycloak/PKCE =
879 PASS**, bez skipów. Po ostatniej zmianie ponowiono cały push/live HTTP
oraz niezależne regresje: **38 PASS**, w tym pięć nowych przypadków.
Łącznie wykonano 406 różnych przypadków PostgreSQL, lecz końcowy pełny
zdalny przebieg wszystkich 406 zostanie odczytany z CI. Ruff122/format,
schematy/resources, E0 (67 valid/20 invalid/18 scenarios/82 HTTP, 16 Decimal,
200 linków), OpenAPI, sdist/wheel i installed wheel Python -I poza checkoutem:
PASS. Obrazu nie budowano lokalnie; właściwy build/smoke wykonuje CI head.

Recenzent sam: pełne 879 PASS, końcowy push/live29 PASS, własne probes,
opakowanie i dokładność 66 plików wheel. **9,2/10 bez istotnych nierozwiązanych
usterek**, [szczegóły](RECENZJA_O2.md). Rzeczywisty restore starszej DB,
barierowe pg_blocking_pids, minimalne receipts61dni, raw ACL/purge,
SQLite/restart oraz real provider wykonano; fixtures E0 nie są ich dowodem.

Pierwsza pełna regresja ujawniła brak modeli deletion w Base.metadata,
dawne założenia testów migracji i niepełny provisioning; naprawiono je.
Nowy test upgrade odtwarza również default ACL po DROP SCHEMA;
cała poprawiona regresja przechodzi. Seed counterMAX poprawiono z UPDATE0rows
na INSERT/ON CONFLICT i sprawdzono ponownie. Nie zaliczano nieudanych ani
niewykonanych prób. Wcześniejsze 707 PASS E3 nie jest wynikiem E4.

Nie zaliczamy skipów ani odczytu kodu jako wykonania integracji. Niezależny
recenzent nie jest autorem implementacji. [O1](INTEGRACJA_O1.md) oraz [O3](KONFIGURACJA_O3.md)
dostają wymagane komendy i granice. Odbiór O2 nie oznacza Room/APK/WorkManager,
KO-31 ani produkcyjnego restore/RPO. Produkcyjny issuer/HTTPS, odbiór obu
baz z zewnętrznym rejestrem deletion i mobilna integracja pozostają O1/O3.
