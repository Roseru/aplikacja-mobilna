# Obserwacja rzeczywistych odczytów APK — agent 1

Stan integracji20.10.2026/O1-085: rodzic PR64 jest już scalony jako
`79dc7d931547c1b74061606342e5a8112649d236` po własnym8/8CI39416910290.
PR73 otrzymuje ten main zwykłym merge i ma uzyskać własny nowy pełny CI.
Poniższe przygotowanie pozostaje historią. Rzeczywisty wynik późnego GET
opisuje [R2](ODBIOR_APK_API_O1_R2_20261019.md), kolejne odczyty
[R3](ODBIOR_APK_API_O1_R3_20261019.md), a ich ograniczony odbiór
[raport O2](ODBIOR_R2_R3_ORACLE_E4_O2.md).
Oba raporty O1 skopiowano bajtowo z dokładnego a41a5cb/PR129; nie przeniesiono
kodu tej gałęzi. Kod aplikacji i drivera PR73 pozostaje identyczny ze źródłem
e319e531 faktycznie użytym w R2/R3. Nowy CI nie jest nową próbą live.
Aktualny kanał validation ma versionCode1023 i versionName0.8.12.validation;
wcześniejsze opisy versionCode23 poniżej dotyczą przygotowania przed rozdzieleniem kanałów.

Przygotowanie 14.10.2026 na `codex/android-odbior-api`. Zależność źródeł:
`4b4e8a3255f2b3c182954b7f83de9daa2ef7adc5`, niescalony PR64.
To osobny etap odbioru, nie nowe rozpoznawanie zdjęć ani zmiana backendu.
Normatywny scenariusz: [odbiór O2](ODBIOR_APK_API_O2.md), odpowiedź O3-035
w [dzienniku](../KOMUNIKACJA_AGENTOW.md).

## Co rejestruje wariant validation

`HttpsJsonTransport` przekazuje do obserwatora tylko metodę, ścieżkę, status
i dwa konkretne nagłówki. Validation dopuszcza wyłącznie GET `/api/v1/me`
i `/api/v1/me/motivation`. Zapis `O1ApiReadReceipt` zawiera czas UTC, status,
boolean obecności dyrektywy no-store oraz kanoniczny UUID X-Request-ID.
Brak identyfikatora jest oznaczony `missing`, niepoprawny — `invalid`, bez jego
surowej wartości. Nie zapisujemy URL/query, tokenu, cookies, ownera, body lub mapy
wszystkich nagłówków. Obserwacja nie zastępuje istniejących kontroli TLS,
limitu odpowiedzi, deadline, parserów DTO, ownera ani cancellation.

Debug/release używają innego pliku źródłowego: stała ENABLED=false i no-op.
Validation używa własnego źródła; nie ma mechanizmu zdalnego włączania obserwacji
w zwykłym APK. To samo versionCode23/Room9 umożliwia install-r testowej aplikacji
z zachowaniem istniejących dzienników; SHA/source każdego artefaktu są odrębne.
Zwykłego APK użytkownika nie instalujemy w ramach tego odbioru.

## Punkt zatrzymania rzeczywistej odpowiedzi — przygotowany driver dla O2

O3-035 proponuje zatrzymanie pojedynczego rzeczywistego wyniku200 GET A po
odebraniu ograniczonego body, a przed zwrotem z gateway do istniejącego kontrolera.
O2 ma potwierdzić, czy spełnia to punkt8, czy wymagane jest opóźnienie strumienia
HTTP. Bramka jest teraz zaimplementowana wyłącznie w validation. Wykonanie na
prawdziwym serwerze pozostaje **NOT_RUN**, a końcowy oracle do odbioru O2.

Jeżeli O2 zaakceptuje granicę gateway, kolejne wykonanie powinno zachować:

1. Rzeczywisty GET A oraz odebrany wynik200 i neutralne metadane.
2. Jednorazowe zatrzymanie wyniku poza mutexem i transakcją Room, maksymalnie10s
   w ramach dotychczasowego całkowitego deadline.
3. Rzeczywisty logout do gościa przed uwolnieniem tego samego wyniku.
4. Uwolnienie bez NonCancellable, bez sztucznego DTO i bez obejścia sprawdzania
   sesji/ownera. Cancellation może odciąć dostawę; receipt określa dokładny punkt.
