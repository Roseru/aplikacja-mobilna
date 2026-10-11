# Integracja odczytów i statystyk E5 - osoba 2

Normatywne wykonanie: [OpenAPI](../../backend/openapi.json), [schemat](../../contracts/schemas/domain.schema.json), [wektory statistics_v1](../../contracts/test-vectors/statistics-v1.json), [reguły](DECYZJE_V1.md). Android nie jest zmieniany w PR R. Punkt odniesienia pozostaje0.7.1/Room6; rzeczywiste dowody nowego APK/KO-31 dostarcza O1.

## Cztery odczyty

GET /api/v1/me/meals, /weights, /diary-days wymagają from i to (ISO lokalne daty włącznie,<=366dni), optional limit1–500/default100 i page_token. W odpowiedzi items mają entity_id/revision/payload; dni również effective_complete obok deklaracji. Metadata: account_id/account_generation/sync_epoch/as_of/time_zone/profile_revision/goal_timeline_revision/server_position/from/to. Następna strona zachowuje te same filtry i limit oraz metadata. Pusty zakres jest items[]; brak profilu nie blokuje listy. Po410 zacznij nową listę; token nie jest sync checkpointem.

GET /api/v1/me/statistics?days=7|30|90 (domyślnie30) zwraca dokładnieN dat, statistics_v1/goal_band_v1, daily, averages z osobnym day_count i liczniki celu/wagi. Przykład [statistics.json](../../contracts/examples/valid/statistics.json) pokazuje no_data/null i denominator0. Nie wyświetlaj częściowej known_sum jako pełnego spożycia ani preliminary_in_goal jako końcowego trafienia. Dni niekompletne i dzisiaj nie wchodzą do średnich; makro null nie blokuje kompletnego energetycznie dnia.

## Różnice z bieżącym Androidem

LocalDayClock używa strefy urządzenia; serwer today w strefie żywego profilu i swoim as_of. Ekran rozróżnia lokalny/pending wynik od potwierdzonego stanu serwera. Zmiana strefy nie przesuwa local_date dawnego wpisu. Wektory mają odmienną device_time_zone, północ/DST i dokładne granice.

Lokalne validFrom/localSequence/id nie rozwiązują correction_of. O1 ma uruchomić wspólne wektory przesunięć i rozgałęzień serwerowej osi przed twierdzeniem o zgodności. Serwer wybiera historyczną datę wspólnym resolverem; dzisiejszy cel/meal.goal_id nie są zamiennikiem.

Stare REAL/Double nie dowodzą dokładnego Decimal w wire. O1 wykonuje BigDecimal, kanoniczne stringi, exact sum i HALF_UP12 tylko dla średnich oraz podpisaną zmianę masy. Remis wagi rozstrzyga UTC occurred_at i UUID. Testy Python rzeczywiście wykonują15 wektorów; wykonania Kotlin/Room nie deklarujemy.

## Dostęp i pamięć lokalna

No-store dotyczy wszystkich prywatnych wyników/błędów. HTTP cache nie zastępuje kontroli aktualnego konta/lease, generation i epoch. Po zmianie konta odrzuć stare zadanie i stan ekranu; po deletion odetnij dalszy odczyt. Read API służy widokowi stanu serwera; synchronizacja nadal jest podstawą trwałego shadow/outbox. [Obsługa sync](ODCZYTY_I_SYNCHRONIZACJA.md) zachowuje oryginały i świadomy import/recovery.

O1 dostarcza odrębne dowody nowego handlera OIDC/HTTP, WorkManager, Room, uruchomienia wektorów, kont A/B/gościa i KO-31. Własny referencyjny klient O2 oraz realKeycloak backendu nie poświadczają APK.
