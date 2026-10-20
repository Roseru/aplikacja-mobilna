# Zlecenie analizy zdjęcia — stan implementacji Androida

Branch `codex/android-poprawki-posilkow`, zależny od dokładnego head `90d28c2db6c85ab0721dc5b972168120594617bb` / [PR105](https://github.com/Roseru/aplikacja-mobilna/pull/105). [PR121](https://github.com/Roseru/aplikacja-mobilna/pull/121) kierujemy na `codex/android-analiza-zdjec`; najpierw integrujemy rodzica, następnie zmieniamy bazę dziecka na main i sprawdzamy integrację.
Wejścia: [integracja O2](../docs/e7/INTEGRACJA_O1.md), [DTO](../backend/src/calorie_app/modules/ai/schemas.py) i [przykład create](../contracts/examples/e7/create-accepted.json).
Gotowe są transport, trwała kolejka, zgoda/wysyłka i jawne ponowienie oraz pobieranie/polling wyniku z podglądem lokalnym. Dostępne jest również świadome anulowanie i zamknięcie anulowanego zlecenia. Dostępny jest trwały lokalny szkic korekt. Zatwierdzenie na serwerze i zapis posiłku pozostają do wykonania. Ten etap nie jest odbiorem pełnego E7.

## Aktualny odbiór0.8.18 — trwałe poprawki składników

Kod `6e1eac8128de2a2036878de380c19817c369dbb5`, wersja0.8.18/code29,
validation1029, Room10 bez migracji. Użytkownik jawnie rozpoczyna korektę
pobranej propozycji i zapisuje szkic na telefonie. Może zmienić nazwę posiłku,
nazwy składników, ilość, g/ml oraz kcal i B/T/W na100g albo100ml; dodać lub
usunąć składnik i odrzucić poprawki po potwierdzeniu. Ostatniego składnika
nie można usunąć. Szkic ma1–30 pozycji, trwałe meal_id/item_id i powiązanie
ze źródłowym komponentem propozycji. Własny dodatek jest jawnie oznaczony.

Wartości są liczone przez BigDecimal; przecinek jest dozwolony, brak pozostaje
null, jawne0 pozostaje0. Nie przyjmujemy liczb ujemnych, wykładnika lub
przekroczenia granic. Pola żywieniowe są na100 jednostek; zmiana g/ml wymaga
własnego określenia tych wartości, bez zgadywania gęstości. Niezmieniona
propozycja AI i jej dopasowania pozostają obok szkicu. Stare długie nazwy
rozpoznania nie są cicho skracane; zapis do docelowego Meal wymaga limitu200.

Snapshot v3 czyta stare ACK/v1/v2 i przechowuje szkic wraz z wynikiem i
anulowaniem w istniejącym wierszu Room10. GET i cancel nie gubią poprawek.
DB-only CAS wymaga zgodnego właściciela, lease, kontekstu i całego poprzedniego
wiersza; lokalna rewizja chroni przed zapisem ze starego formularza. Niepewne
anulowanie, terminalne potwierdzenie lub zmiana konta blokują edycję, zachowując
szkic do odczytu. Otwarty dialog znika po zmianie konta/operacji/rewizji,
przejściu w tło lub utracie prawa do edycji. Zapisane poprawki przeżywają
restart, brak obrazu, wygasły token i wspólny Retry-After bez odnowienia lub HTTP.

Przygotowany serializer buduje przyszłe ConfirmRequest z expected_revision,
stałym meal_id i item_id, prawidłowym nullable payload oraz drafts=[];
product_id pozostaje null, nutrition_origin=ai_estimate. Niezależny fixture
sprawdzono normatywnym ai.schema: poprawny payload PASS, trzy mutacje
(liczbowe wartości odżywcze, pominięte nullable, provenance w sync-v1) odrzucone.
**Nie podłączono HTTP confirm, zapisu Meal/outbox, provenance E4 ani wyboru
produktu z katalogu. Szkic nie jest jeszcze wpisem dziennika.** Nie powstają
automatycznie produkty społecznościowe.

Pełne assemble debug/validation/testAPK **PASS**, **265 JVM debug /280 JVM
validation, lint0error PASS**. Nowe18 testów core; osobny native focus24/24
obejmuje18 testów Room,3 sesji i3 Compose. Następnie **245/245 native API35
PASS**, bez pominięć lub błędów,417.999s instrumentation/422.562s wall,
przy limicie1800s. Brak aktywnej sieci potwierdzony przed i po. Zainstalowane
APK odpowiadają hashom. Wszystkie231 rzeczywistych wejść kompilacji porównano
bitowo przed odbiorem, po buildzie i przy przeniesieniu do niezależnego klonu;
nie opublikowano zastanych braków plików lub uszkodzeń starego klonu Temp.

| Artefakt0.8.18, kod6e1eac8 | SHA-256 |
|---|---|
| Debug/code29 | `e6df50fb3384a875d17d5eb8ff57903153705791bf0b02bfaa7742f00c237a97` |
| Validation/code1029 | `9be491016507e0fab764cbf7ac218399c829b5dbcc8ecbc5ecadab232043bb56` |
| Domyślny testAPK | `f10c6b06ed63644e03e4f53d091c4ba5264776c9ff315822ad9ddc29cca304e4` |

Regularny emulator zaktualizowano przez install-r. Faktycznie zainstalowany
SHA zgodny z debug powyżej; wszystkie24 tabele Room10 identyczne przed,
po instalacji i po otwarciu aplikacji; FK clean. Prywatne snapshoty i ekran
pozostają poza Git/OneDrive. Świeża obserwacja potwierdziła właściwy pakiet,
brak ANR i główne kontrolki; aplikacja otwarta do testów manualnych.
Oddzielnego kandydata API/Room9 nie aktualizowano.

[Podgląd panelu](../propozycje-ui/analiza-0.8.18/README.md) obejrzano na320dp
przy czcionce150%. Pełny native mimo poprawnych asercji uchwycił nakładkę ANR
SystemUI. Diagnostykę zachowano, wybrano obserwowany przycisk Wait i powtórzono
wyłącznie3testy UI:3/3 PASS. Panel po powtórce jest czytelny bez nakładki.
Plik nazwany dialogiem ponownie uchwycił panel, więc nie publikujemy go jako
dowodu wyglądu dialogu. Asercje walidacji i resetu formularza zaliczone;
wizualny odbiór samego dialogu pozostaje do uzupełnienia.

Rzeczywiste APK/API, Gemini i E7-R: **NOT_RUN**. To oddzielny etap0.8.18,
nie odbiór pełnego E7. Zdalne CI nowego PR i merge wymagają osobnego sprawdzenia;
rodzic105 pozostaje bez zmian. Następny etap: utrwalona decyzja confirm,
bezpieczne ponowienie i uzgodnienie ACK/GET z kanonicznym E4/provenance,
bez drugiego zapisu posiłku; dalej retencja osieroconych plików.

## Historyczny odbiór0.8.17 — świadome anulowanie analizy

Kod `24526ddab2b4a442b57581f8b3508ffc79a82fd3`, wersja0.8.17/code28, validation1028, Room10. Po jawnym pobraniu stanu można wybrać „Anuluj analizę na serwerze”. Dialog wyjaśnia zachowanie zdjęcia i dziennika oraz to, że anulowanie nie cofa przetwarzania wykonanego już przez dostawcę. Dopiero potwierdzenie utrwala i wysyła jedną decyzję. Zmiana konta, zlecenia lub pokazanej rewizji oraz przejście w tło unieważniają otwarty dialog.

SessionController zapisuje klucz i rewizję decyzji przed siecią. „Ponów anulowanie” zachowuje dokładnie tę samą operację, również po utracie odpowiedzi lub ponownym uruchomieniu. Nie ma automatycznego CANCEL przy wejściu na ekran, starcie lub odzyskaniu internetu. Jedna próba ma limit45s,401 pozwala na jedno odnowienie bez zmiany żądania;429/503 utrwala wspólny Retry-After. Konflikt rewizji wymaga nowszego GET i kolejnego świadomego potwierdzenia. Zmiana epoki/generacji/kontekstu wymaga recovery, a403/404/410 blokują niedostępne zlecenie.

Każda wysyłka i zapis odpowiedzi wymagają zgodnej sesji, captured lease/operacji/kontekstu i dokładnego snapshotu. Zmiana konta A→B→A, wyjście w tło lub zmiana mapowania odrzuca spóźniony ACK i zachowuje trwałą decyzję do uzgodnienia. Parsowanie i IO obrazu pozostają poza mutexem/Room. Po zweryfikowanym ACK albo GET cancelled stary podgląd propozycji znika; starszy GET nie cofa anulowania ani nie uruchamia dalszego pollingu.

„Zamknij anulowane zlecenie” jest osobnym lokalnym krokiem, dostępnym również z wygasłym tokenem. Wymaga zapisanego dowodu anulowania, zwalnia kolejkę w transakcji i dopiero potem usuwa jej przygotowaną kopię obrazu. Zdjęcie źródłowe i dziennik pozostają. Przerwanie sprzątania może pozostawić niepowiązany plik do późniejszej retencji. Samo anulowanie nie zapisuje Meal/ProductDraft/celu/outbox i nie anuluje już zatwierdzonego posiłku.

**Pełne assemble debug/validation/testAPK,247 JVM debug/262 JVM validation, lint0error PASS. Nowe8/8 regresji sesji i Compose PASS, następnie pełne235/235 native API35 PASS**, bez pominięć, offline przed/po i ze zgodnością SHA zainstalowanych APK. Pełny przebieg trwał247.75s przy limicie1800s. Nowe scenariusze obejmują lost ACK/restart, dokładne ponowienie,401 tylko raz, wspólny429, held ACK po wyjściu/zmianie kontekstu/A→B→A,409 z nową rewizją i decyzją, błędny ACK/recovery oraz dialog i retry/release na320dp przy czcionce150%. Wcześniejszy223PASS i14Room pozostają oddzielnymi dowodami swoich commitów. Dowód225 wejść źródłowych sprawdzono przed odbiorem i po buildzie; bez zmian kodu podczas przebiegów.

| Artefakt0.8.17, kod24526dd | SHA-256 |
|---|---|
| Debug/code28 | `94b6bc00309375dbc170baa123f686c0ad65261662e145679b1d56deaf4974bf` |
| Validation/code1028 | `f2a1fda9e3b2eb58001eb943d359ae8a9d9bb437dcf505b06a4e821dca203b26` |
| Domyślny testAPK | `170ae5529ace40ddb5eef7de05cba87acdf45d51225544c6c4ec79d8f48c81bf` |

Regularny emulator zaktualizowano przez install-r i porównano z debug SHA; wszystkie24 tabele Room10 identyczne przed/po, FK clean. Prywatne snapshoty pozostają poza repozytorium/OneDrive. Nie zmieniono oddzielnego kandydata API/Room9, nie wykonano wipe/clear/uninstall ani restartu komputera. Aplikacja jest otwarta do testów manualnych: świeża hierarchia potwierdza właściwy pakiet, brak ANR i główne kontrolki. Pierwszy odczyt tuż po starcie zwrócił brak korzenia hierarchii; aplikacja działała jako resumed Activity. Ponowiono wyłącznie obserwację, zachowując pierwszy log, bez ponownej instalacji lub restartu.

**Rzeczywiste APK/API, Gemini i E7-R: NOT_RUN.** Testy używają syntetycznych odpowiedzi, nie dowodzą anulowania na prawdziwym serwerze. Pełny zdalny CI105 i merge pozostają osobnymi krokami. Nadal potrzebne są korekty składników/porcji, confirm/provenance/kanoniczny E4 i retencja plików osieroconych. Ten odbiór nie zamyka całego E7.

## Historyczny fundament — trwała decyzja anulowania, 17.10.2026

Kod `22cccb22125eddef3cfcb6dd9caa2f01d8bbfe64` dodaje fundament anulowania: klucz i rewizja jednej decyzji pozostają niezmienne przy niepewnym ponowieniu. Snapshot `photo-analysis-state-v2` czyta również wcześniejsze ACK i v1, zachowuje dotychczasowy wynik oraz zapisuje próbę, potwierdzenie albo rozpoznane odrzucenie. Utrata odpowiedzi nie tworzy nowego klucza; nowa decyzja po konflikcie rewizji wymaga nowszego GET i osobnego klucza. Potwierdzenie jest walidowane na prywatnej kopii bajtów. Starszy odczyt nie cofa zweryfikowanego anulowania.

Room nadal10, bez nowej migracji. Parser i przygotowanie zapisu działają poza guardem; transakcja sprawdza cały poprzedni wiersz, właściciela/lease/kontekst i dokładne żądanie. Zapis nie skraca Retry-After. Zwolnienie kolejki wymaga potwierdzonego anulowania przez ACK lub GET i osobnego jawnego kroku. Usunięcie przygotowanego wejścia jest oddzielone od transakcji; nie usuwa oryginalnego zdjęcia, posiłków ani outbox. Przerwane sprzątanie może pozostawić plik do późniejszej retencji.

**To fundament danych, jeszcze bez wywołania CANCEL z SessionController i bez przycisku w UI.** Przyciski obecnego ekranu nadal realizują odbiór GET opisany poniżej. Nie deklarujemy wykonanego anulowania na serwerze ani zamknięcia E7. Następny krok: sesja, jawne potwierdzenie użytkownika, ponowienie tej samej decyzji oraz regresje utraty odpowiedzi i zmiany konta.

Walidacja tego commita: pełne assemble debug/validation/testAPK, **247 JVM debug i262 JVM validation PASS, lint0error**. Na API35 wykonano **14/14 PhotoAnalysisStorageTest PASS**, bez pominięć, z trybem offline sprawdzonym przed/po i zgodnością zainstalowanych APK. Cztery nowe przypadki obejmują odtworzenie decyzji po ponownym otwarciu Room, konflikt CAS i backoff, przypięcie do żądania/kontekstu/A→B→A oraz zwolnienie kolejki przed sprzątaniem pliku. Poprzedziło to77/77 lekkich testów JVM. Pełny nowy zestaw urządzenia227: **NOT_RUN**; runtime/UI anulowania: **NOT_CONNECTED**; rzeczywiste APK/API i Gemini: **NOT_RUN**. Historyczny223PASS poniżej dotyczy kodu GET `a4447e4`, nie tego etapu.

Zestaw techniczny nadal0.8.16/code27, validation1027; nie jest nowym wydaniem do testów użytkownika. Nowe validation/testAPK uruchomiono wyłącznie na O1Tests35. Regularny emulator zachowuje poprzedni debug `cb1f7003…` z odbiorem danych23tabel, a osobny kandydat API/Room9 pozostaje bez zmian.

| Artefakt fundamentu anulowania | SHA-256 |
|---|---|
| Debug0.8.16/code27, kod22cccb2 | `39793e884d4f08b762dc009691981b7422ee33aa9ae2744def1dfc99594dc0de` |
| Validation0.8.16/code1027, kod22cccb2 | `2174292d897f04fc969880de8a568e5ce05cdb880da21c7c3e8b4bf47f8942a3` |
| TestAPK fundamentu,14 testów Room | `36512f489333f2b1c8682d4aa340ef85f5af9c0ccf57cac6cc56f05192a03397` |

Archiwalne APK/logi i dowód222 wejść kompilacji zachowano poza Git. To inne bajty niż zestaw GET poniżej; równa nazwa wersji nie oznacza tej samej aplikacji. Własny pełny CI105 oraz odbiór serwera pozostają osobnymi krokami.

## Odbiór GET0.8.16 — kod a4447e4, sesja i podgląd

Wersja0.8.16/code27, validation1027, Room10. Ekran zdjęć odtwarza zapisany wynik lokalnie, również bez obrazu i po wygaśnięciu tokenu. Wejście/powrót na ekran nie uruchamia HTTP. „Sprawdź wynik” rozpoczyna jawny GET; „Zatrzymaj sprawdzanie” unieważnia dalsze żądania i spóźnione odpowiedzi, ale nie anuluje analizy na serwerze. Wyjście w tło/opuszczenie ekranu usuwa prywatny podgląd z UI i zatrzymuje dalsze sprawdzanie.

Odczyt używa captured owner/lease/operacji/kontekstu i wspólnego guardu operacji konta. Pierwszy jawny GET może odzyskać gotową propozycję po terminie obrazu; dopiero zwalidowana odpowiedź working wyznacza granice automatycznego pollingu. Każda próba, także ponowienie po401, zużywa budżet12 prób/120s z timeoutem≤45s i odstępami2/4/8/15/30s.429/503 utrwala maksymalny wspólny Retry-After i kończy pętlę do jawnego ponowienia.403/404/410 blokuje niedostępny wynik,409 zmiany epoki/generacji/kontekstu wymaga recovery. Błędny JSON/timeout/stop nie uruchamia POST i zachowuje ACK oraz dziennik.

Prezentacja pokazuje źródło/mock, stan/decyzję, składniki g/ml, kcal/B/T/W, niepewność i notatki. Sumy są liczone przez NutritionV1; null pozostaje brakiem danych, nie zerem. Niepełna suma jest jawnie opisana. Projekcja jest niemutowalna, redagowana w logach i powstaje poza mutexem/Room. Ten odczyt nie zapisuje Meal/ProductDraft/celu/outbox.

**Pełna walidacja źródła GET a4447e4:235 JVM debug/250 JVM validation, assemble debug/validation/testAPK, lint0error i223/223 native API35 PASS, bez pominięć.** Native wykonano na zachowanym O1Tests35, offline przed/po (tryb samolotowy1, Wi-Fi wyłączone, brak aktywnej sieci). Pierwszy pełny przebieg221PASS/2FAIL ujawnił dwa testowe selektory Compose, które porównywały fragment jako cały napis. Poprawiono wyłącznie `substring=true`, bez zmiany tekstu produktu i bez osłabienia oczekiwanych wartości. Oba APK aplikacji pozostały identyczne; przebudowano testAPK i ponowiono cały zestaw. Oddzielna nieudana próba Gradle nie połączyła się z lokalnym daemonem, zanim ruszyły zadania; log zachowano. Bez wipe/uninstall/clear lub restartu komputera przez O1. Drugi przebieg223PASS objął długą przerwę sesji (96798s); zachowano go osobno. Końcowy nowy przebieg17.10 miał ograniczenie1800s i zakończył się po1187.391s; to on stanowi bieżący odbiór.

| Artefakt | SHA-256 |
|---|---|
| Debug0.8.16/code27 | `cb1f7003aebbbfef6a522bc53272df8768fe339118b7fc1ab8097b77d839b88d` |
| Validation0.8.16/code1027 | `71837a090776bfe760eb0d3fb5398b1a6df72366d9e386d28aca184eb67fc9e7` |
| TestAPK końcowego pełnego przebiegu | `c2d84b98391efb1c8a5bda84582a02e866d7a6e83faefd59a32d64f0f977986f` |

Domyślny testAPK wyklucza driver rzeczywistego API; debug wyklucza bramkę obserwacji. Testy używają syntetycznych fixture i transportu testowego. **Rzeczywiste APK/API, Gemini i E7-R: NOT_RUN.** Nie dodano sekretów ani wywołań Google. Pełny zdalny CI PR105 nie uruchamia się dla obecnej bazy dziecka; ewentualna kontrola konfiguracji Dependabot nie zastępuje Android CI. Lokalny PASS nie oznacza zielonego CI lub merge. Kolejność61→64→73→96→105 pozostaje obowiązująca.

## Opis i historyczne checkpointy implementacji

Poniższe mniejsze odbiory pokazują stan w chwili ich publikacji. Ich dawne NOT_RUN/„do podłączenia” nie zastępują aktualnego odbioru powyżej; ograniczenia pełnego E7 nadal obowiązują.

## Trwała kolejka

`PhotoAnalysisStore` zachowuje jedno nierozstrzygnięte zlecenie na konto. Room10 zapisuje key/epokę, account generation/context revision, źródło zdjęcia, provider/model/notice, czas jawnej zgody, hash/rozmiar wejścia, attempted, Retry-After, blokadę i ACK. Nie zapisuje tokenu ani obrazu w BLOB. Osobna kopia przygotowanego JPEG jest prywatnym plikiem konta/operacji, niedostępnym przez Camera FileProvider. Usunięcie zdjęcia źródłowego nie usuwa wejścia do retry.

Przygotowanie wymaga jawnego accepted=true, dostępnego capabilities, konta i gotowego bootstrapu. Odczyt obrazu, hash i AtomicFile write odbywają się poza Room. Przed commit następuje ponowne sprawdzenie lease/konta/kontekstu. Błąd usuwa tylko własny niezatwierdzony plik; cancellation po commit zachowuje powiązane wejście. Zabicie procesu przed Room może pozostawić niepowiązany plik — jego sprzątanie pozostaje częścią integracji retencji.

Retry odczytuje i sprawdza zachowaną kopię, bez ponownego pobierania z galerii lub kodowania. Ten sam key/image/metadata odtwarzają te same bajty multipart po restarcie i lost ACK. B ani stary lease A nie mają dostępu do kolejki A. Powrót A wymaga aktualnego lease i zgodnego kontekstu serwera. Zmiana account ID/generacji/epoki/context revision lub recovery blokuje wysyłkę i zachowuje dane. Nigdy niewysłaną operację można jawnie odrzucić lokalnie, również po zmianie kontekstu; attempted nie oznacza pewnego braku wysyłki.

ACK jest ściśle parsowany i zapisywany atomowo. Identyczne potwierdzenie jest idempotentne; inne ID/treść nie zastępują ACK. Późny błąd lub Retry-After nie cofają przyjęcia. Kolejka nie zapisuje Meal, ProductDraft, celu ani outbox. Autoryzację tokenu, wspólny backoff i guard operacji sieciowej obsługuje SessionController. Odczyt pliku/hash/encoding multipart i parsowanie ACK są poza jego mutexem/transakcją. `prepareReceipt` wiąże ACK z dokładnym wysłanym key/epoką/providerem/notice/hashem obrazu. `acceptPrepared` wykonuje tylko walidację i commit w Room, pod aktualnym guardem sesji.

## Zgoda i wysyłka z aktywnej sesji

Ekran zapisanych zdjęć udostępnia „Analizuj to zdjęcie” po zalogowaniu, bootstrapie i aktualnym odczycie dostępnego providera. Okno pokazuje dostawcę/model, cel, retencję backendu do24h, zasady dostawcy i szacunkowy charakter wyniku. Checkbox zgody jest wyłączony na początku. Anulowanie, zmiana zdjęcia/konta/providera/modelu/notice oraz wyjście aplikacji w tło resetują zgodę. Potwierdzenie obejmuje jedno zdjęcie; wybór z galerii/aparatu nie uruchamia sieci.

UI przekazuje captured lease oraz dokładny provider/model/notice. Kontroler ponownie sprawdza sesję, bootstrap, kontekst i tę samą wersję dostępności; najpierw utrwala wejście, potem rozpoczyna POST. Nie uruchamia wysyłki przy starcie lub powrocie aplikacji. Jedna operacja online nie pokrywa się z inną operacją konta. Logout/logowanie/odnowienie ręczne unieważniają wcześniejszą operację; spóźniony ACK po A→B→A nie zapisuje potwierdzenia ani wiadomości w nowym zakresie.

Wygaśnięty token jest odświeżany przed próbą;401 pozwala na jedno odnowienie, bez zmiany key/body.429/503 i409`ai_operation_busy` zachowują operację oraz trwały wspólny backoff. Przy409busy bez Retry-After domyślna przerwa wynosi30s. Konflikty `sync_epoch_changed`, `account_generation_changed` i `analysis_context_changed` oznaczają wymagane uzgodnienie stanu; nie odtwarzamy starej próby automatycznie. Niepewna odpowiedź/timeout/cancellation zachowuje wejście do jawnego retry. Retry nie potrzebuje ponownego otwierania galerii i korzysta z uprzednio zapisanej zgody na ten obraz/provider/notice.

Panel rozróżnia zlecenie niewysłane, próbę bez potwierdzenia, przyjęcie202 i blokadę. Tylko operację nigdy niepróbowaną można usunąć lokalnie; próby niepewnej nie traktujemy jako bezpiecznie niewysłanej.202 nie oznacza rozpoznania ani zapisu posiłku. ACK pozostaje w kolejce do dalszego odczytu/rozstrzygnięcia; w tej części nie dodajemy kolejnego zlecenia obok nierozstrzygniętego.

Wersja wewnętrzna0.8.15/code26, validation1026. Room nadal10, bez nowej migracji. Checkpoint przed przerwaniem pracy: **186JVM debug/201JVM validation, oba APK/testAPK i lint0error PASS. Nowe testy urządzenia: NOT_RUN. Rzeczywiste APK/API i Google: NOT_RUN.** Pakiet testowy kompiluje osiem nowych regresji SessionController, dwa testy Compose zgody/kolejki i dodatkowy przypadek commit ACK bez IO. Są przygotowane do wykonania na O1Tests35; nie dziedziczą poprzedniego native200PASS.

Validation0.8.15.validation/code1026/Room10 SHA256 `9d220bc4435f579bc94a3bead205c7962e4593880ac484d9afdb41c1d8c947ee`.
TestAPK SHA256 `d6a8277126aeb30c215d7fc631c1caa942d4bfa163eb3d30501a6cb9b5050d6c`. Domyślny testAPK wyklucza driver live, debug wyklucza bramkę obserwacji. Regularna instalacja użytkownika i osobny kandydat rzeczywistego API nie zostały podmienione. Po checkpointcie zamknięto wyłącznie własny bezczynny O1Tests35 z zachowaniem danych; nie rozpoczęto instrumentacji.

Pierwszy build przerwany bez wyniku. Kolejne dwie próby wykazały dwa wygenerowane metadata JSON wypełnione zerami. Zachowano ich kopie i logi, sprawdzono pozostałe JSON-y pod build, usunięto wyłącznie te dwa potwierdzone uszkodzone artefakty; Gradle odtworzył je ze źródeł. Końcowy pełny build zakończył się sukcesem. Bez clean/uninstall/wipe i bez zmiany źródeł w celu ominięcia błędu środowiska. Historyczny wynik poniżej dotyczy poprzedniego checkpointu kolejki.

## Transport

`PhotoHttpRequest` buduje typed create/read/cancel. Jeden multipart ma metadata JSON/consent i niezmienne image. Waliduje rozmiary, sygnaturę/MIME, UUID i wstrzyknięcie granicy; filename jest stały, bez ścieżki użytkownika. ACK create/cancel odrzucają nieznane/brakujące pola, duplikaty, nieprawidłowy UTF-8/UUID/UTC/revision/provider. Replay ACK queued nie jest bieżącym stanem zadania.

Wspólny HTTPS ma bounded JSON/no-store, bez redirects/cache/automatycznego retry. Mutacje mają key/epokę, GET ich nie dostaje. Multipart o znanej długości jest zapisywany w blokach4KiB, z cancellation/deadline między blokami; systemowy write może blokować. Callback sprawdza autoryzację przed wysyłką. Proxy429/503 zachowuje Retry-After bez parsowania HTML. Parser pełnego odczytu/propozycji opisano poniżej; pobieranie i polling nie są jeszcze podłączone do sesji.

## Parser wyniku — etap16.10

`PhotoAnalysisReadProtocol` dekoduje pełny GET i propozycję jako odczyt bez IO, zapisu, publikacji produktu lub planowania sieci. Wymaga ID z zapisanego ACK, rewizji nie starszej od ACK, niezmiennego deadline i dokładnego profilu analizy. Waliduje zgodność state/decision/proposal/error, UTC, wymagane nullable pola oraz odrzuca dodatkowe/zdublowane klucze, błędny UTF-8 i głębokość ponad20. Cała odpowiedź ma limit2MiB, sama propozycja1MiB; limit całego GET uwzględnia obudowę wokół maksymalnej propozycji.

Wynik ma1–30 składników o unikalnych component ID, kanoniczne dodatnie ilości i wartości Decimal, g/ml zgodne z basis oraz density=null. Stany brand/variant/composition zachowują znaczenie known/unknown/not_applicable i nullable wartości; skład może być tekstem receptury lub listą. Matching przechowuje exact product ID/revision, powody/provenance i niepewność, bez automatycznej decyzji lub utworzenia produktu. Brak składnika odżywczego pozostaje null. Sumy i zaokrąglony display każdego pola są porównywane z niezależnym przeliczeniem istniejącego NutritionV1: known_sum, missing_count i complete muszą odpowiadać składnikom. Kolekcje są niemodyfikowalne; DTO i błędy mają neutralny tekst bez prywatnej treści.

**Walidacja tego parsera:25 testów JVM PASS —16 nowych+9 istniejącego protokołu.** Uruchomiono osobny kompilator Kotlin2.1.20 i JUnit na klasach bazowego checkpointu e633ace, z jednym procesorem, heap384MiB i obniżonym priorytetem, bez Gradle/emulatora. [Syntetyczny GET](app/src/test/resources/photo/analysis-read-succeeded.json), zbudowany z normatywnych create/provider examples, przeszedł także przypięty `ai.schema.json#/$defs/AnalysisResponse`. Pierwszy lekki przebieg23/23, po dodaniu granicy rozmiaru24/24, po pozytywnych gałęziach matching25/25. Nie było błędnych prób ani pominięć.

To nie jest pełny build/test/lint Androida bieżącego źródła. APK i wyniki186/201JVM z poprzedniej części dotyczą checkpointu e633ace; APK z parserem jeszcze nie zbudowano. Native nowego runtime/UI i rzeczywisty APK/API pozostają NOT_RUN. Limit transportu GET jest już zwiększony do2MiB w kolejnym etapie opisanym poniżej; mutacje zachowują1MiB. Pozostają owner/session guard odczytu, trwały monotoniczny stan odpowiedzi, bounded polling/deadline/cancel, prezentacja/korekta i confirm/E4. Parser sam nie uprawnia do zapisu posiłku.

## Postęp i budżet odczytu

`PhotoAnalysisProgress` porównuje zwalidowane odczyty tej samej analizy, niezmiennego profilu, deadline i wygaśnięcia obrazu. Starsza rewizja pozostawia bieżący snapshot. Identyczny replay jest idempotentny, sprzeczne treści tej samej rewizji są odrzucane; fingerprinty powstają z kanonicznego JSON i nie trafiają do logów. Wynik sukcesu nie może zmienić propozycji przy późniejszej rewizji. Pending może przejść do confirm lub cancel, ale potwierdzona/anulowana decyzja nie wraca do pending. Można pominąć obserwację pośrednich stanów. Backend ponawia wewnętrzny job, pozostawiając AnalysisResponse.state=running; analiza running→queued jest więc cofnięciem, a nie prawidłowym retry.

`PhotoPollBudget` jest niemutowalnym budżetem przyszłej pętli foreground, bez harmonogramu/HTTP. Przed każdą próbą zwraca nową rezerwację, oczekiwanie lub stop. Maksimum12 prób/120s według zegara monotonicznego, timeout pojedynczej próby do45s i nie dłużej niż pozostałe okno. Odstępy2/4/8/15/30s respektują wspólny Retry-After, bez skracania go lub wydłużania okna. Granica serwera to minimum photo_expires_at i queue_deadline+120s, aby nie uciąć pracy rozpoczętej tuż przed końcem kolejki. Terminalny wynik zatrzymuje automatyczne odczyty. Zmiana zegara/overflow kończy budżet bez wysłania. Budżet nie nadaje autoryzacji i nie zastępuje captured lease ani trwałego zapisu rewizji.

Gateway stosuje2MiB dla GET i dotychczasowe1MiB dla mutacji. Mock HTTPS potwierdza przyjęcie odpowiedzi ponad1MiB dla GET, odrzucenie ponad2MiB przed czytaniem, brak mutation headers GET oraz zachowanie wcześniejszych zasad no-store/redirect/cancellation.

**Walidacja:47/47 standalone JVM PASS** —16 decoder,13 progress/budget,9 multipart/ACK i9 HTTP (w tym2 nowe). Kompilowano bieżący kod tych klas Kotlin2.1.20/JUnit przeciw niezmienionym klasom bazowym e633ace. Jeden procesor/heap384MiB/niski priorytet, bez Gradle/emulatora i rzeczywistej sieci. Kompilator JBR zgłosił wyłącznie deprecation istniejącego użycia URL(String); nie zmieniano narzędzi. Nie zaliczamy pełnego Android build/lint/native ani realnego API tego źródła.

Pętla odczytu i integracja SessionController/UI nie są jeszcze podłączone. Trwały ostatni snapshot/CAS w Room opisano poniżej; pozostaje guard sesji i bounded polling/cancel oraz edycja/confirm. Sam budżet nie uruchamia żądań po starcie aplikacji, nie powtarza analizy i nie zapisuje posiłku. APK e633ace pozostaje wcześniejszym checkpointem, bez tych nowych klas.

## Trwały wynik i zapis warunkowy

`PhotoAnalysisSnapshot` wersjonuje wartość istniejącej kolumny receiptJson jako `photo-analysis-state-v1`: niezmienny create ACK i ostatni zwalidowany GET. Czyta także starszy format samego ACK; aktualizuje go dopiero przy przyjęciu GET. Room pozostaje w wersji10, bez nowej tabeli/migracji. Odtworzenie ACK nie wymaga obrazu ani rekonstrukcji żądania multipart. Parser ponownie sprawdza provider, powiązanie GET z ACK, stan/revision/propozycję i limity. Zapis ma limit2MiB+64KiB, dodatkowo1024 bajty obudowy; pierwotne limity GET/ACK pozostają obowiązujące. Błędy i toString nie zawierają prywatnej treści.

Pierwszy GET nie może cofnąć stanu znanego z ACK. Kolejne odczyty używają PhotoAnalysisProgress; stare/identyczne pozostawiają ten sam zapis. Ponowny POST ACK musi odpowiadać oryginalnemu i nie usuwa ostatniego GET, również po restarcie. Format nie nadaje uprawnień do zapisu dziennika.

`PhotoAnalysisStore.stored` dekoduje zapis bez pliku zdjęcia; po parsowaniu ponownie sprawdza bieżący wiersz i lease. `prepareRead` przeprowadza parsowanie/uzgodnienie poza transakcją. `acceptReadPrepared` jest wyłącznie DB: porównuje cały przechwycony wiersz, aktualny owner/lease i kontekst serwera, następnie atomowo zapisuje przygotowaną wartość. Zmiana rewizji, backoffu, właściciela lub kontekstu od czasu przygotowania odrzuca commit; wywołujący musi ponownie przygotować odczyt. Spóźniony ACK przygotowany przed nowym GET jest odrzucany, a poprawne ponowienie ACK przygotowane z aktualnego zapisu jest no-op. Nie ma parsowania, hashowania ani IO obrazu pod guardem commit.

**59/59 standalone JVM PASS**:16 decoder+13 progress/budget+9 create/ACK+9 HTTP+12 snapshot. Drugi przebieg skompilował także bieżący PhotoAnalysisStore oraz cały PhotoAnalysisStorageTest przeciw przypiętym Android35/Room2.7.2 i klasom checkpointu; testy Room nie zostały wykonane. Jedyny procesor/heap384MiB/niski priorytet, bez Gradle/emulatora/rzeczywistego HTTP. Kompilacja ręczna nie uruchamia KSP ani Android packaging/lint i nie zastępuje pełnego builda.

Trzy dodatkowe przypadki urządzenia obejmują restart Room z usuniętym obrazem i replay ACK, wyścig dwóch GET/backoff oraz kontekst/A→B→A. **Ich wykonanie native: NOT_RUN**; pełny Android build/lint/JVM/native aktualnych źródeł i rzeczywisty APK/API pozostają NOT_RUN. SessionController nie wywołuje jeszcze nowych metod odczytu; podłączenie GET/budżetu/sesji/UI jest następnym krokiem, bez automatycznego POST i bez zapisu posiłku.

## Walidacja poprzedniego checkpointu kolejki

Końcowe źródło `0a6667a1ee856ba27f0264f0710765e673965995`; checkpoint kolejki `95e9a180280a2aaf32ae9246fc264044f9676c34`.
**186JVM debug/201JVM validation, build obu APK/testAPK i lint0error PASS. Końcowy pełny native200/200 API35 PASS, bez pominięć.** Sześć nowych przypadków Room/plików obejmuje restart/lost ACK/usunięcie oryginału, zgodę/guest, ABA/kontekst serwera, race, uszkodzenie/backoff/ACK i migrację9→10. Migracja zachowuje wartości wszystkich23 wcześniejszych tabel, zdjęcie/dziennik i FK, dodając pustą24.tabelę. Starsze ścieżki migracji zachowują swoje asercje i dochodzą do10.

Historia pełnych prób na zachowanej bazie:

| Próba | Wynik | Wniosek i poprawka |
|---|---|---|
| 1 | 198PASS/2FAIL | Stare fixture UI ponownie używały stałego ID historii i szukały nowego produktu po nazwie. Unikalne ID, pusty dzień, cleanup własnych danych i wybór nowego produktu przez różnicę ID. |
| 2 | 199PASS/1FAIL | Test edycji racji znalazł dwa składniki o tej samej nazwie. Dodano niewidoczny testTag z ID składnika i dokładny selektor testu. |
| 3 | 199PASS/1FAIL | Dokładny składnik został wybrany, ale pole edycji nie pojawiło się po tapnięciu. Celowana próba1 zakończyła się0PASS/1FAIL i wykazała aktywny przycisk poza viewport po aktualizacji listy. Test czeka na aktywny przycisk, przewija ten dokładny element do widocznego obszaru i czeka na okno; asercje ilości/energii zachowane. |
| 4 | 200PASS/0FAIL | Po poprawce przewijania osobny test edycji1/1 PASS, potem pełny przebieg. Build/JVM/lint PASS; APK aplikacji identyczny z próbą3, zmieniono tylko testAPK. |

Zachowano asercje zachowania i logi wszystkich prób. Bez clear/uninstall/wipe. Przed trzecią kompilacją zamknięto wyłącznie własny bezczynny O1Tests35, następnie uruchomiono ten sam AVD z zachowaną bazą; przed instrumentacją sprawdzono boot oraz phone/connectivity/wifi/settings/package. Trzecia próba ma nowy APK aplikacji ze znacznikiem testowym, nie dziedziczy hash poprzedniego.

Validation0.8.14.validation/code1025/Room10 SHA256 `73be410966a879f66ba540587eb04c4a518f840e74426d508ef4dc973f75942f`.
TestAPK SHA256 `62a23387f990f39bc6e65911e56e1e1f35e2c6f310345e47e41d1ec7a3c5ec0a`. Domyślny testAPK nie zawiera drivera live; debug nie zawiera znaczników bramki. Regularna aplikacja użytkownika0.8.13/Room9 i kandydat API/CA O1-046/Room9 pozostają osobne i nie zostały zaktualizowane tym etapem. Fixture testy nie potwierdzają rzeczywistego HTTP/Gemini ani E7-R; zdalne CI i merge są odrębnymi wynikami.

## Kolejne części pełnego E7

1. Anulowanie analizy na serwerze oraz edycja propozycji do30 składników (GET/polling i podgląd są już podłączone).
2. Confirm ze stabilnymi ID/provenance, atomowy Room+outbox i jedyny zapis serwera przez kanoniczny E4 push, bez duplikatu po replay.
3. Retencja pozostałości po crash, rzeczywisty APK/API oraz E7-R i odbiór wydania.

Nie wywołano Google, nie umieszczono sekretu w APK i nie opublikowano produktu.

## Końcowy podgląd i zwykła instalacja17.10

Pierwsze zrzuty mimo223 poprawnych asercji zasłaniało okno ANR **System UI**
emulatora. Zachowano je prywatnie i nie przyjęto jako odbioru wizualnego.
Po pojedynczym wyborze widocznego Wait świeża hierarchia nie zawierała okna;
powtórzono wyłącznie trzy właściwe testy UI na identycznych APK: **3/3PASS**,
offline po przebiegu. Wszystkie trzy nowe PNG obejrzano, bez ANR/retuszu.
[Podglądy syntetyczne](../propozycje-ui/analiza-0.8.16/README.md) pokazują zgodę,
niepewną próbę i wynik przy wąskim viewport/dużym tekście.

Regularny APK0.8.16/code27 zainstalowano jako install-r na zachowanym
CodexCalories. Prywatny baseline poza Git/OneDrive przed instalacją,
po instalacji przed startem i po uruchomieniu migracji potwierdza wszystkie
stare wartości23tabel identyczne, Room9→10, FK clean i pustą nową tabelę.
SHA zainstalowanego base.apk odpowiada debug z tabeli wyżej.
Polecenie oczekiwania startu zwróciło timeout; nie ponawiano instalacji.
Późniejszy świeży UI dump potwierdził rzeczywistą aplikację, brak ANR oraz
widoczne Dodaj posiłek/Dziennik/Postępy/Profil/Ustawienia. Aplikacja otwarta
do testów ręcznych. Osobnego kandydata API/CA/Room9 nie aktualizowano.


## O1-089 — integracja PR105 z aktualnym main,20.10.2026

Rodzic PR96 został scalony jako03d776b52d769cb1f07d70dfa5acb7b697bb9ae1
po własnym8/8CI39445144500 dla1042125:170debug/185validationJVM i194native,
bez błędów/pominięć. Rzeczywiste drzewo zgodne z testowym3c14426.
PR105/head90d28c2 dołącza aktualny main zwykłym merge. Kod Android/app
pozostaje identyczny; narzędzia/CI/backend/infra pochodzą ze scalonego main,
w tym wymagane testy obu wariantów JVM. Osiem konfliktów dotyczyło tylko
dziennika; wszystkie125/190 wystąpienia historyczne i ich wiersze zachowane.

Historyczne wyniki powyżej opisują konkretne wcześniejsze APK. Nowa integracja
otrzyma własny pełny Project CI po skierowaniu istniejącego PR105 na main
i publikacji; wynik rodzica nie zastępuje jej kontroli.0.8.17/code28/Room10
nie jest instalowany nad aktualnym zwykłym0.8.23/code34/Room14. Własny
odbiór ręcznych posiłków139 i dowody O1-088 są w osobnym zależnym PR139.
Brak nowego rzeczywistego API/Gemini lub zmian używanego środowiska O3;
pełny E7/E4/recovery/KO32 pozostaje osobnym odbiorem. Szczegóły O1-089.


## O1-090 — integracja trwałych poprawek121,20.10.2026

PR105 scalony jako d27efd7114594d1ca173d950defc61629bf9ff8d po8/8CI39450871756
dla b6a229c:247debug/262validationJVM i235API35 offline, bez błędów/pominięć.
Drzewo merge29ff693f zgodne z testowymcfa05f7. PR121 dołącza ten main do
dokładnego0068232 zwykłym merge, zachowując kod Android/app. Narzędzia/CI,
backend/infra pochodzą z main. Dwa konflikty tylko dziennika rozwiązano
z zachowaniem wszystkich127/201 historycznych wystąpień i ich wierszy.
Ten etap nadal0.8.18/code29/Room10 bez migracji, bez confirm/zapisu Meal.
Historyczne wyniki powyżej dotyczą dawnych APK; własny nowy Project CI
tej integracji jest wymagany po retarget istniejącego PR121 na main.
Starszy APK nie zastępuje zwykłego0.8.23/code34/Room14. O2-046/PR137c5ac5ca
odczytane, oracle bez zmiany; liveE4/E7/KO32 i środowisko O3 osobno.