5. Dowód nieprzywrócenia A oraz prywatne porównanie Room/Vault/podglądu gościa.

Jeżeli wymagane jest opóźnienie strumienia, osobny transport przygotowuje O3;
O1 nie podmienia usług wspólnej instalacji. Sam fixture, anulowany request bez
odebranego wyniku lub log szyfrowanego TCP nie jest tym dowodem.

`LateReadGate` wstrzymuje jedynie pierwszy faktycznie odebrany200 wybranej
ścieżki po ograniczonym odczycie body. Nie otrzymuje DTO lub identity i nie
może ich podmienić. AtomicReference zużywa jednorazowe uzbrojenie; oczekiwanie
nie utrzymuje mutexa/transakcji. Limit to mniejsza z wartości:10s i pozostały deadline
HTTP, z propagacją cancellation/timeout i bez NonCancellable. Kolejne GET oraz
błędy HTTP nie są wstrzymywane.

`LiveApiLateReceiptTest` używa rzeczywistego Application/SessionController/Vault
po uprzednim browser PKCE konta A. Bez fixture tokenów lub gateway. Driver
czeka na odebrany wynik, wykonuje istniejący logout, sprawdza gościa, uwalnia
ten sam wynik i weryfikuje brak powrotu prywatnego podglądu oraz niezmienione
15 tabel danych lokalnych. Wartości wierszy nigdy nie trafiają do asercji/logów.
Neutralne zdarzenia: held → logout → released → guest_preserved.

Driver jest poza domyślnymi źródłami androidTest. Dodaje się go tylko przez
`-PO1_LIVE_API_RECEIPT_TEST=true` przy budowie. Samo dodanie źródła nie uruchamia
próby: runner wymaga też `-e live_api_receipt true` oraz istniejącej sesji/powiązania
konta. Pominięcie lub cancellation nie jest realnym PASS.

Próbę O1 wykonuje wyłącznie na swoim testowym AVD, po nowym uzgodnionym oknie O3,
check TLS/issuer, własnym lease, prywatnym baseline i logowaniu A. APK testu i
aplikacji muszą pochodzić z tego samego źródła. Dokładna klasa uruchomienia:

```text
adb -s OWNED_TEST_SERIAL shell am instrument -w -r -e class pl.roseru.kalorie.LiveApiLateReceiptTest -e live_api_receipt true pl.roseru.kalorie.validation.test/androidx.test.runner.AndroidJUnitRunner
```

To celowo kończy sesję A i pozostawia gościa. Nie używać na zwykłej aplikacji lub
urządzeniu użytkownika. Surowy wynik runnera, Room/Vault i XML pozostają prywatne.
Do publikacji trafia dopiero rzeczywisty wynik, neutralne zdarzenia i equality.

## Odbiór i publikacja

Weryfikacja obejmuje formatowanie/redakcję/allowlist nagłówków, zbudowanie obu
implementacji wariantowych i rzeczywiste GET z aktualnego APK. Build/test/HTTP
mają osobne wyniki. Po install-r porównujemy pełne23tabele przed/po, a po GET
dziennik, cel i outbox pozostają bez zmian. Nie wykonujemy PUT zgód/importu/push.

Własny odbiór obserwacji **PASS**, 14.10.2026. Build debug/validation i lint
(0 błędów) zakończone; 165 JVM debug i 168 JVM validation bez błędów/pominięć.
Pierwsza próba validation miała 3 błędy stubu android.util.Log; opcjonalny logger
teraz nie przerywa GET, asercji nie zmieniano. Wcześniejszy wynik zachowano.
Tag loggera występuje w DEX validation, nie występuje w DEX zwykłego debug.
Nie wykonano nowego pełnego native188 na tych źródłach; wynik188 z O1-038 jest
oddzielnym dowodem poprzedniego źródła.

Aktualny APK validation: 0.8.12/code23/Room9, SHA256
`4bad317a5115482d5319e12bb1f18a1ec83ae36d40dbda6e698d8a260933a628`.
Wszystkie23tabele przed/po install-r są identyczne. Ponowne rzeczywiste logowanie
A przez Chrome/PKCE i oba GET przyjęte przez istniejący parser/controller;
wszystkie23tabele przed/po GET są identyczne. Niepusty dziennik gościa, cel i jego
pending outbox zachowane. Prywatne snapshoty/identity/tokeny poza Git.

