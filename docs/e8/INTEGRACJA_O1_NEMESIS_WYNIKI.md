# Integracja O1: wyniki Nemesis E8.4 - osoba 2

Podstawa kontraktu: master E8.4 z source `76546405d2c549278a9826c0223204e98698015c`. Addytywne DTO są w [schemas.py](../../backend/src/calorie_app/modules/nemesis/schemas.py); obowiązujące OpenAPI jest generowane z aplikacji. Niniejszy dokument opisuje kontrakt do odbioru O1, a nie wynik APK/UI/cache ani otwarcie wdrożenia. Publiczne issuance/create/accept/statistics pozostają domyślnie zamknięte do rzeczywistych preconditions i osobnej aktywacji operatora.

## Żądanie i świadome warunki

`GET /api/v1/nemesis/{challenge_id}/statistics` wymaga aktualnego access tokena i kanonicznego `X-Sync-Epoch` UUID. Nie przyjmuje body, parametrów punktów, procentów, partner UUID ani zakresu nadpisującego zgody. List/read metadata, pairing przez share-code oraz accept/cancel zachowują kontrakt E8.3. Użytkownik akceptuje dokładne `rule_version=regularity_v1`, okres 7/30/90 dni, strefę IANA i scope. Regularity jest obowiązkowe; weight_change i mean_deficit są osobnymi opcjami zgody obu uczestników. Scope ani ranking opt-in nie zastępują aktualnego sharing konkretnej rywalizacji.

Metadata ma status invited/active/finished/cancelled i własną revision do quoted `If-Match` mutacji. Statistics ma odrębny status pending/provisional/final i dodatnią 64-bitową read revision. Nie należy używać read revision statystyk jako If-Match lifecycle. Początek jest następną rzeczywistą granicą lokalnej daty po accept, okres obejmuje `[start_date,end_date)`, a deadline przypada 720 godzin po utrwalonym end_at UTC. Instants oraz maturity pozostają w accepted zone także po legalnej późniejszej zmianie profilu.

## Rozłączne odpowiedzi

Każda odpowiedź statistics zawiera id własnej rywalizacji, revision, rule_version, as_of UTC, time_zone, start_date, end_date i deadline. Żadna nie zawiera UUID partnera ani surowych kg/kcal/E, celów, posiłków lub graph rewizji źródeł.

| status | Obecne pola wynikowe | Znaczenie dla UI |
|---|---|---|
| pending | Brak self, opponent, outcome i finalized_at | Jeszcze nie dojrzała pierwsza data. Pokazuj oczekiwanie, bez pozornego 0:0 lub remisu. |
| provisional | self, opponent, outcome | Spójny wynik dojrzałych kwalifikowanych projekcji. Może zmienić się po poprawnej korekcie do deadline. |
| final | self, opponent, outcome, finalized_at UTC | Atomowo utrwalony wynik po deadline. Dostęp nadal wymaga aktualnej zgody i privacy fences. |

Przykłady: [pending](../../contracts/examples/nemesis-statistics-pending.json), [provisional](../../contracts/examples/nemesis-statistics-provisional.json), [final](../../contracts/examples/nemesis-statistics-final.json), [hidden](../../contracts/examples/nemesis-statistics-hidden.json). Schemat odrzuca pola z innego stanu i nieznane pola. Provisional dokładnie na deadline jest legalny; finalizer działa dopiero po deadline. Brak lub uszkodzony seed daje HTTP503, nigdy pending ani fikcyjne zera.

Self/opponent mają regularity `{points,closed_days,complete_days,days_in_goal}`, weight_change oraz mean_deficit. Counts oznaczają dojrzałe daty okresu. Zachodzi `points=complete_days+days_in_goal`, `days_in_goal<=complete_days<=closed_days`, a oba closed_days są jednakowe. Outcome to self_wins/opponent_wins/tie względem użytkownika wykonującego request i wynika wyłącznie z punktów.

## Opcjonalne metryki i braki

