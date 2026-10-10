# Integracja E3 dla Androida - osoba 2

Punkt odniesienia: scalony PR #9, Android 0.7.1 / Room 6 na main
`0ff4b4c`. Backend realizuje kontrakt `/api/v1`; prywatne zapisy klienta
pozostają zakresem synchronizacji E4. Wykorzystujemy `AccountBootstrapStore`
i `BootstrapProtocol` dostarczone przez O1, opisane w
[przekazaniu mobilnym](../../android/INTEGRACJA_E3.md).

## Sesja i kolejność wywołań

1. Uwierzytelnij użytkownika przez systemową przeglądarkę, Authorization Code
   z PKCE S256. Publiczny klient `calorie-android` nie ma sekretu w APK.
2. Powiąż dokładne `(issuer, sub)` z lokalnym właścicielem. Przechwyć jego
   lease i token; zmiana sesji nie może podstawić tokenu innej osoby.
3. Utrwal Idempotency-Key UUID przez `AccountBootstrapStore.begin()`, następnie
   wywołaj `POST /me/bootstrap` z bearer access tokenem, bez body i If-Match.
4. Zastosuj wynik przez istniejący `BootstrapProtocol`/`apply()` w transakcji
   sprawdzającej lease i klucz. Wynik ma dokładnie account_id, sync_epoch,
   account_generation i server_time. Identyczny replay zwraca pierwotny czas.
5. Po bootstrapie dostępne są GET me, GET me/goals, GET products i szczegół
   produktu, kalkulator oraz online PUT zgód.

Przed bootstrapem każda chroniona operacja oprócz bootstrapu daje
403 `account_bootstrap_required`. Bootstrap nie tworzy profilu, celu,
posiłku ani importu gościa. GET me może zwrócić `profile:null` i
`goal_timeline_revision:0`; lista celów może być pusta.

| Wartość | Reguła klienta |
|---|---|
| local owner UUID i lease generation | Zachować istniejące identyfikatory i lokalną kontrolę zadań |
| account_id | Mapowanie otrzymane z poprawnego bootstrapu, bez przepisywania historii |
| account_generation | Serwerowa generacja; oddzielna od lokalnego lease |
| sync_epoch | Trwała epoka instalacji backendu; restart jej nie zmienia |
| goal_timeline_revision | Serwerowa rewizja osi; nie jest lokalną sekwencją celu |

Odtwarzanie repozytorium/ViewModel i czyszczenie pamięci ekranów przy zmianie
sesji pozostają pracą O1. Trwałe `requiresRecovery` po zmianie epoki/generacji
nie jest kasowane przez ponowny bootstrap; uzgodnienie danych należy do E4.

## Błędy i bezpieczne ponowienia

Wspólny błąd ma `code`, `message`, `details:[{field,reason}]` i request_id.
Używaj code do logiki; request_id służy diagnostyce bez tokenu i payloadu.

| Wynik | Działanie |
|---|---|
| 401 unauthorized, WWW-Authenticate: Bearer | Odnowić sesję; lokalny dziennik nadal działa |
| 403 forbidden | Brak roli user z klienta calorie-api |
| 403 account_bootstrap_required | Wykonać bootstrap aktualnej tożsamości |
| 403 account_deleting | Zablokować operacje serwerowe tego konta, także replay |
| 409 sync_epoch_changed | Stary klucz bootstrapu; details zawiera field=sync_epoch i bieżący UUID w reason; renew i nowy bootstrap |
| 409 account_generation_changed | Stary klucz/generacja; details bootstrapu zawiera bieżącą generację; renew, bez resetu danych |
| 409 idempotency_key_reused | Ten sam klucz użyty z inną treścią lub If-Match; nie zmieniać wysłanej operacji |
| 409 version_conflict | Nowa mutacja zgód ma nieaktualną revision; ponownie odczytać GET me |
| 409 idempotency_result_expired | Wynik zgód starszy niż retencja pełnej odpowiedzi; minimalne potwierdzenie zachowano, mutacji nie odtworzono |
| 410 page_expired | Rozpocząć nową listę; token strony nie jest checkpointem sync |
| 422 invalid_request | Poprawić format danych/nagłówków/parametrów |
| 503 identity_provider_unavailable lub service_unavailable | Retry-After; bez utraty lokalnej kolejki |

PUT `/me/consents` jest osobnym zasobem online. Wysyłaj oba wymagane booleany
`ranking` i `automatic_energy_adjustment`, UUID Idempotency-Key oraz cytowaną
revision, np. `If-Match: "1"`. Odpowiedź zawiera revision, updated_at i oba
booleany; ETag odpowiada revision. Identyczne ponowienie sprawdza receipt
przed bieżącą revision i zwraca pierwotny wynik. Zgody nie należą do outbox.

## Odczyty i obliczenia

Listy produktów i celów: limit 1..500, domyślnie 100, stabilny porządek UUID,
nieprzezroczysty page_token i TTL 60 minut od pierwszej strony. Parametry
muszą pozostać identyczne. Token wiąże konto/generację/epokę oraz snapshot;
kolejne strony nie przedłużają TTL. Produkty wskazują wyłącznie opublikowany
official. Brak official daje pustą listę; demo pozostaje w katalogu lokalnym.
Szczegół produktu z revision wskazuje dokładną opublikowaną wersję; bez
revision zwraca najnowszą dozwoloną wersję.

Kalkulator POST `/energy-estimates` zwraca `mifflin_pal_v1`, wejście,
resting_kcal, pal, maintenance_kcal i estimated_at. Nie ustawia celu ani
deficytu. Decimal wejściowy jest kanonicznym stringiem do 6 miejsc, wynik
ComputedDecimal do 12 miejsc. Brak wartości pozostaje null, a znane zero "0".

Nie ma PATCH me ani POST me/goals, HTTP zapisu posiłków, wagi lub szkiców.
Istniejące UUID, snapshoty i payloady outbox zachowujemy dla adaptera E4.

## Parametry OIDC i granice dowodu

O1 dostarczył dokładne callbacki `pl.roseru.kalorie:/oauth2redirect` oraz
`pl.roseru.kalorie.validation:/oauth2redirect`. Są w allowliście testowego
realmu. Osobny harness backendu używa dokładnego callbacku loopback;
opis środowiska i komendy są w [instrukcji Keycloak](../../infra/local/keycloak/README.md).

Rzeczywisty test backendu z tokenami Keycloak nie jest testem handlera APK.
APK 0.7.1 nadal wymaga klienta sesji/HTTP. Produkcyjny issuer/HTTPS i
osiągalność środowiska mobilnego dostarcza O3; nie są zastępowane adresem
testowego harnessu.

Kontrakt: [generowane OpenAPI](../../backend/openapi.json),
[raport E3](RAPORT_E3.md), [konfiguracja O3](KONFIGURACJA_O3.md).
