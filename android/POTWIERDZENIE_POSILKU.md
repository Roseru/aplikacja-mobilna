# Potwierdzenie poprawionego posiłku — Android

Agent 1 / O1, 17 października 2026. Gałąź `codex/android-potwierdzenie-posilku`,
zależna od dokładnego head `0068232d80c0e33b0b33bf15e86cad2174774707`
/ [PR121](https://github.com/Roseru/aplikacja-mobilna/pull/121).
Kontrakt: [integracja E7](../docs/e7/INTEGRACJA_O1.md),
[server confirm](../backend/src/calorie_app/modules/ai/decisions.py),
[ai.schema](../contracts/schemas/ai.schema.json).

## Dostarczony fundament

Pełna decyzja przechowuje klucz UUID, analizę, rewizję propozycji, rewizję
poprawek i całe kanoniczne żądanie, z niezmiennymi meal_id/item_id.
Własny produkt nie jest publikowany automatycznie; aktualny edytor wybiera
product=null, nutrition_origin=ai_estimate, drafts=[]. Zachowuje Decimal,
nullable pola, g/ml i nutrition_v1. Metadane pochodzenia AI są osobne od Meal.
Próba, odpowiedź albo rozpoznane odrzucenie nie zmieniają klucza i body.

Snapshot v4 odczytuje starsze surowe ACK oraz v1/v2/v3. Jedna decyzja zamraża
poprawki i konkurujące anulowanie. GET confirmed bez własnego ACK pozostawia
niepewne żądanie do uzgodnienia. GET cancelled zachowuje szkic i zamrożoną
intencję tylko do odczytu; nie przyjmuje późniejszego potwierdzenia posiłku.
Zweryfikowany ACK blokuje cofnięcie do starego pending i sprzeczne rozstrzygnięcie.

Odpowiedź musi zawierać dokładnie wysłane szablony i oryginalny profil,
model_version oraz listę niepewności źródłowych komponentów. Nie może podmienić
posiłku, UUID, gramatury, null na0, dopisać produktu lub własnego pola.
Duplikaty kluczy JSON, złe typy, nadmierny rozmiar lub zagnieżdżenie są odrzucane.
Wyjątki i toString nie zawierają prywatnego posiłku lub odpowiedzi serwera.

PhotoAnalysisStore przygotowuje decyzję/odpowiedź poza blokadą sesji i Room.
DB-only CAS dla intencji, próby i odrzucenia zachowuje Retry-After i wymaga
właściciela, kontekstu, lease oraz identycznego poprzedniego wiersza.
PreparedPhotoConfirmationReceipt jest osobnym typem: **nie ma samodzielnej
metody zapisującej ACK bez posiłku/outbox/provenance**. To zabezpieczenie przed
podłączeniem niepełnej ścieżki do SessionController.

## Granica etapu i dalsza implementacja

HTTP confirm i przycisk SessionController/UI nie są jeszcze podłączone.
Nie zapisano Meal, ProductDraft ani outbox i nie wysłano synchronizacji.
Room pozostaje10, bez migracji. Build fundamentu używa dotychczasowego numeru
0.8.18/code29 jako artefakt do walidacji; nie jest nowym wydaniem do ręcznego
instalowania. Regularny emulator zachowuje odebraną aplikację0.8.18 z PR121.

Następny wymagany krok to jedna transakcja, która zapisze dokładne zwrócone
szablony, powiązanie analizy i provenance oraz kanoniczne operacje E4.
Rejestr materializacji musi przetrwać ponowny ACK, restart i późniejszą edycję
posiłku, zachowując identyfikatory i zapobiegając odtworzeniu starego payloadu.
Istniejący lokalny outbox ma roboczy format; nie wolno wysyłać go jako sync-v1
bez poprawnej konwersji. Nowy posiłek wymaga base_revision=null. Dopiero po
trwałym lokalnym zapisie wysyłamy standardowy push i uzgadniamy jego lost ACK.

Po tej transakcji podłączymy świadome potwierdzenie w UI, dokładny retry,
pojedyncze odnowienie401, wspólny Retry-After oraz rozróżnienie409. Konflikt
propozycji/katalogu wymaga nowego pobrania i jawnej decyzji użytkownika;
nie odblokowujemy ani nie nadajemy nowego klucza automatycznie.
Konieczne są także retencja niepowiązanych plików i brakujący wizualny odbiór
dialogu edytora zgłoszony w [raporcie0.8.18](ZLECENIE_ANALIZY.md).

## Walidacja

Kod `a7bb7dde374a606e9399a205d64e7fcce69781b2`. Pełne assemble debug/validation/testAPK, **281 JVM debug,
296 JVM validation i lint0error PASS**. Wszystkie234 wejścia Androida porównano
bitowo przed i po buildzie oraz przed commitem. Wśród przypadków jest16 nowych
core: niezmienny retry, niezależny ACK fixture, podmiana posiłku/UUID/porcji,
null/0, oryginalne provenance, granice JSON, konkurujące decyzje i terminalny GET.
Fixture ConfirmRequest i ConfirmResponse przeszedł normatywny ai.schema;
dopisanie provenance do sync-v1 Meal odrzucono w obu wariantach.

**23/23 natywne Room API35 PASS**,18 wcześniejszych i5 nowych przypadków,
bez błędów i pominięć,7.864s instrumentation/12.109s wall. Brak sieci potwierdzony
przed i po; SHA zainstalowanych validation i testAPK odpowiadają artefaktom.
Sprawdzono trwałość po restarcie i usunięciu wejścia obrazu, Retry-After,
konkurencję intencji/edycji/GET, context oraz A→B→A również z nową instancją store,
przygotowanie ACK bez zapisu niepełnego dziennika i cancelled tylko do odczytu.
Pełnego250 native nie uruchamiano; poprzedni245PASS dotyczy kodu edytora6e1eac8.
Nie przypisujemy tych wcześniejszych wyników obecnemu fundamentowi.

Pierwszy pełny build zatrzymał się na siedmiu niepełnych when w testowych
atrapach po dodaniu wariantu Confirm. Dodano jawne odrzucenie nieoczekiwanego
Confirm w tych scenariuszach anulowania. Pierwszy log i źródła zachowano;
ponowny pełny build zakończył się sukcesem7m26s. Po przeglądzie zabezpieczono
również odmowę po GETconfirmed bez własnego ACK i captured lease w przygotowanym
zapisie; wynik281/296 obejmuje te finalne zmiany. Wcześniejszy110lite ich nie dowodzi.

| Wewnętrzny artefakt fundamentu, kod a7bb7dd | SHA-256 |
|---|---|
| Debug,0.8.18/code29 | `7a4124f7c58472c949b1119efde94f957f2bb5de3c8c97e0d6187365395eacae` |
| Validation,0.8.18.validation/code1029 | `d1801e3b12fdea6c1d4a1e64886540ea366d667428bb6b75bb71b8870398c54b` |
| Domyślny testAPK, bez drivera live | `f468f5f7f75df2df7115b5eb0feda4846540b00b7902f72e732619f8bc17139f` |


Rzeczywiste HTTP confirm, standardowy push, Gemini, E7-R, pełne KO32 i wydanie
pozostają **NOT_RUN/NOT_CONNECTED**. Testy z fixture nie są odbiorem API lub AI.

## Kandydat do próby APK/API z O3

17.10 sprawdzono fizyczną obecność i pełne SHA obydwu oryginalnych plików:
źródło `e319e53130020b3bbcdb50588ef4a2205a241118`,
0.8.12.validation/code1023/Room9, APK
`89164efd5199c8e1329f4fc833107a4045d034533ded6ef0e93f00996c50efcb`,
opt-in driver `91b788998c3aa20b928e65e3f4d63a5ff3ad9048cc3de8c70f5ba8b86ecc231f`.
To osobny, zgodny z wcześniejszą próbą zestaw. Nie zastępujemy go buildem Room10
ani obcym signerem APK C2 od O3. Dane A/B i CA nie wymagają ponownej dostawy.
Nowy boot/baseline Room9, świeży peer i osiągalność przed proponowanym oknem
19.10,08:00–08:10CEST nadal wymagają sprawdzenia. Nie uruchomiono relay,
nie wykonano żądania na wygasłym listenerze ani testu Google.
