# Niezależny odbiór E4 - osoba 2

Ocena końcowej implementacji: **9,2/10**, brak istotnych nierozwiązanych
usterek. Recenzent e4_review nie jest autorem ocenianych modułów. Używał
osobnej bazy PostgreSQL17.11, oddzielnych SQLite i własnego efemerycznego
realmu Keycloak; nie zaliczał odczytu kodu lub fixtures jako PASS integracji.

Sam wykonał pełne 469 unit + 401 PostgreSQL + 9 real Keycloak/PKCE =
879 PASS, bez skipów. Po ostatniej drobnej zmianie sprawdzania dokładnej
wersji produktu ponowił cały push/live HTTP: 29 PASS, w tym nowe granice
chunked i counterMAX. Dodatkowa własna próba istniejącego product_id z
brakującą dokładną revision dała trwałe dependency_missing bez półzapisanego
dnia; rzeczywisty BIGINT MAX nie utworzył receipt ani encji i nie zawinął H.

Własne probes obejmują foreign source i inny typ, równoczesny RecoveryMapping,
usunięty target, stabilny final checkpoint/TTL, rzeczywiste bajty/+1/zero DML,
SELECT1/0 po pierwszym commit i retry prefixu, trwałe SQLite i 12→6/underflow,
A→B→A oraz trzy dowody pg_blocking_pids: rollback pierwszej transakcji,
DB clock po oczekiwaniu i prefix przed wygaśnięciem checkpointu. Dziewięć
pierwszych zostało dołączonych do regresji jako test_e4_independent_regressions.

E0/schematy/scenariusze, Ruff, zasoby, sdist/wheel oraz Python -I po instalacji
poza checkoutem: PASS. Recenzent porównał 66 runtime plików PY/JSON wheel
z końcowymi źródłami. Przejrzał dokumenty E4 i poprawione reguły preflight/prefix
w wymaganiach i E0.

Pierwsza pełna niezależna regresja miała 320 PASS/72 FAIL z powodu nowego
testu upgrade, który odtwarzał schemat bez jego default ACL. Naprawiono wyłącznie
fixture, zachowując rzeczywisty provisioning; końcowy pełny przebieg 401 PASS.
Pierwszy counterMAX test ustawiał nieistniejący jeszcze licznik (UPDATE0rows).
Naprawiono seed INSERT/ON CONFLICT i ponowiono właściwe testy. Problemy te
nie są ukryte przez skipy lub poszerzanie praw produkcji.

Rzeczywisty test provider używał osobnego service account bez master/realm-admin,
syntetycznego usuwanego A i niezależnego B. Potwierdzono PKCE, odmowę
nieuprzywilejowanego service account, DELETE/authorized absence/crash retry,
odmowę refresh/login i starego JWT oraz niezmienny B/katalog.

Ocena dotyczy backendu/klienta O2. Końcowy zdalny CI odczytuje autor po push;
Room/APK/WorkManager/KO-31 i produkcyjny restore obu baz z zewnętrznym
rejestrem usunięć pozostają odbiorem O1/O3. Nie wykonywano merge E4/E5.
