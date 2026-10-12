# Konfiguracja motywacji E8.1 + E8.2 - osoba 2

12 października 2026. To przekazanie [decyzji](DECYZJE_MOTYWACJA.md), nie deklaracja produkcyjnego wdrożenia lub odbioru O3.

## Provision i migracja

Dodana linia Alembica0016_e8_motivation po0015_e7_ai;0001–0015 niezmienne. Przed upgrade należy utworzyć base role calorie_app_motivation_worker NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS. [Bootstrap](../../infra/local/init-db.sh) zawiera ją dla nowych środowisk. Istniejącego AI/retention/API/deletion LOGIN nie przestawiaj na nową rolę.

Migracja odmawia atomowo przy braku roli, jej nadmiarowych membership/table/column/DDL/function effective privileges lub przy odziedziczonym dostępie PUBLIC. Migrator stosuje DATABASE_URL; normalny krok alembic upgrade head. Nie dopisuje historycznych markerów racji ani świeżej zgody. Istniejące konta zaczynają pending; nic nie publikuje fałszywego historycznego zera.

[Provisioner](../../infra/local/provision_motivation_worker.py) uruchamiaj administracyjnie ze standardowym PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD lub pgpass/service, MOTIVATION_WORKER_LOGIN i MOTIVATION_WORKER_PASSWORD wyłącznie w chronionym środowisku, nigdy argv. python infra/local/provision_motivation_worker.py tworzy własny odrębny LOGIN i lokalnie zaszyfrowany SCRAM po kontroli logging guards/effective ACL. Nadaje tylko bieżący app/test CONNECT, base membership, zamknięty search_path i właściwe timeouts. Nie używaj sekretów ani logów testów w produkcji. PUBLIC CONNECT do postgres/templates i zewnętrzne audit proxy są osobną polityką O3.

Worker otrzymuje EXECUTE e8_process/e8_candidates/e8_status/e8_prune_ranking_sessions oraz SELECT wyłącznie installation_state/alembic_version. Bez raw diary lub raw projekcji/punktów, bez DDL/deletion/AI. API nie ma raw DML projekcji/odznak/markeru; wyniki wyznaczają funkcje źródłowe. Wewnętrzny e8_clock jest prawdziwym clock_timestamp i nie jest publicznie wykonywalny; testy disposable DB mogą podmienić jego body, O3 nie stosuje tego w produkcji.

## Forward repair 0017 i transakcje usuwania

`0017_e8_purge_commit` po 0016 naprawia COMMIT minimalnego operatora z żywym posiłkiem. Zmienia tylko atrybut SECURITY DEFINER istniejącego `app.diary_aggregate_count()`. Checker pozostaje deferred i wyłącznie sprawdza 1..100 źródłowych elementów; body, qualified tables, owner calorie_app_migrator bez SUPER, closed search_path i ACL nie są zmieniane. Migracja weryfikuje ich frozen stan i odmawia po tamper. Nie dodaje SELECT/EXECUTE/DML operatorowi, API lub workerom. Readiness/worker wymaga teraz head 0017. Opublikowane 0001–0016 są niezmienne.

Downgrade metadata jawnie zawsze zachowuje tę wstecznie zgodną poprawkę, emitując warning. Nie usuwa danych, jobs/fences ani nie cofa checkera do znanego 42501. Re-upgrade jest idempotentny po weryfikacji niezmienionego body/path/owner/ACL. Pozostałe data-protection guards starszych migracji nadal obowiązują. E8.3 rezerwuje teraz 0018 po tej naprawie.

Normalny operator CLI wykonuje świeże oddzielne transakcje begin commit → provider → confirm commit → purge commit, z INITIALLY DEFERRED. Ręczne wymuszenie diary IMMEDIATE nadal odmawia 23514 podczas przejściowego usuwania items przed meals i cofa całość; retry powinien korzystać ze świeżej domyślnej transakcji. Naprawa nie przestawia trybów caller ani nie wymusza sprawdzenia innych pending constraints. Nie dodawaj GRANT SELECT operatorowi w celu obejścia błędu.

## Proces i monitoring

Odrębny DATABASE_URL LOGIN E8. Uruchom `python -m calorie_app.motivation_worker --batch 100 --date-batch 256` jako oddzielną usługę. Startup natychmiast nadrabia pierwszą ograniczoną porcję; dalszy cykl co60s. --once wykonuje jeden bounded cykl, --status zwraca zagregowany backlog bez identyfikatorów kont. SIGINT/SIGTERM kończy bieżącą transakcję i zamyka engine. CLI odmawia niewłaściwej roli/schematu i nie drukuje credentiali ani źródeł.

Obserwuj pending_backfill, pending_materialization, oldest_matures_at, owners_handled, dates_processed, exitcode i motivation_worker_unavailable. Duży backlog wymaga kolejnych cykli, nie nowego klienta. Wiele instancji serializuje konto→counter i rewaliduje źródła/czas po lock; brak zewnętrznej kolejki/lease. Batch1..1000, date-batch1..1000, maksymalnie4×date-batch kandydatów keyset przed merge źródeł, brak limitu całkowitej historii lub pozycji rankingu. SQL pełnohistoryczne streak/agregacje mogą korzystać z work_mem/spill; dobierz monitoring czasu i dysku, nie obcinaj historii. Korekta osi celu atomowo przechodzi całą sparse historię w porcjach w jednej transakcji.

## Backup, restore i purge

Źródła są autorytetem, pochodne są odtwarzalne. Backup obejmuje spójne app/Keycloak i istniejącą politykę E4/E7. Po restore: zatrzymany ruch/workery, nowy sync_epoch, E4 reconciliation i osobna konserwatywna bramka AI pozostają obowiązkowe. Stare projekcje są widoczne jako pending_backfill, niewidoczne w rankingu do poprawnej odbudowy. Worker wykrywa epoch mismatch, unieważnia marker/projekcje, restartuje bounded checkpoint i odtwarza tylko zachowane źródła. Utraconych posiłków nie wymyślamy. Własna motywacja wraca niezależnie od publikacji.

Przywrócone ranking=true oraz stary marker nie otwierają rankingu po rebuild. Potrzebna nowa świadoma afirmacja bieżącej epoki. Nie resetuj false/revoked/źródłowych zgód lub historii. Downgrade pustego E8 zachowuje E0–E7; dowolne dane E8/marker/cursor domyślnie odmawiają przed DDL. Opróżnianie pochodnych to osobna kontrolowana operacja odtworzenia, nie normalny rollback obrazu.

Purge wrapper E8 usuwa własne projekcje/odznaki/marker/sesje i unieważnia cursory z purged anchor; deleguje cały E7→E6→E5/E4. Cleanup intents, anonimowa pula AI, catalogue i subject fences zachowują istniejącą semantykę. Deleting odcina ranking jeszcze przed purge. Nie nazywaj tego dokumentu odbiorem produkcyjnego restore lub RPO/RTO.
