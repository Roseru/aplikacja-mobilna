# Odczyty i obsługa synchronizacji - osoba 2

Dokument uzupełnia [kontrakt E4](../e4/INTEGRACJA_O1.md) i [trwały klient referencyjny](../../tools/sync_client/README.md). E5 dodaje widok stanu serwera; zapis nadal przechodzi wyłącznie przez sync.

1. Po OIDC/PKCE bootstrap potwierdza dokładną tożsamość i kontekst. Przypisanie zbioru gościa do wybranego konta wymaga oddzielnej trwałej świadomej decyzji; bootstrap/lista go nie wykonuje.
2. Normalnie pull → push → pull. Strony pull i checkpoint zapisuj atomowo w staging/shadow; niewysłane operacje i oryginały pozostają osobno. Po ostatniej stronie pełny snapshot można aktywować. H/read1 nie zastępują checkpointu.
3. Wire operation_id/treść/hash/epoka po materializacji są niezmienne. Edycja późniejsza ma nowe ID/base_revision po potwierdzeniu poprzedniej. Tylko kompletneHTTP200 sync z wynikiem każdej operacji pozwala naACK. Utrata odpowiedzi po servercommit pozostawia kolejkę; retry tej samej treści rozpoznaje receipt/already_applied, także po zatwierdzonym prefixie.
4. 401 odnawia sesję,503 respektuje Retry-After; podstawowy dziennik offline nadal działa. Na konflikt przechowuj obie wersje, pokazuj różnice i zapisuj świadome rozwiązanie nową operacją. Nie nadpisuj starego payloadu pod istniejącym ID.
5. Wspierane30×24h dotyczy ważności checkpointu, nie długości historii. Starszy checkpoint wymaga pełnego uzgodnienia, bez usunięcia outbox i bez automatycznego create każdego nieobecnego UUID. Brak rekordu nie dowodzi usunięcia/przyjęcia operacji.
6. Po restore nowa epoka blokuje zwykły push. Zachowaj także wcześniej potwierdzone wpisy/ACK; requiresRecovery nie znika przez bootstrap. Pełny snapshot i receipts/mapowania bieżącego kontekstu, potem świadome nowe recovery recreate_missing lub resolve_existing. Oryginały i stare wire pozostają. Równa revision nie dowodzi równej treści, a brak receipt nie dowodzi niewykonania.
7. Recovery ma nowy operation_id i autorytatywny mapping target. Nowe zależne referencje można świadomie przepiąć; wysłanych nie przepisuj. Dwa urządzenia stosują ten sam mapping. Świadome zakończenie recovery ponownie sprawdza pełny kontekst i wszystkie decyzje w jednej transakcji.
8. Read API pokazuje wyłącznie żywe dane. Tombstones i potwierdzenia pochodzą z sync. Po410 read_session_expired zacznij nową listę; nie cofaj/zmieniaj outbox. as_of/statystyki opisują tylko znane serwerowi spożycia, nie poświadczają wysłania całej kolejki telefonu.

Przykład: local pendingmeal nie jest jeszcze w GET meals/statistics. Ekran może pokazać lokalny wynik z oznaczeniem oczekiwania; nie oznacza dnia zsynchronizowanego po samym odczycieH. Deletion, zmianaA→B→A, generation i epoch odcinają stare zadania/odpowiedzi również po powrocie do tej samej tożsamości.

Katalog C wymaga pełnych rzeczywistych danych ARPOL/bazowych; [audyt źródeł](../e0/ZRODLA_KATALOGU.md) i materiały są wynikiem R, nie wydaniem official. APK/Room/WorkManager/KO-31 O1 oraz HTTPS/restore/RPO/RTO O3 mają oddzielne dowody.

Rotacja `CATALOG_PAGE_TOKEN_SECRET` także odrzuca stare checkpointy/snapshoty/strony sync: 422 invalid_sync_token nie oznacza wyłącznie wygasłej strony. W obecnym kliencie nie włącza automatycznie pełnego pull. Po uzgodnionej spójnej zmianie klucza potrzebny jest jawny nowy pełny snapshot bez starych tokenów, zachowanie outbox/originals/receipts i nowy checkpoint dopiero na końcu. [Dokładna procedura O3](KONFIGURACJA_O3.md#kontrolowana-rotacja-wspólnego-klucza) rozróżnia tę sytuację od zmiany epoki/generacji oraz lost ACK; sama rotacja nie tworzy recovery operacji i nie potwierdza zapisu.