| Metryka / stan | Dokładny kształt |
|---|---|
| Każda hidden | `{"state":"hidden"}`. Bez value, counts, dat i data_available. |
| Weight insufficient_data | `{"state":"insufficient_data","value":null,"observed_days":0}` albo observed_days=1. |
| Weight available | `{"state":"available","value":"-10","observed_days":3,"first_date":"2026-10-14","last_date":"2026-10-18"}`. |
| Deficit insufficient_data | `{"state":"insufficient_data","value":null,"eligible_days":0}`. |
| Deficit available | `{"state":"available","value":"-15","eligible_days":2}`. |

Weight wymaga co najmniej dwóch różnych dojrzałych dat. Dzienny reprezentant to ostatni pomiar według occurred_at UTC, potem UUID, klasyfikowany do accepted zone w `[start_at,end_at)`. Procent to `(last-first)/first*100`; pierwsza i ostatnia dostępna data są jawne. Wiele pomiarów jednego dnia nie zwiększa observed_days.

Deficyt to średnia dziennych procentów `100*(E-intake)/E` tylko z dojrzałych efektywnie kompletnych dni z dodatnim historycznym `GoalVersion.payload.estimate.maintenance_kcal`. Nie używa celu spożycia ani bieżącego profilu. Przykład: 2000 przy E2500 daje 20%, a 3000 przy E2000 daje -50%; średnia to -15%, eligible_days=2. Większy deficyt nie daje punktów ani przewagi w remisie.

Value obu metryk jest kanonicznym **stringiem** ze znakiem, do 12 miejsc po przecinku, bez sześciocyfrowego limitu części całkowitej. BigDecimal musi zachować znak i skalę; float nie jest poprawnym wire. Przykłady poprawne: "-50", "-15", "0", "-0.000000000001". NaN, Infinity, wykładniki, "+1", "01", "1.0", "-0" i "0.0" są niepoprawne. Zaokrąglany jest dopiero końcowy agregat, HALF_UP. `"0"` jest dostępną wartością, `null` z counts oznacza brak danych, hidden oznacza brak udostępniania. Pusty/niekompletny dzień nie oznacza zerowego spożycia.

## Rewalidacja, odświeżanie i izolacja sesji

Sukcesy i błędy mają `Cache-Control: no-store`. Przy każdym odczycie backend sprawdza JWT, uczestnictwo, oba active generations, installation/control epoch, status i aktualne sharing. Invited, cancelled, deleting i stara epoka odmawiają neutralnym404 również po finalizacji. Moderator/admin bez uczestnictwa także nie ma dostępu. Brak gotowości funkcji jest ujawniany dopiero po kontroli dostępu; poprawny uczestnik może dostać503 service_unavailable i Retry-After5. Standardowy envelope błędu nie jest statistics ze status unavailable.

Read revision zmienia się także przy maturity bez nowego zapisu klienta. O1 odświeża zwykłym GET przy otwarciu/powrocie na ekran oraz według przyjętej polityki poll, porównuje revision i pokazuje as_of. Read revision ma własną przestrzeń Nemesis i nie jest sync H/checkpoint. Nie używać If-None-Match ani304 do pomijania aktualnej kontroli zgody; nie ma kontraktu ETag. Na404, zmianę konta, wylogowanie, zmianę generacji/epoki lub cancel usuń widok partnera i odrzuć opóźnione odpowiedzi poprzedniej sesji. Receipt, cursor, nowa rywalizacja i późniejszy ranking opt-in nie przywracają starej zgody.

Wyniki partnera nie trafiają do starego sync-v1, Room jako pozorny lokalny partner ani lifecycle receipt. Pobranych danych na cudzym urządzeniu nie można zdalnie cofnąć, ale klient ma usuwać własny widok po utracie aktualnego uprawnienia i respektować no-store.

## Osobny odbiór O1

O1 wykonuje na zgodnych APK/API własne przypadki pending bez 0:0, pusty dojrzały dzień z prawidłowym zerem punktów, hidden bez liczności, null vs "0", ujemny procent, 7/30/90 i DST, deadline/provisional/final, cancel/deletion/restore po final oraz opóźnioną odpowiedź A podczas przełączenia na B. Sam backend/unit/OpenAPI PASS nie zamyka APK/UI/cache/sesji. O3 osobno odbiera rollout i aktywację; E8.5 należy do koordynatora.