| Faktyczny GET | Czas UTC 14.10.2026 | Status | no-store | X-Request-ID |
|---|---|---|---|---|
| `/api/v1/me` | 15:20:28.666258Z | 200 | true | `6ca4fbd6-5089-4d16-9299-c6bdeac8b231` |
| `/api/v1/me/motivation` | 15:22:36.401192Z | 200 | true | `9ae26b4e-9f2b-4464-87a3-74054f59065a` |

To receipt własnego APK, nie operatorskiego curl lub fixture. Logger został
odebrany na dedykowanym O1Api35/5558 w oknie O3-034; oryginalny issuer i CA
zachowane. Po próbie zamknięto wyłącznie własny lease/klienta przed17:25 CEST.

Pełny rozszerzony odbiór kont nadal **PARTIAL**: rzeczywista spóźniona odpowiedź
pozostaje NOT_RUN do uzgodnienia oracle O2. Kolejność merge: PR61 → PR64 →
ten zależny PR po retarget do aktualnego main i wymaganych kontrolach.

Nowe przygotowanie bramki: 165 JVM debug/174 JVM validation (w tym6testów bramki),
build obu wariantów i opt-in drivera oraz lint0error PASS. DEX zwykłego debug
nie zawiera bramki/loggera; validation zawiera. Osobny build bez właściwości
opt-in potwierdził brak drivera w domyślnym testowym APK. APK bramki ma odrębny
SHA256 `5706387aa603c2632ebd6051619ad2c55c436f94729bdbe994af340d9acaa86d`.
Historyczny receipt HTTP powyżej dotyczy wcześniejszego APK4bad317 i pozostaje
odrębnym dowodem; nie opisujemy go jako wykonania nowej bramki.

## Uzupełnienie O2-034 — dowód parsowania i rzeczywistego odrzucenia

