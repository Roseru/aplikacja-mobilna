# Lokalne bazy E1 - osoba 2

`compose.yaml` uruchamia PostgreSQL 17 z portem wyłącznie na localhost. `init-db.sh` zakłada oddzielne bazy `calorie_app`, `keycloak` i jednorazową bazę `calorie_test`, a także role migratora, API, workera i Keycloak. API/worker mają DML bez praw DDL; rola API nie ma dostępu do bazy tożsamości. Prawa domyślne ustawia właściciel schematu, więc obejmują przyszłe migracje uruchamiane tą samą rolą.

Skopiuj `.env.example` do `.env` i ustal hasła. Następnie z katalogu repozytorium:

```text
docker compose --env-file infra/local/.env -f infra/local/compose.yaml up -d --wait
```

Instrukcję migracji i uruchomienia API zawiera [backend/README.md](../../backend/README.md). Pliki są lokalnym punktem startowym dla O3, nie konfiguracją publicznego serwera. Serwer Keycloak i realmy są zadaniem integracji OIDC E3. Inicjalizacja działa dla pustego wolumenu; zmiana haseł istniejącego środowiska wymaga ich świadomej zmiany w PostgreSQL, nie usuwania danych.

W E1 lokalnie wykonano SQL tego samego skryptu na PostgreSQL 17.11 z oficjalnego [pakietu EDB wskazanego przez PostgreSQL](https://www.postgresql.org/download/windows/). Docker nie był dostępny na komputerze. Budowę obrazu i testy na Linuksie wykonuje workflow PR; wynik jest odnotowany w raporcie E1.
