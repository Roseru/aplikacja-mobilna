# E9-O2 — konfiguracja i odbiór O3

Stan i dowody: [raport](RAPORT_E9.md). E9 używa tego samego procesu
`calorie_app.worker`, roli `calorie_app_ai_worker`, puli/attempts/physical permits
i prywatnego storage E7. Nie powstaje druga usługa, Redis ani broker.
Nie wdrożono do istniejącej instalacji użytkownika i nie aktywowano live.

## Upgrade i role

Liniowy ciąg0022→0023→`0024_e9_history_graph` jest addytywny wobec0021; stare migracje/SQL niezmienne.
Uogólnia FK joba (photo albo energy), zachowuje istniejące zdjęcia/jobs i dodaje
prywatne wersje E, snapshoty/notice/receipts oraz payload przy wspólnej pozycji
ChangeLog. Bootstrap źródeł Mifflina nie daje baseline/notice ani zgody.
Nie zmienia source JSON, epoki, kont, celu lub klasy.

```sh
uv run --project backend --locked alembic -c backend/alembic.ini upgrade head
uv run --project backend --locked python -m calorie_app.worker --help
```

Migrator uruchamia upgrade raz. API/worker nie mają DDL. Istniejący provisioner
AI zachowuje minimalny LOGIN, bez API/migratora/superusera, SET ROLE i raw diary.
Worker ma tylko typed claim/dispatch/finish/discovery; e7_reserve pozostaje prywatne.
Prowizja lifecycle/finalizera wskazuje nowy head. Upgrade zamyka Nemesis activation;
przed świadomym ponownym otwarciem O3 sprawdza nowy manifest/pairing. Nie otwieraj
go samym env/JWT ani w tej dostawie.

Old sync-v1 wire i jego payloady pozostają zgodne: E używa wewnętrznego markera,
ignorowanego przez historyczny kod snapshotu. Starszy obraz ma jednak stary
EXPECTED_REVISION/readiness; nie deklarujemy bezwarunkowego rollbacku obrazu na
0022. Wycofanie operatorowe wymaga sprawdzonego zgodnego obrazu. Test downgrade
jest wyłącznie dla własnej pustej efemerycznej bazy i odmawia przy danych E9.

## Wspólny runner i producent

Minimalne ustawienia nadal obejmują DATABASE_URL workera, AI_PROVIDER=mock,
AI_PROJECT_ID/AI_MODEL/AI_ENVIRONMENT_ID zgodne z ai_pools i prywatny AI_PHOTO_ROOT.
Storage jest potrzebne dla wspólnego cleanup zdjęć, nie dla agregatów E9.
W normalnym minutowym cyklu istniejącego AI CLI najpierw działa bounded producent,
potem claim/dispatch i cleanup. Dla energii brak fake image/hash/storage_key.

Producent wybiera najwyżej100 kwalifikujących się kont/cykl. Account→counter
serializuje dwóch producentów/ręczne POST. Każde konto bez danych jest oceniane
najwyżej raz na lokalny dzień, z last_auto_state/datem audytu; nie blokuje dalszych
kont w kolejnych cyklach. Przyjęty job ma admission336h i queue deadline5min.
Nie ma catch-up dla pominiętych historycznych okien. Automat default off; wymaga
aktualnej online zgody, kwalifikacji, notice/providera i świadomego baseline.

Globalne RPM/TPM/RPD/Pacific/concurrency i konserwatywne unknown nadal należą do E7.
45s/próbę,120s całość, najwyżej2 generate; każdy dozwolony retry rezerwuje ponownie.
Retry klienta odczytuje receipt i nie rezerwuje. Sieć jest poza transakcją;
dispatch marker i permit commitują przed I/O. Proces zabity po dispatch nie
wysyła drugi raz po restart/lease recovery.

## Restore, purge, zdrowie

Nowy epoch zamyka wspólny dispatch i unieważnia pending notice/job/akceptację
oraz baseline aktywnego automatu. Nie przywracaj markerów ze starej epoki przez
sync, restart lub off→on. Operator fizycznie odcina dawne workery i zachowuje
niepewne okna/rezerwacje; istniejące reconcile wymagania336h pozostają.
Nie resetuj puli przez rotację klucza, nowe prompt_version lub purge.

Purge E9 jest częścią istniejącego scoped begin/purge/COMMIT; usuwa prywatne
wersje/analizy/notice/receipts/attached payloady właściwego właściciela.
Anonimowe attempts/zużycie i fizyczne permits mają wcześniejsze zasady retencji.
Receipt po60d traci pełny wynik, lecz zachowuje hash/kontekst/minimalny marker;
powtórzenie daje idempotency_result_expired, bez odtworzenia joba.

Readiness nadal wymaga PG17/head0022/sekretu tokenów. Diagnostyka/CLI wyświetla
kontrolowane kody i liczniki, bez diary/notice payloads lub sekretów w logach.
O3 odbiera rollout, właściwe LOGINS/health/minutowy cykl i restore w swoim zakresie.

## Bramki zewnętrzne

AI_PROVIDER=gemini nadal wymaga dotychczasowego datowanego potwierdzenia O3,
dokładnej konfiguracji Free Tier/model/project/limitów i development-only gate.
Żadnego billing lub płatnego fallbacku. Projekt/model/environment scope jest
wspólny ze zdjęciem; prompt/schema energii nie tworzą nowej puli.
Nie wykonano Google I/O. Prywatne agregaty użytkowników nie są corpus live.
E7-R/E9-R, realny APK/Room/O1 i produkcyjne RPO/RTO pozostają odrębnymi odbiorami.
