# Odczyt profilu Androida 0.8.2 — O1/O2/O3

Po udanym bootstrapie ekran **Profil → Konto i logowanie → Profil na serwerze** udostępnia jawny `GET /api/v1/me`. Pokazuje pseudonim, opcjonalny wzrost, klasę aktywności, strefę czasu i zgody z serwera. `profile:null` oznacza brak profilu serwerowego, a nie usunięcie lub utworzenie lokalnego profilu. Przycisk jest niedostępny dla gościa, przed bootstrapem oraz przy `requiresRecovery`.

Odczyt nie zmienia profilu Room, lokalnego celu kcal, historycznych celów, posiłków ani outbox; nie importuje gościa i nie potwierdza synchronizacji. Klasy mapują się `stationary` → Etat biurowo-kawowy, `line` → Linia, `commando` → Komandos. Odczyt klasy nie uruchamia `activity_goal_v1` ani kalkulatora zapotrzebowania. Podgląd pozostaje wyłącznie w pamięci bieżącej sesji; restart wymaga nowego odczytu.

## Kontrakt i transport

`ProfileReadProtocol` odpowiada [ProfileRead E0](../contracts/schemas/domain.schema.json) oraz [przykładowi O2](../contracts/examples/valid/profile-read.json). Ścisłe UTF-8/JSON odrzuca duplikaty, dodatkowe/brakujące pola i niepoprawne typy. UUID pozostają kanoniczne, rewizje całkowite mieszczą się w Int, Decimal wzrostu pozostaje tekstem do 6 miejsc z kontrolą >0 i ≤300. Wymagane są dozwolona klasa, znana strefa IANA, Unicode bez NUL/samotnych surrogate oraz rzeczywisty czas UTC z maksymalnie 6 miejscami. Nie używamy `Double` do interpretacji wire Decimal. Wersja lokalnego tzdb może różnić się od serwerowej; nierozpoznana strefa odrzuca cały podgląd.

GET ma wyłącznie przechwycony bearer i nagłówki Accept/Accept-Encoding/Cache-Control. Nie wysyła body, Idempotency-Key, If-Match ani X-Sync-Epoch. Wspólny transport z bootstrapem zachowuje HTTPS/systemową weryfikację CA/hosta, brak redirect/cache, 15 s connect/read i 30 s termin odbioru kontrolowany między odczytami oraz limit 64 KiB. Baza API nadal wymaga dokładnej ścieżki `/api/v1`; domyślne adresy pozostają puste. [Konfiguracja bootstrapu](BOOTSTRAP_HTTP.md) i [overlay validation O3](../infra/integration/ANDROID_PKCE.md) obowiązują również tutaj.

## Izolacja i błędy

Żądanie przechwytuje dokładną sesję, lease i rewizję mapowania bootstrapu. Przed wysyłką i przy zastosowaniu odpowiedzi ponownie sprawdza te trzy konteksty. Sieć czeka poza mutexem/transakcją Room. Nowe logowanie, logout/A→B→A, zmiana sesji podczas refresh lub zmiana mapowania uniemożliwiają zastosowanie starego podglądu. Podwójny klik nie wysyła dwóch GET. Bootstrap i odczyt nie działają równocześnie. Logout pozostaje dostępny podczas sieci; pakiet już wysłany może dotrzeć wyłącznie z wcześniej przechwyconym tokenem.

HTTP200 musi pasować do account_id z bootstrapu. Inne account_id odrzuca całą odpowiedź bez zmiany mapowania. Inna sync_epoch ustawia trwałe `requiresRecovery` i zwiększa contextRevision; dotychczasowe UUID/generacja/epoka oraz prywatne dane zostają zachowane. Następny bootstrap nie kasuje flagi. GET me nie zawiera account_generation, więc nie stanowi dowodu jej zgodności ani zamiennika bootstrapu/E4.

Bliski expiry odnawia sesję przed GET. `401 unauthorized` pozwala na jedno udane odnowienie tej samej osoby i jedno ponowienie; niepowodzenie nie wysyła starego tokenu. `403` nie odnawia sesji ani automatycznie nie tworzy konta. Inny błąd/nieprawidłowy JSON/sieć usuwa niepotwierdzony podgląd, zachowując dziennik. `429/503`, także HTML proxy, respektuje Retry-After bez pobierania body. Termin jest wspólny dla bootstrapu i odczytu, szyfrowany w sesji, zachowany po refresh/restart; logout usuwa rekord sesji. Nie ma automatycznej pętli żądań. Anulowanie zwalnia stan pobierania; kolejne jawne ponowienie jest możliwe.

Początek nowego odczytu, bootstrapu, logowania oraz refresh usuwa poprzedni podgląd. Zakończony poprawnie podgląd jest oznaczony w UI jako ostatni odczyt, nie jako zawsze aktualny stan. Tokeny/payloady nie trafiają do logów; wire obiekty mają redagowane `toString()`.

## Odbiór i następny krok

Testy kontraktu używają skopiowanego, niezmienionego przykładu O2. Testy JVM transportu mają zastępcze HttpsURLConnection; testy urządzenia używają jawnie syntetycznych sesji/odpowiedzi oraz rzeczywistego Room/Keystore. Nie są odbiorem TLS, podpisu JWT, Keycloak ani prawdziwego API. [Raport 0.8.2](RAPORT_0_8_2.md) wskazuje wykonane próby.

Gałąź `codex/android-odczyt-profilu` zależy od `42763f8` / [PR #26](https://github.com/Roseru/aplikacja-mobilna/pull/26). Osobny PR kierujemy na `codex/android-sesja`, aby pokazać wyłącznie nowy etap. Najpierw odbiór i scalenie PR26, potem zmiana bazy nowego PR na aktualny main i ponowny odbiór integracji. Nie scalać nowego PR do oczekującej gałęzi sesji.

Rzeczywisty odbiór wymaga adresów istniejącego środowiska O3, prywatnego stanu testowego pozostającego lokalnie i validation-only publicznego CA. Na komputerze O1 nie odnaleziono Docker/uv ani lokalnego stanu integration; nie inicjalizowano fikcyjnego środowiska i nie zmieniano issuer. O3-011 potwierdza rzeczywisty login APK 0.8.0, nie bootstrap/GET tego etapu. Dalszy zakres: realny bootstrap+GET A/B, lost ACK/restart/logout, następnie odczyty celów i adapter trwałego E4/Room/WorkManager. Pełne E3/E5/KO-31 pozostają otwarte.

Aktualizacja 11.10.2026/O1: PR26 scalony normalnym merge na main c59e6d68d18bbafd157a9d1383aae8d36fa1b893 po osmiu success dla42763f8 i zerze reviews/comments. Zgodnie z docs/WORKFLOW.md odbior rzeczywistego bootstrapu/GET pozostaje kolejnym etapem integracyjnym; merge nie zamyka E3/KO-31. PR31 skierowano na main, nastepnie dolaczono main zwyklym merge; zrodla android/app pozostaly identyczne z przetestowanym0522824. Wczesniejsze uwagi o bazie zależnej/nieuruchamianiu CI sa historyczne; nowy push uruchamia wymagane CI PR do main.