Odczytano rozstrzygnięcie [O2/PR95](https://github.com/Roseru/aplikacja-mobilna/pull/95)
na main `82137d20bbbf0420237bdc109256c1e17f45c7b1`. Technika gateway jest
przyjęta; nie potrzeba opóźniania strumienia lub nowego proxy. Dodatkowy dowód
został zaimplementowany w istniejącym PR73. Wynik live nadal **NOT_RUN**.

Ticket bramki otrzymuje losowy neutralny `run` UUID. Kontroler przechwytuje
nieprzezroczysty obserwator dla tego ticket przed własnym GET me. Dopiero po
udanym istniejącym `ProfileReadProtocol.parse` emituje `dto_parsed`. Nie ma
drugiego parsera ani DTO przekazanego do obserwatora. W istniejącym
`withApiSession` wyłącznie `StaleOwnerException` po `requireApi(ticket)`
emituje `stale_owner_rejected`; oryginalny wyjątek jest dalej rzucany.
Błąd bazy, parsera lub zwykłe zakończenie `read.await(): Unit` nie stanowią
takiego dowodu. Catch nie obejmuje bloku aplikacji po guardzie.

Driver wymaga dokładnej kolejności jednego ticket/run:

`held → logout → released → dto_parsed → stale_owner_rejected → guest_preserved`.

`logout` jest emitowane po faktycznym wybraniu gościa; ostatni znacznik dopiero
po sprawdzeniu braku sesji/podglądu i równości 15 tabel danych. Nie opisujemy tego
jako identyczności wszystkich 23 tabel po celowym logout. Ticket nie zalicza
markerów parsowania/odrzucenia przed wymaganą kolejnością. Każdy event ma tylko
stałą nazwę, allowlisted path, neutralny run UUID i UTC. Bez body, identity,
tokenów lub exception message. Debug/release korzysta z nieaktywnej implementacji.

Regresje obejmują prawdziwy parser i guard kontrolera na deterministycznym
gateway oraz HTTP200 z `{}`: stary warunek Unit/guest przechodzi, ale nowy dowód
parsed/rejected pozostaje niekompletny. To test fixtures, nie rzeczywiste HTTPS.
Cancellation/expiry nadal oznacza bezpieczne przerwanie i live delivery NOT_RUN.
Nie zmieniono limitu10s, deadline, TLS, parsera, reguł właściciela ani cancellation.

Do PR73 przeniesiono tylko naprawę cold startu z PR96 (zakolejkowany start
Application oraz callbacku logowania). Nie przeniesiono panelu E7 lub jego
pozostałego kodu. Wariant validation ma osobny licznik `1000 + defaultConfig.versionCode`
i nazwę z `.validation`, korzystając z publicznego [VariantOutput API AGP8.9](https://developer.android.com/reference/tools/gradle-api/8.9/com/android/build/api/variant/VariantOutput).
Dzięki temu kolejne testowe APK aktualizuje istniejący pakiet bez downgrade,
uninstall/clear lub zmiany applicationId/callback. Debug/release zachowuje swój
licznik. Nie cofamy Room9 ani danych emulatora.

Lokalny build/test i gotowy nowy driver mają oddzielne wyniki od live. Nowy run
wymaga aktualnego okna O3 oraz fresh check/lease/PKCE; okna14.10 do17:25 nie
przedłużamy. Konta A/B zostały odebrane i nie trzeba dostarczać ich ponownie.

Weryfikacja poprawki O2-034:165JVM debug/180JVM validation bez błędów/pominięć,
lint0error, build obu wariantów i opt-in drivera PASS. Native79/79 PASS na
O1Tests35/API35 obejmuje dwa nowe testy kontrolera/parsera i trzy testy ekranów
zdjęć. Pierwszy start instrumentacji zakończył się ANR podczas ładowania klas
przy równoległych ANR systemowych; log zachowano. Po uruchomieniu tej samej
maszyny79testów przeszło bez resetu danych. Nie utożsamiamy tego z realnym API.
Domyślny testowy APK nie zawiera LiveApiLateReceiptTest (DEX sprawdzony).
Aktualny check relay O3-040 zakończył się timeout przed TLS; adres O1 wrócił do
wcześniej uzgodnionego172.18.4.123. Bez nowego dopasowania peer nie uruchamiamy
lease/klienta ani próby live. Szczegóły w O1-046.

Uzupełnienie O1-046 — gotowy build API/CA ze źródła `e319e53130020b3bbcdb50588ef4a2205a241118`:
validation0.8.12.validation/code1023/Room9 SHA256 `89164efd5199c8e1329f4fc833107a4045d034533ded6ef0e93f00996c50efcb`;
opt-in driver SHA256 `91b788998c3aa20b928e65e3f4d63a5ff3ad9048cc3de8c70f5ba8b86ecc231f`. Zweryfikowano w gotowym APK
issuer/API z zasobów, dokładny publiczny CA oraz obecność nowych markerów/drivera.
Build PASS; nie instalowano tego artefaktu na regularnym APK ani nie wykonano
live. Artefakty pozostają poza Git; native79 dotyczy wariantu fixtures z tego
samego źródła, nie dowodzi połączenia z API. O3 może uzgodnić okno i dokładny
peer na podstawie gotowego artefaktu. E0 PASS:10schematów/95valid/35invalid/
18scenariuszy/636linków; zdalne CI i merge nadal niepotwierdzone.

## Faktyczna instalacja kandydata O1-051 —15.10.2026

API/CA `89164efd5199c8e1329f4fc833107a4045d034533ded6ef0e93f00996c50efcb` i driver `91b788998c3aa20b928e65e3f4d63a5ff3ad9048cc3de8c70f5ba8b86ecc231f` z source `e319e53130020b3bbcdb50588ef4a2205a241118` zainstalowano17:53CEST na istniejącym O1Api35/API35. Version0.8.12.validation/code1023/Room9; zainstalowane base.apk mają zgodne SHA256. Wszystkie23tabele przed/po install-r identyczne, FK clean i niepusty gość/pending outbox zachowane. Prywatne Room/WAL poza Git/OneDrive, bez clear/uninstall/wipe. Aplikacja po snapshotach zatrzymana; brak nowych żądań serwera.

Aktualny peer192.168.137.29 i propozycja18:00–18:30CEST15.10 wymagają nowego potwierdzenia O3 oraz świeżego check/lease przed PKCE. Nie używamy starego relay. Realne sześć markerów, odbiór O2 i pełny rozszerzony wynik nadal NOT_RUN/PARTIAL. Regularny APK użytkownika i kolejka Room10 są osobnymi artefaktami.
