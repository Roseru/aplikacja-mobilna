# Zlecenie analizy zdjęcia — stan implementacji Androida

Branch `codex/android-analiza-zdjec`, [PR105](https://github.com/Roseru/aplikacja-mobilna/pull/105), zależny od PR96/merge8d96aa7.
Wejścia: [integracja O2](../docs/e7/INTEGRACJA_O1.md), [DTO](../backend/src/calorie_app/modules/ai/schemas.py) i [przykład create](../contracts/examples/e7/create-accepted.json).
Gotowe są transport i trwałe przygotowanie zlecenia. SessionController, ekran zgody/wysyłki oraz pełny przepływ wyniku pozostają do podłączenia.

## Trwała kolejka

`PhotoAnalysisStore` zachowuje jedno nierozstrzygnięte zlecenie na konto. Room10 zapisuje key/epokę, account generation/context revision, źródło zdjęcia, provider/model/notice, czas jawnej zgody, hash/rozmiar wejścia, attempted, Retry-After, blokadę i ACK. Nie zapisuje tokenu ani obrazu w BLOB. Osobna kopia przygotowanego JPEG jest prywatnym plikiem konta/operacji, niedostępnym przez Camera FileProvider. Usunięcie zdjęcia źródłowego nie usuwa wejścia do retry.

Przygotowanie wymaga jawnego accepted=true, dostępnego capabilities, konta i gotowego bootstrapu. Odczyt obrazu, hash i AtomicFile write odbywają się poza Room. Przed commit następuje ponowne sprawdzenie lease/konta/kontekstu. Błąd usuwa tylko własny niezatwierdzony plik; cancellation po commit zachowuje powiązane wejście. Zabicie procesu przed Room może pozostawić niepowiązany plik — jego sprzątanie pozostaje częścią integracji retencji.

Retry odczytuje i sprawdza zachowaną kopię, bez ponownego pobierania z galerii lub kodowania. Ten sam key/image/metadata odtwarzają te same bajty multipart po restarcie i lost ACK. B ani stary lease A nie mają dostępu do kolejki A. Powrót A wymaga aktualnego lease i zgodnego kontekstu serwera. Zmiana account ID/generacji/epoki/context revision lub recovery blokuje wysyłkę i zachowuje dane. Nigdy niewysłaną operację można jawnie odrzucić lokalnie, również po zmianie kontekstu; attempted nie oznacza pewnego braku wysyłki.

ACK jest ściśle parsowany i zapisywany atomowo. Identyczne potwierdzenie jest idempotentne; inne ID/treść nie zastępują ACK. Późny błąd lub Retry-After nie cofają przyjęcia. Kolejka nie zapisuje Meal, ProductDraft, celu ani outbox. Autoryzacja tokenu, wspólny backoff i guard operacji sieciowej wymagają jeszcze integracji. Odczyt pliku/parsowanie oraz commit trzeba rozdzielić — całego request/accept nie wolno otoczyć transakcją/mutexem SessionController.

## Transport

`PhotoHttpRequest` buduje typed create/read/cancel. Jeden multipart ma metadata JSON/consent i niezmienne image. Waliduje rozmiary, sygnaturę/MIME, UUID i wstrzyknięcie granicy; filename jest stały, bez ścieżki użytkownika. ACK create/cancel odrzucają nieznane/brakujące pola, duplikaty, nieprawidłowy UTF-8/UUID/UTC/revision/provider. Replay ACK queued nie jest bieżącym stanem zadania.

Wspólny HTTPS ma bounded JSON/no-store, bez redirects/cache/automatycznego retry. Mutacje mają key/epokę, GET ich nie dostaje. Multipart o znanej długości jest zapisywany w blokach4KiB, z cancellation/deadline między blokami; systemowy write może blokować. Callback sprawdza autoryzację przed wysyłką. Proxy429/503 zachowuje Retry-After bez parsowania HTML. Pełny decoder propozycji i polling nie są jeszcze dostarczone.

## Walidacja

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

1. SessionController: token/captured operation, wspólny backoff/401, IO poza guardem i jawne wznowienie.
2. UI notice/zgody, wybór zdjęcia, kolejka i create; brak zgody domyślnej.
3. Pełny decoder propozycji, ograniczony polling/deadline/cancel, korekty do30 składników, Decimal/null/B/T/W/g/ml i referencje katalogu.
4. Confirm ze stabilnymi ID/provenance, atomowy Room+outbox i jedyny zapis serwera przez kanoniczny E4 push, bez duplikatu po replay.
5. Retencja pozostałości po crash, rzeczywisty APK/API oraz E7-R i odbiór wydania.

Nie wywołano Google, nie umieszczono sekretu w APK i nie opublikowano produktu.
