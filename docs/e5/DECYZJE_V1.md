# Decyzje odczytów E5 v1 - osoba 2

Zakres E5-O2-R: odczyty i `statistics_v1`. [Master prompt](../MASTER_PROMPT_E5.md) z odebranego main b27838b oraz jawne zlecenie koordynatora uruchomiły wykonanie. R nie zamyka katalogu C, integracji APK O1, HTTPS O3 ani E6.

## Odczyt, autoryzacja i stan

JWT jest weryfikowany przed SQL; konto pochodzi z dokładnego issuer/sub. Role moderator/admin nie dają cudzych danych. Każda strona ponawia sprawdzenie blokady podmiotu, active i generacji oraz epoki. `Cache-Control: no-store` obejmuje wynik, walidację, OIDC i błędy middleware. Nowe odczyty nie zapisują encji ani receipt/ChangeLog. `server_position` (H) i `as_of` opisują stan serwera, nigdy ACK lub checkpoint telefonu.

Pierwsza strona materializuje spójny snapshot w REPEATABLE READ. Zamraża UTC as_of, H, strefę/revision profilu, revision osi celu i dane. Zmiany po utworzeniu nie zmieniają następnych stron. Brak profilu jest dopuszczony dla jawnego zakresu dat: strefa/revision są null. Statystyki wymagają żywego profilu (409 profile_required), bez wymyślonej strefy.

Strony sortują posiłki/wagi po occurred_at,entity_id, dni po local_date,entity_id. Filtry from/to są lokalnymi datami włącznie; zakres do366dni, limit1–500/default100. Niewiadome i powtórzone parametry są odrzucane. Token `read1` jest podpisany przez HMAC z kluczem pochodnym o oddzielnej domenie od katalogu/sync; zawiera wyłącznie identyfikatory i kontekst, bez payloadu.

## Limity i trwałość

Limit4 aktywnych sesji/konto,100000 rekordów/64MiB kopii/sesję,60min od pierwszej kopii, do1MiB całej koperty UTF-8/500rekordów/stronę. Pojedynczy rekord ma dodatkowy limit512KiB. Następne strony nie wydłużają TTL; wygasła/sprzątnięta kopia daje410 read_session_expired. Błędny token/parametry422, zmiana kontekstu409, zasoby503 read_resources_exhausted; SQL/lock timeout503 service_unavailable. Nie zwracamy fragmentu jako kompletnej kopii.

Sesje i rekordy są w PostgreSQL, więc restart/repliki zachowują dane przy tym samym sekrecie. Techniczna bramka przyjęcia pod tym samym właścicielem zapobiega przekroczeniu limitu przy równoczesnych REPEATABLE READ. Konflikt serializacji jest ponawiany ograniczoną liczbą prób. Przebieg ma blokadę konta przed bramką/licznikiem. [Migracja i retencja](KONFIGURACJA_O3.md) opisują minimalne ACL, purge i downgrade.

## Statystyki

Jedna transakcja REPEATABLE READ i jeden as_of w IANA strefie profilu wyznaczają dokładnie7/30/90dat. Historia zachowuje zapisane local_date; dzisiejszy dzień jest preliminary, nie wchodzi do średnich ani końcowego in_goal. `effective_complete` używa wspólnej reguły diary: deklaracja, żywy posiłek, znana energia każdej pozycji i dodatnia dokładna suma. Tombstone usuwa obserwację, nie deklarację innych dni.

Pole bez znanej wartości ma known_sum=null. Znane zero jest "0"; częściowa suma ma complete=false. Każde makro ma własny denominator day_count z zamkniętych energetycznie kompletnych dni z pełnym polem. Denominator0 daje średnią null. Nie ma deficytu, punktów lub interpolacji z braków.

Cel pochodzi z jednego wspólnego batch resolvera profiles. Graf korekt właściciela czytamy raz, także z przodkami poza oknem. Najnowsza accepted timeline_revision wybiera głowę każdej pierwotnej decyzji, potem jej poprawioną datę; przesunięcie daty nie wskrzesza starej wersji. Dodatni historyczny cel, zamknięty kompletny dzień i dokładna energia włącznie[0.9*cel,1.1*cel] kwalifikują do goal_band_v1.

Dzienny punkt wagi to ostatni rzeczywisty pomiar po occurred_at,entity_id. Change_kg jest podpisaną różnicą ostatniego i pierwszego dziennego punktu; mniej niż2 różne dni daje null. Liczniki obejmują wszystkie obserwacje. Nie dodajemy procentowej zmiany masy.

Wspólne nutrition_v1 i snapshot spożycia zachowują g/ml, gęstość wyłącznie przy konwersji i exact Decimal. Nowy katalog nie przelicza historii. Tylko średnie zaokrąglamy HALF_UP do12miejsc, kanonicznie. Sumy mogą mieć więcej miejsc; nie walidujemy wyników jako6-miejscowego wejścia. SQL timeout15s, lock timeout5s, statystyki do100000wierszy wejścia łącznie i10000wersji celu; przekroczenie jawnie422 statistics_resource_limit, bez częściowego wyniku.

Jednostronicowa pierwsza odpowiedź bez next_page_token nie zachowuje niepotrzebnej kopii: API wywołuje wyłącznie wąskie discard z kontrolą właściciela/generacji/epoki w tej samej transakcji. Admission tuple pozostaje. Puste/single odświeżenia nie zajmują slotów ani nie tworzą rosnącego backlogu; stronicowane kopie nadal istnieją do TTL dla retry końcowej strony. Granice pracy kompletności dni: do 10000 posiłków, 100000 pozycji i 8 MiB UTF-8 na partię do 32 lokalnych dat.
