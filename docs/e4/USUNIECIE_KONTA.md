# Usunięcie konta E4 - osoba 2

Inicjacja jest komendą operatora, z UUID operacji, UUID konta oraz oczekiwaną
generacją. Nie dodano endpointu DELETE /me. Tożsamość `(issuer, sub)` pochodzi
z trwałego konta w DB; operator nie podaje subject ani dowolnego endpointu.

```text
python -m calorie_app.modules.identity.deletion begin --account-id <UUID> --operation-id <UUID> --expected-generation <N>
python -m calorie_app.modules.identity.deletion status --operation-id <UUID>
python -m calorie_app.modules.identity.deletion resume --operation-id <UUID>
```

`begin` zatwierdza wyłącznie rozpoczęcie zamknięcia. `resume` wykonuje następne
etapy; tę samą operację można ponawiać po utracie odpowiedzi albo restarcie.
Konfiguracja `DELETION_DATABASE_URL` wskazuje osobny login operatora z
uprawnieniami roli `calorie_app_deletion_operator`. `KEYCLOAK_ADMIN_CONFIG`
wskazuje chroniony lokalny plik JSON z listą dokładnych mapowań:

```json
[{"issuer":"https://identity.example/realms/calorie",
  "admin_base_url":"https://identity.example","realm":"calorie",
  "client_id":"calorie-deletion-operator","client_secret":"<sekret ze środowiska>"}]
```

Plik, hasło DB i sekret klienta pozostają poza repo, APK i logami. HTTPS jest
wymagany; `allow_local_http:true` dopuszcza wyłącznie syntetyczny loopback
127.0.0.1. Provider adapter nie podąża za przekierowaniami ani proxy środowiska.

Krótka transakcja blokuje konto, licznik i zadanie, ustawia `deleting`, zwiększa
generację dokładnie raz i zapisuje blokadę subject. Bootstrap i chronione
odczyty sprawdzają blokadę również po usunięciu konta; replay nie otwiera dostępu.
Po jej commit adapter otrzymuje service token przez client_credentials,
sprawdza autoryzowany dostęp do kolekcji użytkowników w tym samym realmie,
odczytuje dokładny target, usuwa go i sprawdza jego brak. Sam DELETE/404,
nieautoryzowany 404, redirect, timeout lub odmowa nie potwierdzają odcięcia.

Potwierdzenie dostawcy ma osobny trwały commit. Awaria między DELETE a nim
pozostawia prywatny graf i receipts; retry sprawdza autoryzowany brak tego
samego targetu. Dopiero potwierdzone zadanie pozwala na purge. Purge jest
jedną transakcją; awaria po faktycznym SQL przywraca cały graf i nie oznacza
zadania jako ukończonego. Dane B i wspólny katalog nie są jego targetem.

Migracja 0011 dodaje `account_deletion_jobs`, `deleted_subjects` i prywatny
`_deletion_context`, bez FK zadania/blokady do usuwanego konta. Operator ma
SELECT zadania i EXECUTE begin/confirm/purge; nie ma DML tabel prywatnych,
DDL, TRUNCATE ani członkostwa migratora. API/worker nie mają tych komend.
SECURITY DEFINER ma stały `search_path=pg_catalog,pg_temp`; purge zapisuje
niepodrabialny przez runtime kontekst własnej transakcji i dokładnego owner.
Kontrolowane wyjątki triggerów dopuszczają wyłącznie jego DELETE. Sam
migratorowy surowy DELETE nie omija niezmienności celów. Nie użyto GUC,
wyłączenia triggerów/FK ani session_replication_role. Downgrade zachowuje
dane i ochronę; ponowny upgrade jest idempotentny.

Trwały `block_until` wynosi co najmniej czas potwierdzenia + 420 s:
lifetime 300 s + przyszły iat 60 s + skew exp 60 s. Test podpisanego JWT
ze sterowalnym zegarem potwierdza ważność w T+360 i T+419.999 oraz odmowę
w T+420. Sama blokada subject jest bezterminowa, więc restart lub późniejszy
czas DB nie skraca tej granicy. Nowa rejestracja wymaga nowego subject i UUID
konta. Zachowujemy tylko minimalny dowód zamknięcia, bez payloadów prywatnego
grafu. Restore aplikacji/Keycloak wymaga zewnętrznego reconcile zamkniętych
tożsamości przed otwarciem ruchu; zwykły TTL JWT nie jest dowodem tego reconcile.

Harness generuje odrębnego confidential klienta i syntetycznego `delete_a`.
Jego jedyną legacy rolą administracyjną jest `realm-management/manage-users`,
zweryfikowaną rzeczywistym tokenem, odczytem, DELETE i potwierdzeniem.
Nie ma master-admin ani realm-admin; drugi service account bez tej roli
rzeczywiście dostaje odmowę i nie uruchamia purge. Ta legacy rola pozwala
także na tworzenie/edycję użytkowników w swoim realmie; Keycloak nie ma
osobnej legacy roli tylko dla DELETE. Produkcyjne ograniczenie targetów przez
fine-grained admin permissions i zarządzanie credentialami odbiera O3.

Testy rzeczywistego Keycloak zaliczają PKCE A/B, usunięcie wyłącznie `delete_a`,
ponowienie po zewnętrznym DELETE, odmowę refresh/login, blokadę starych JWT
i bootstrapu oraz niezmienność B i bajtów katalogu. Brak providera nie daje skip.
Backendowy harness nie stanowi odbioru samousunięcia UI ani logowania APK.
