# Wysyłanie trwałej kolejki dziennika — etap w toku

Agent 1 / O1, 19 października 2026. Gałąź `codex/android-wysylanie-kolejki`.
Zależność: dokładny commit `b3bde558d866ccad7a21f0664ffbd092e84bd506`
z [PR122](https://github.com/Roseru/aplikacja-mobilna/pull/122).
Ten etap korzysta z [trwałych partii i atomowego ACK](SYNCHRONIZACJA_PUSH.md).
Normatywne reguły: [integracja E4](../docs/e4/INTEGRACJA_O1.md)
i [decyzje protokołu](../docs/e4/DECYZJE_V1.md).

## Dostarczona część: transport

`HttpsMealPushGateway` wysyła wyłącznie `POST /api/v1/sync/push` pod skonfigurowany
adres HTTPS. Przyjmuje wcześniej zamrożony `PushBatch`; nie tworzy operacji,
checkpointu ani nowego identyfikatora. Wysyła dokładne bajty UTF-8 tego batcha,
ze znaną długością i `Content-Type: application/json; charset=utf-8`.

Idempotencję określają identyfikatory poszczególnych operacji w JSON.
Transport nie dodaje nagłówka `Idempotency-Key` dla całej koperty, `If-Match`,
`X-Sync-Epoch` ani niezaimplementowanej deklaracji `X-Sync-Capability`.
Epoka pozostaje częścią zamrożonego żądania. Konto i bearer pochodzą z biletu
sesji przekazanego przez kontroler.

Przed pierwszą fizyczną wysyłką wywoływana jest kontrola `beforeSend`.
Jej odmowa albo anulowanie zamyka połączenie bez pobrania strumienia wyjścia.
Wyjątek zapisu nie uruchamia automatycznego retry. Kolejna jawna próba może
użyć odtworzonego batcha z identycznymi bajtami.

Wspólny transport zachowuje weryfikację TLS i hosta systemu. Nie podąża
za przekierowaniami, nie używa cache, żąda JSON oraz nieskompresowanej
odpowiedzi. Sukces i prywatny błąd wymagają `Cache-Control: no-store`.
Limity obejmują również brak `Content-Length`: do 4 MiB sukcesu i 64 KiB
błędu. 429/503 zwracają status i `Retry-After`, bez odczytu HTML proxy.

Transport nie uznaje samodzielnie odpowiedzi za potwierdzenie. Istniejący
`PushProtocol` przyjmuje pełny ACK wyłącznie z HTTP200, po sprawdzeniu całej
odpowiedzi i związaniu jej z konkretną kopertą. Dodano parser normatywnego
`SyncError`, którego `details` jest obiektem; błędów E3 nie wolno używać
zamiennie. Nie pokazujemy użytkownikowi swobodnego tekstu serwera.

## Odbiór bieżącej części

Kod `d646c154e59ca1fff6669648580e59798ada6b6c`: pełne zadania
`testDebugUnitTest`, `testValidationUnitTest` oraz `lintDebug` PASS.
**322 JVM debug / 337 validation**, 0 błędów i pominięć; lint: 0 błędów.
Po 9 nowych testów transportu w każdym wariancie. Przebieg Gradle 6 min 55 s,
cały proces 416,921 s. 254 wejścia źródłowe mają identyczne hashe przed i po
przebiegu. Log SHA-256:
`5a6ed1a3db4a90e1b06b0f308cb566ae23a891dc9d53525d66889f31271ba1aa`.

Pierwszy przebieg zakończył się 321 PASS / 1 FAIL w debug: syntetyczny przykład
`sync_epoch_changed` pomijał wymagane `current_sync_epoch`,
`requested_sync_epoch` i `recovery_required`. Parser poprawnie go odrzucił.
Uzupełniono przykład i dodano osobną asercję odrzucenia brakujących szczegółów;
nie osłabiano kontraktu ani walidatora. Pierwotny log i raport zachowano.

To testy pamięciowego transportu, nie odbiór rzeczywistego HTTPS/API.
Nie uruchamiano nowych testów urządzenia. Schemat Room 13, wersja aplikacji,
zależności i protokół serwera pozostają bez zmian w tej części.
Nie wygenerowano ani nie zainstalowano nowego APK. Otwarty do testów pozostaje
odebrany [Android 0.8.22](POWROT_DO_POPRAWEK.md).

## Następna część: sesja i interfejs

1. Kontroler rezerwuje jedną operację dla przechwyconego konta, lease i pełnego
   kontekstu. Blokuje równoległy bootstrap, zmianę sesji, pull i inne mutacje.
   Wylogowanie lub A→B→A unieważniają przygotowanie i późną odpowiedź.
2. Po bootstrapie i pełnym pull korzysta z checkpointu trwałego snapshotu.
   `MealPushStore.prepare` utrwala batch i zamraża operacje przed HTTP;
   serializacja i walidacja JSON pozostają poza blokadą sesji. Kontrola
   tuż przed wysyłką atomowo sprawdza aktualność i oznacza próbę.
3. Po utracie ACK lub restarcie wznawia ten sam batch. Po 401 odświeża najwyżej
   raz, z ponowną kontrolą kontekstu. 429/503 utrwala wspólny backoff;
   brak odpowiedzi nigdy nie potwierdza nawet prefiksu kolejki.
4. Pełny ACK jest przygotowywany poza blokadą sesji, a stosowany atomowo
   z kontrolą biletu, kontekstu oraz wersji wierszy. Nowsza lokalna poprawka
   pozostaje; kolejna operacja dostaje rewizję z potwierdzonego poprzednika.
   Konflikt/odrzucenie pozostawia lokalne dane do świadomego uzgodnienia.
5. Odmowa epoki/generacji/reconciliation blokuje zwykłe wysyłanie i wymaga
   właściwego recovery; `account_deleting` blokuje dostęp trwale. Wygasły
   checkpoint wymaga pełnego pull i kontrolowanego przegrupowania koperty
   z niezmienionymi operacjami oraz zachowaniem starego żądania jako dowodu.
6. Interfejs pokazuje lokalne oczekiwanie, rzeczywiste potwierdzenie, backoff
   i potrzebę uzgodnienia osobno. Po push odświeża pełną kopię serwera.
   Nie nazywa kopii serwera kompletną synchronizacją lokalnych typów legacy.

Odbiór tej części będzie wymagał testów Room i sesji: lost ACK/restart,
odświeżenie/backoff, zatrzymana odpowiedź po logout/A→B→A/kontekście,
awaria atomowego zapisu, nowa porcja podczas lotu i konflikt późniejszej
operacji. Dopiero po kwalifikacji nowego APK można zaktualizować emulator.

Nie jest to pełne E4, konwersja historycznych typów, automatyczne wysyłanie
WorkManager, pełne recovery/retencja ani rzeczywisty odbiór APK/API/KO32.
Nie zmienia się protokół lub używana instalacja serwera. Nie wywołujemy
Gemini, nie otwieramy relay i nie podmieniamy osobnego kandydata API.
