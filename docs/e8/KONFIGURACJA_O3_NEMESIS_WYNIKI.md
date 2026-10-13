# E8.4: finalizer i odbiór O3 - osoba 2

Wdrożenie backendu 0021 pozostaje domyślnie zamknięte. Operator odrębnie
weryfikuje gotowość instalowanego pakietu, migracji, prywatnych ACL oraz
rzeczywistych funkcji initializer/projector/finalizer i aktywuje bieżącą epokę
przez właścicielskie `app.e8n_activate(epoch)`. API i worker nie mają tej
kompetencji. Aktywacja nie zastępuje odbioru Androida ani rollout O3.

## Oddzielny LOGIN i uprawnienia

`infra/local/provision_nemesis_finalizer.py` korzysta z istniejącego protokołu
ochrony logów provisionera deletion. Połączenie administracyjne pochodzi ze
standardowych PG* / service / pgpass; `NEMESIS_FINALIZER_LOGIN` oraz
`NEMESIS_FINALIZER_PASSWORD` są przekazywane środowiskiem. Hasła ani DSN nie
należą do argv, repozytorium i raportów. SCRAM verifier powstaje lokalnie.
Provisioner wymaga PostgreSQL 17 i prywatnej bazy `calorie_app` albo `*_test`.
Ponowne wykonanie dopuszcza wyłącznie własny, wcześniej oznaczony LOGIN.

LOGIN dziedziczy tylko bazową `calorie_app_nemesis_finalizer`, bez SET ROLE,
ADMIN, SUPER, DDL, source SELECT i surowego DML. Dopuszczone entrypoints to
`app.e8n_finalize(uuid)` i `app.e8n_finalize_batch(integer)`; własny worker
lifecycle nie dziedziczy tej roli. Odczyt `app.alembic_version` służy wyłącznie
readiness. Provisioner sprawdza
efektywne ACL, wszystkie memberships oraz dostęp do innych prywatnych baz.

## Wywołanie i minutowy schedule

Po ustawieniu `DATABASE_URL` na właściwy minimalny LOGIN należy wywoływać
`python -I -m calorie_app.modules.nemesis.finalization --batch 100` z
zainstalowanego wheel albo obrazu. Scheduler O3 uruchamia jeden bounded batch
co minutę. Nie należy dodawać automatyzacji Codex ani zmieniać istniejących
harmonogramów PAUSED. Równoległe wywołania są bezpieczne; wynik i obie strony
utrwalają się w jednej transakcji, a crash przed COMMIT pozostawia rekord due.

CLI sprawdza PG17 oraz exact Alembic head i wykonuje COMMIT. SQLSTATE 40001
lub 40P01 otrzymuje najwyżej trzy próby, każda w nowej transakcji. Nieznane
błędy nie są zamieniane na sukces. Kod 0 oznacza gotowy przebieg; 2 oznacza
zamkniętą capability; 1 oznacza niepowodzenie z neutralną diagnostyką bez
prywatnych wierszy. JSON podaje `ready`, `processed`, `finalized`, `backlog`.

Backlog obejmuje faktycznie due i możliwe do finalizacji accepted rekordy,
łącznie z overdue active. Uszkodzone legacy seed wymagają owner-only audytu:
nie są fałszywie odbudowywane z bieżącej historii i nie blokują kolejnych due.
Zwykły restart nadrabia zaległości bez zmiany epoki lub terminów.

## Purge i restore

Należy zachować istniejący begin/resume/purge deletion CLI i scoped chain E4–E8.
Begin atomowo odcina sharing; purge usuwa prywatne projekcje i finalne wyniki
obojga uczestników wyzwania. Nie wywołuje się prywatnych helperów ręcznie ani
nie konstruuje `_deletion_context` poza istniejącym entrypointem.

Restore wymaga istniejącego fencing, zmiany installation epoch i wyłączonej
capability. Stare wyzwania nie są czytelne ani aktualizowalne natychmiast po
zmianie epoki, zanim bounded cleanup wykona cancellation. Reconsent nie
przywraca starego wyniku. Restore nie jest zwykłym restartem.

O3 samodzielnie wykonuje i raportuje minimalny SCRAM LOGIN, minutowy worker,
monitoring, purge, rzeczywiste backup/restore oraz RPO/RTO. Backend PASS i
lokalny test nie stanowią potwierdzenia produkcyjnego wdrożenia O3.
