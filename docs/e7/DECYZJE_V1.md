# Decyzje kontraktu i runtime E7 v1 - osoba 2

11 października 2026. Baza: `485fb2e959f4d4b74548e6ac6ffe4e129cd5e68f`.
Zakres wykonania: E7-O2; E7-R oczekuje datowanych wejść O3 i zatwierdzonego corpus.

## Przyjęcie i wynik

Jeden multipart, dwie części metadata/image, body 6 MiB wyłącznie w pamięci.
Zgoda this_photo, notice i provider poprzedzają codec oraz storage, także przy odwrotnej kolejności części.
JWT/konto/epoka poprzedzają receipt; SHA-256 oryginału i semantyczne metadata tworzą hash operacji.
Dedykowana blokada sesyjna operation key serializuje replay i przygotowanie, bez account lock/transakcji podczas IO.
Przyjęty profil jest niezmienny. Confirm zawiera kompletny stary Meal i opcjonalne ProductDraft templates oraz rewizję;
walidacja i publiczne exact refs poprzedzają zapis jednej decyzji. Dziennik powstaje dopiero przez dotychczasowy sync.

## Pliki i zadania

Nowa migracja 0015, bez zmian 0001–0014. Oddzielne analizy, zadania, zgody, receipts, decyzje i admissions;
anonimowe rezerwacje pool i cleanup intents przetrwają purge. Staging wyłącznie sanitized JPEG w prywatnym root.
Aktywna operacja ma blokadę sesyjną storage key; orphan sweep próbuje tę samą blokadę przed unlink.
Fsync i atomic rename poprzedzają acceptance. Terminalne stany tworzą trwały intent przed unlink.
Startup/minutowy sweep usuwa zaległości; po 24 h worker odmawia odczytu nawet przy niedziałającym cleanup.

Durable compensation intent powstaje przed staging. Acceptance usuwa go atomowo;
po niepewnym COMMIT ACK zachowujemy plik, a cleaner sprawdza bieżący registry
po uzyskaniu storage lock, także dla wcześniej pobranego intentu. Unlink ma trwały
intent, ACK dopiero po fizycznym usunięciu; rollback poprzedza session unlock.

AI używa osobnej NOLOGIN/NOINHERIT bazowej roli `calorie_app_ai_worker`, bez praw
legacy workera do dziennika/katalogu. Minimalny LOGIN dziedziczy tylko tę rolę,
bez SET/ADMIN membership. Job SELECT nie zawiera fence, a ledger zawiera tylko
SHA-256 capability transportu. Upgrade odmawia nadmiarowych wcześniejszych ACL.

Kolejność: konto → catalog, gdy potrzebny → AI control/pool → job → ledger/receipt.
Publiczne queued/running/succeeded/failed; lease/fence, generation i epoch chronią finish.
Durable dispatch_started przed IO. Crash po markerze daje provider_result_unknown bez resend.
Permit outbound jest trwały i nie wygasa z lease. Transport działa w osobnym procesie z hard timeout;
zwolnienie wymaga potwierdzonego zakończenia procesu. Osierocony permit jest fail-closed do jawnego odcięcia przez O3.
Cancel przed dispatch blokuje send; późniejszy cancel blokuje wynik i kolejne próby, bez obietnicy cofnięcia wysłania.

Child ma własny watchdog wspólnego absolute deadline, także po zabiciu parenta.
Preflight finish jest jednorazowy po zakończonym countTokens; nie cofa fazy generate.
Finish/retry odmawia, gdy nadal istnieje niezakończone IO dla zadania.

## Limity i restore

Jedna pool dla food_photo i energy_adjustment. Stabilny provider/project/model/environment, bez hasha klucza.
Okno RPM/TPM ruchome 60 s; RPD Pacific/DST; admission zdjęć UTC i interfejs energii 14×24 h.
Pełny budżet rezerwowany przed każdym call; niepewne/missing usage nie zwalnia zużycia.
Live zamknięte bez datowanego free-only/model/limits config. Mock ma jawne osobne testowe wartości.
Kontrola jest związana z sync_epoch; zmiana epoki zamyka dispatch. Odblokowanie wymaga current epoch i dowodu operatora,
z zachowaniem rezerwacji i odcięciem dawnych procesów. Brak automatycznego resetu puli po restore/purge/rotation.

Restore v1 pozostaje zamknięty przez minimum 336 h i wymaga exact nowej epoki
oraz datowanego fizycznego fencing. Rutynowy configure-pool nie zmienia środowiska
tego samego projektu nawet po wyłączeniu starej puli. Rozbieżność limitów O3/DB
zamyka live. Quiet bounded retention pełnych receipts≥1440 h i ledger≥336 h działa
także bez dostępnego storage, bez resetu minimalnych dowodów.

## Dowody i granice

Realne PG/SCRAM, HTTP/storage, wieloprocesowe bariery i fake HTTP provider; niezależny nieautor ≥9/10.
E7-R nie jest zaliczane mockiem. O1 Room/outbox/APK i O3 mount/ACL/cleanup/restore są osobnymi odbiorami.
PR do main bez merge; osiem obowiązkowych kontroli CI zachowane. Automatyzacje PAUSED, bez E8/E9.
