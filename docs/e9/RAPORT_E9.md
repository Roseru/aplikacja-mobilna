# E9-O2 — raport wykonania

Status: **W TOKU**, bez finalnego PASS kodu lub CI.
Start: `a522471140150271d853d66aa06f11d868699e49`.
Gałąź: `codex/backend-e9-korekta-zapotrzebowania`.
Master: [MASTER_PROMPT_E9](../MASTER_PROMPT_E9.md).
Przekazania: [O1](INTEGRACJA_O1.md), [O3](KONFIGURACJA_O3.md).
Pełne E9/R i E10 pozostają otwarte. Katalog jest demo; live gate zamknięty.

## Reprezentacja i granice

Oszacowania mają własną właścicielską oś energy_versions i monotoniczną
energy_axes.revision. Mifflin pozostaje prawdziwym artefaktem GoalPayload.estimate;
źródłowy JSON nie jest nadpisywany. Adapter/backfill identyfikuje source goal/revision,
zachowuje graf korekt i daty oraz odrzuca nieprawidłowy Mifflin. Cel bez estimate
nie tworzy ani nie zeruje E. Tożsamość oszacowania wyznacza pełny canonical estimate JSON, z input i estimated_at.
Zmiana samego celu ze skopiowanym artefaktem nie tworzy E; nowe oszacowanie jest
wersjonowane również przy tej samej liczbie i nie resetuje baseline.
Forward0023 kwalifikuje istniejące duplikaty z0022 bez przepisywania immutable historii.

Korekta/revert obowiązuje od następnego lokalnego dnia zegara DB. Zajęta data
wymaga jawnego conflict/revert-ID; późniejsze plany pozostają. Revert nie przyjmuje
nigdy dowolnej liczby lub przyszłego, jeszcze nieobowiązującego celu E.
Supersedes i audit wskazują poprzedni E/baseline, reguły, analizę i decider.
Goal kcal/B/T/W, goal_type, activity_class i stare wersje pozostają niezmienne.

Funkcje E9 używają account→counter→shared epoch→AI controls/pool→job/analysis
oraz uporządkowanych wszystkich challenge locks przed kwalifikacją zastosowania.
Expiry i fingerprint są ponownie sprawdzane po czekaniu na blokady.
Model wyłącznie wyjaśnia dokładny wynik. Decimal/Fraction i NUMERIC rational
nie zaokrąglają średniej po każdym dniu; HALF_UP12 raz, granice do14 miejsc,
zaokrąglenie wychodzące poza clamp przesuwane do środka.

Energy jobs należą do jednej ai_jobs/puli/attempts/permits E7. Relacja typed FK
nie udaje zdjęcia. Jeden active/konto; admission336h i osobny apply cooldown336h.
Unknown/crash po dispatch nie powtarza sieci. Automat ma bounded producenta,
fair skip jednej oceny konta/dzień, online baseline/consent/notice i default off.

Notice ręczne i automatu są jawne, wersjonowane, z providerem, kwalifikacją,
allowlisted zakresem oraz snapshot hash/rewizjami. PhotoConsent nie zastępuje ich.
PUT zgód, epoch/generation, reject i drift kontekstu odcinają stare upoważnienia.
Ręczne accept/revert przesuwa baseline; automat nie. Wystarczająca historia
bez stabilności/pełnej kompletności daje opis, a minimum niedostępne nie wysyła modelu.

Nowa encja E wymaga energy_estimates_v1. Wspólny ChangeLog przechowuje NULL marker,
a energy_changes dołącza typed payload do tej samej pozycji — nie jest drugą kolejką.
Legacy binarny kod snapshotu z a522 pomija marker i przesuwa checkpoint.
Scope podpisanych cursor/snapshot/page wymaga pełnego snapshotu przy upgrade,
bez zmiany outbox/body/hash/receipts. Stare obrazy mają swój head/readiness;
zgodność starego wire nie jest bezwarunkowym rollbackiem obrazu.

E8 używa wspólnego historycznego resolvera w kwalifikowanej projekcji deficytu.
Energia nie zmienia regularity_v1/punktów/celu. Deadline i frozen final results
nadal należą do E8; nowy E nie rekwalifikuje spóźnionego źródła.
Purge/retencja i stale restore są w dotychczasowym scoped mechanizmie E7/E4/E8.

## Dotychczasowe dowody i RED

Dotychczasowe przebiegi robocze (nakładających się zakresów nie sumujemy):
54 pure/provider unit PASS;185 dotychczasowych E7/token unit PASS.
PG:18 podstawowych API/source/ACL,19 worker+sync,10 actual-process+sync,
24 migration/independent SQL i4 manual/auto/on-time/late E8 PASS.
Te wyniki dotyczą swoich roboczych drzew; po uzupełnieniu notice/globalnej kwalifikacji
wymagany jest aktualny pełny zestaw, freeze i niezależny odbiór.

- Pierwsza migracja na PG17.11 zakończyła backend procesu0xC0000005 podczas tworzenia
  SQL resolvera zwracającego anonymous CTE row. Log zachowany prywatnie; jawny
  PL/pgSQL record RETURN przechodzi0021→0022. Nie deklarujemy udowodnionej
  pierwotnej przyczyny błędu PostgreSQL.
