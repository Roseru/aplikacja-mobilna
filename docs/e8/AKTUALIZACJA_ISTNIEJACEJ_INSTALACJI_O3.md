# Aktualizacja istniejącego E7 do E8 — odbiór O3

13 października 2026, Agent 3. Własna próba używa rzeczywistego starego backendu
`b4d2780` / head0015 i aktualnego backendu `89be120` / head0021. Nowy, oznakowany
PostgreSQL17 z przypiętego obrazu Docker Hub, oddzielne role i prywatne dane.
Cudze środowisko użytkownika oraz wcześniejsze checkouty pozostały nietknięte.
Syntetyczny podpisany JWT/JWKS i produkcyjne factories/TestClient nie są odbiorem
publicznego Keycloak/TLS lub APK; te zakresy mają osobne dowody.

## Ważny warunek przed migracją

`init-db.sh` tworzy role przy pierwszej inicjalizacji PostgreSQL. Zmiana tego
pliku nie tworzy ich w istniejącym wolumenie E7. Przed upgrade operator DB
musi zapewnić trzy wymagane bazowe role E8. Migrator aplikacji nie powinien
otrzymać CREATE ROLE i nie należy zamieniać kont API/retencji w nowe workery.

Najpierw sprawdź istniejące nazwy, atrybuty i powiązania:

```sql
SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
       rolcreaterole, rolreplication, rolbypassrls
FROM pg_roles WHERE rolname IN (
  'calorie_app_motivation_worker', 'calorie_app_nemesis_worker',
  'calorie_app_nemesis_finalizer');
```

Twórz wyłącznie brakujące role zaufanym administratorem DB, z minimalnymi
atrybutami. Przykład dla instalacji, w której nie ma żadnej z tych trzech:

```sql
BEGIN;
CREATE ROLE calorie_app_motivation_worker NOLOGIN NOINHERIT NOSUPERUSER
  NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE calorie_app_nemesis_worker NOLOGIN NOINHERIT NOSUPERUSER
  NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE calorie_app_nemesis_finalizer NOLOGIN NOINHERIT NOSUPERUSER
  NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
COMMIT;
```

Nie nadpisuj ani nie normalizuj istniejących ról w ciemno. Migracje i hardened
provisionery sprawdzają też effective ACL, memberships i inne prywatne bazy;
niezgodność należy zbadać, zamiast obchodzić guard. Dopiero potem jeden migrator
uruchamia upgrade przy zatrzymanym ruchu/workers. Po readiness trzy osobne
LOGINy i worker start nie otwierają automatycznie capability Nemesis.

## Wykonane pięć zakresów

1. Stary production factory E7 przyjął legalny profilUTC, historyczny cel2000,
   posiłek1900 i deklarację kompletności; ranking=true pochodzi z dawnej zgody.
   Zapisano rzeczywiste stare replay responses/checkpoint i pełny odczyt konta.
2. Próba upgrade bez bazowych ról E8 została atomowo odrzucona: nadal0015,
   brak motivation_accounts i częściowo zastosowanego schematu E8.
3. Po wyłącznie owner-only minimalnym bootstrap rzeczywisty upgrade0015→0021
   zakończył się poprawnie. Hardened producent utworzył odrębny SCRAM LOGIN
   motywacji; installedCLI wykonał bounded cycle i naliczył2 należne historyczne
   punkty bez nowego zapisu klienta.
4. Nowy production factory zachował byte-równe odczyty konta/zgody/epokę,
   cztery stare replay responses i działający checkpoint. Ranking po faktycznym
   naliczeniu punktów nadal pusty: stara true nie zastępuje świeżej affirmation.
5. Baza ma dokładny head0021, a capability Nemesis pozostaje disabled.

Pięć zakresów PASS, finalny prywatny runner exit0; nie są to pięć kolejnych
unikalnych pełnych regresji. Własny oznakowany PG usunięto w finally po ownership
check. Credentials, raw logs i stare payloady pozostają poza Git.

Wcześniejsze błędy harnessu zachowano: niepełny PUT zgody poprawnie dostał422;
porównywano początkowe accepted zamiast starego replay already_applied;
końcowy Unicode komunikat konsoli miał błąd kodowania po zaliczonych assertions.
Poprawiono tylko prywatny harness, bez zmiany produktu lub oczekiwanego kontraktu.
Finalny przebieg porównuje replay starej i nowej rzeczywistej factory, nie mirror
implementacji receipt. Zestawy/powtórki nie są sumowane do1265PG.

## Stan dostawy

PR44(workery), PR45(kopia/próba restore) i PR46(registry) są scalone.
Osobny main `89be1204b83933b2cdbea1cf29f6ae74118f0862` /
[CI38349960125](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38349960125)
ma8 completed/success z odczytanymi pełnymi logami:1658unit/44infra/1265PG609,65s,
28Keycloak/126JVM/130device, installed wheel/Docker-I, HTTPS/PKCE, workers/cadence
i rzeczywista paired capture/offline restore. Historyczne main408/10d/ECR failures
pozostają historią; nie przypisano im PASS.

Pełne zespołowe E8 wciąż wymaga rzeczywistych O1/API/APK i produkcyjnych O3
registry deletion/sesji/reopen/RPO-RTO. Niniejszy lokalny upgrade nie rotuje
epoki, nie afirmuje zgód i nie zastępuje procedury restore.