- Pierwszy pytest tmp trafił na WinError5 współdzielonego katalogu. Własny basetemp
  zamknął problem bez zmiany oracles/ACL.
- Rzeczywisty503 admission: niejednoznaczne id zmiennej PL/pgSQL. Zmienione nazwy;
  podstawowy18PG GREEN.
- Late countTokens source drift poprawnie nie stosował E, ale zostawiał running.
  Dodano natychmiastowy terminal analysis_context_changed;18PG GREEN.
- Pierwszy fullunit1712 miał1710PASS/2FAIL: nieaktualny OpenAPI i enum implemented
  paths. Artefakty/lista odświeżone; stary fullrun nie jest PASS.
- E8 harness TRUNCATE CASCADE usunął dwa physical permits; zero attempts/queued
  ai_outbound_busy wykazało błędne przygotowanie. Przywrócono pierwotne dwa slots,
  bez zmiany quota. Później oracle uwzględnił naturalny wzrost closed_days1→7
  po deadline, zachowując points/complete/in_goal i identyczne projections.
  Cztery rzeczywiste scenariusze E9–E8 GREEN.

Własne testy wykorzystują Python3.13.9 i trzy izolowane PG17.11, SCRAM oraz rzeczywiste
API/worker LOGINS. Dane syntetyczne; mock działa w tym samym procesowym transport/
limiter/parser co E7. Usługi użytkownika nie były zatrzymywane ani modyfikowane.
Sekrety/rawlogs/buildy/private review pozostają poza Git. Cleanup własnych usług
i finalne SHA/CI/recenzja zostaną dopisane po rzeczywistym odbiorze.


## Aktualny odbiór kwalifikacji 0023

PR [54](https://github.com/Roseru/aplikacja-mobilna/pull/54) pozostaje draft.
Head poprzedniego odbioru e9331a9/base6952c14: zdalne contracts/quality/Android
build/device/PKCE GREEN, PostgreSQL/local-integration RED. Finalnego PASS brak.
Niezależny recenzent:145PASS bez skip, trzy dodatkowe krytyczne RED:
kopiowany estimate nadpisuje E9; pusty wire12 clamp; limit jednego auto konta
przerywa shared runner. Potwierdzono także PUBLIC EXECUTE wewnętrznego helpera
oraz nieaktualny whitelist provisionera. Poprawki SQL dodaje liniowa0023,
bez edycji wypchniętej0022. Head/health i provisioning wskazują0023.

Bieżące lokalne dowody:1714unit PASS;94 rules+infrastructure PASS;
27PG migration/rules/clone PASS (osobny poprzedni błąd setup nowego photo oracle);
realny oversized100001 source fixture i działający photo job PASS15.80s.
Installed wheel Python-I: migracja/head/drift/manifest/rules PASS;
rzeczywisty CLI--once obsłużył photo+energy,4 dispatched attempts, minimalny SCRAM
LOGIN bez raw DML/API/migrator membership i bez SET ROLE. Mock, bez Google IO.
Oczekujemy fullPG i ponownego odbioru tego samego PR na aktualnym freeze.

Praktyki odbioru: krótki aktualny stan powyżej; stare RED zachowane osobno;
reprodukcja→jedna korekta→regresja; krytyczne oracles najpierw wykryły błąd
w poprzednim freeze. Powtarzalne przygotowanie używa istniejącego PostgreSQL CI,
infra bootstrapu i installed smoke. Przepływ O1 klient→PKCE→API→E9→sync pozostaje
następnym odbiorem O1 po przyjęciu backendu; testy backendu nie udają gotowego UI.


### Aktualna korekta grafu i parent contract

Po pierwszym recheck003 wykryto regresję explicit history_correction (daty źródła)
oraz rehash obcego driftu manifestu. Nowa0024 zachowuje korekty grafu dat,
deduplikuje wyłącznie zwykłe user_decision clone i sprawdza actual prosrc wszystkich
10 normatywnych funkcji względem literalnego pristine003 manifestu. Żadna z10
nie jest zmieniana przez004, więc żaden digest nie jest odświeżany. Upgrade z
uszkodzonym guarda źródła odmawia transakcyjnie nawet po wcześniejszym rehash003.
33PG aktualnego krytycznego zakresu PASS,88.46s, obejmuje oracles daty/clone/fresh
estimate, wszystkie migracje, literalny drift, ACL, wire i oversize+photo.
Head/health i provisioner wskazują0024; live gate po migracji nadal zamknięty.
Pełny przebieg003 przerwano jako nieaktualny bez PASS. Przed końcowym fullPG
uzupełniamy istniejące wymagania PG_BIN i TEST_WORKER_PASSWORD; stary fullrun
1216PASS/28failure/111setup error nie zamyka odbioru. Automatyczny reviewer odmówił
własnej dodatkowej zmiany globalnego członkostwa LOGIN; nie wykonano jej i nie
zaliczamy niezależnego rzeczywistego SCRAM proof. Autorski installed-I proof był
rzeczywisty; read-only niezależne ACL i pozostałe własne próby są osobnym dowodem.
