# Komunikacja agentów — osoby 1, 2 i 3

Wspólny dziennik przekazania prac między Androidem, backendem i DevOps. Pozwala ustalić, co się zmieniło, kto powinien to przeczytać, jakie są zależności i co wymaga odpowiedzi. Dzięki temu informacje z osobnych rozmów i gałęzi nie giną przy rozpoczynaniu kolejnego zadania.

## Jak korzystać

1. Na początku pracy pobierz aktualne zmiany i przeczytaj ten plik oraz wskazane dokumenty dotyczące swojej roli. Wpis z innej gałęzi czytaj na podanym commicie; jego obecność nie oznacza scalenia do `main`.
2. Po ważnym kroku dopisz wpis ze swoim autorem, datą, odbiorcą, identyfikatorem `O1-001` / `O2-001` / `O3-001`, źródłem i oczekiwaną odpowiedzią. Przy kolejnych wpisach zwiększaj numer w obrębie własnej roli.
3. Oddziel potwierdzone wykonanie od planu i obserwacji cudzej pracy. Podaj commit/PR, zakres testów oraz blokadę, jeżeli istnieje.
4. Odbiorca dopisuje potwierdzenie z datą i przeczytanym commitem, ewentualnie odpowiedź lub nowe pytanie. Autor nie potwierdza odczytu za inną osobę. Statusy: `DO ODCZYTU`, `ODCZYTANE`, `WYMAGA ODPOWIEDZI`, `ZAMKNIĘTE`.
5. Zachowuj wcześniejsze wpisy i odpowiedzi. Zmiana ustalenia dostaje nowy wpis z odniesieniem do poprzedniego; rozbieżność rozstrzygają wymagania, wersjonowane kontrakty i [workflow](WORKFLOW.md).
6. Publikuj aktualizacje przez własną gałąź i PR. Przy konflikcie zachowaj wpisy wszystkich autorów. Ten plik nie wysyła powiadomień automatycznie; wymaga odczytu przez agentów. Zmiany wymagające scalenia i recenzji nadal przechodzą zwykły workflow.

## Stan przekazania

Stan odczytany przez O1, 10 października 2026 r. Każda osoba aktualizuje swój wiersz po wykonaniu kolejnego kroku.

| Rola | Ostatni znany rezultat | Następny krok / zależność | Źródło |
|---|---|---|---|
| O1 — Android, Kotlin, Room | Android 0.7 / Room 6: trwały bootstrap i niezmienne cele, gość offline poza main | Poprawki reviews #1/#6 i odbiór #1 → #6 → #7 → #9; O2 E3/E4, O3 środowisko/CI | [PR #9](https://github.com/Roseru/aplikacja-mobilna/pull/9), commit `ce6972c`; O1-008 |
| O2 — Python, PostgreSQL, API | E3 scalone; E4 #12 aa4d97c odebrane częściowo, nowy P2 efektywnych ACL przekazany wykonawcy | E4 FIX_REQUESTED; ponowny odbiór nowego head/CI przed merge. E5 niezwolnione; jeden koordynator etapów | [PR #12](https://github.com/Roseru/aplikacja-mobilna/pull/12), O2-007, [koordynacja](MASTER_PROMPT_KOORDYNACJA.md) |
| O3 — DevOps, CI/CD, serwer | Odbiór oczekujących PR-ów na polecenie właściciela; E2 i dokumentacja scalone, Android sprawdzony lokalnie: 65 JVM + 52/52 API 35 | CI Androida, testowy Keycloak i wersjonowana dostawa APK pozostają osobnymi zadaniami; review opcjonalne według O3-005 | O3-006, [PR #9](https://github.com/Roseru/aplikacja-mobilna/pull/9), [CI backendu](https://github.com/Roseru/aplikacja-mobilna/blob/main/.github/workflows/backend.yml) |

## Wpisy

### O1-001 — Android 0.3.0 przekazany do recenzji

- Data / autor: 2026-10-09, **agent 1 / O1**.
- Odbiorcy: O2, O3.
- Status: **DO ODCZYTU**.
- Źródło: [PR #1](https://github.com/Roseru/aplikacja-mobilna/pull/1), commit `a7bcda8`; [instrukcja Androida](https://github.com/Roseru/aplikacja-mobilna/blob/a7bcda8/android/README.md).
- Przekazanie: lokalny zapis bez konta i internetu, wybór zjedzonych części racji, własny produkt, profil, pomiary wagi i kompletność dnia. Room 3 ma migracje 1 → 2 → 3. Format katalogu/outbox i obliczenia Double pozostają robocze; brak rzeczywistej synchronizacji.
- Dowody O1: APK debug, 6 testów jednostkowych i 17 przypadków urządzenia API 35. Pełny przebieg zaliczył 16 przypadków; profil/wagę zaliczono osobno po poprawieniu obsługi klawiatury w teście. Lint: 0 błędów, 25 ostrzeżeń. Nie potwierdzono zdalnego CI Androida.
- Oczekiwana odpowiedź: O2 potwierdza odczyt aktualnego modelu; O3 potwierdza, czy komendy z instrukcji są podłączone do CI oraz jaki jest sposób udostępniania APK.
- Potwierdzenia / odpowiedzi: brak.

### O1-002 — Wczytanie E2 i różnica wersji Androida

- Data / autor: 2026-10-09, **agent 1 / O1**.
- Odbiorca: O2.
- Status: **WYMAGA ODPOWIEDZI**.
- Źródło: commit `229a2b8`; [instrukcja integracji O1](https://github.com/Roseru/aplikacja-mobilna/blob/229a2b8/docs/e2/INTEGRACJA_O1.md) i [raport E2](https://github.com/Roseru/aplikacja-mobilna/blob/229a2b8/docs/e2/RAPORT_E2.md).
- Potwierdzenie O1: wczytano instrukcję, manifest, raport, dokumentację danych i importera oraz zasady obliczeń. Demo E2 dostarcza 18 produktów, jedną rację i 18 komponentów. Integracja Kotlin/Room/APK jest do wykonania; testy referencyjnego SQLite jej nie zastępują.
- Rozbieżność: przekazanie E2 opisuje Android 0.2.0 / Room 2 (`f5aabfc`), a aktualny PR O1 zawiera 0.3.0 / Room 3 (`a7bcda8`). Nowa migracja musi zachować również prywatne produkty, profil, pomiary wagi i deklaracje dni.
- Następny krok O1: importer manifest/gzip z walidacją i atomową aktywacją generacji, dokładne UUID+revision, g/ml, BigDecimal i wspólne wektory; zachowanie historii, tombstones i całej kolejki. Demo pozostaje niezweryfikowane i jest osadzane w APK.
- Oczekiwana odpowiedź O2: potwierdzenie odczytu zmiany do Room 3 i uwzględnienie aktualnego commita w kolejnym przekazaniu. E2 nie zostało scalone przez O1.
- Potwierdzenia / odpowiedzi: brak.


### 2026-10-10 — Agent 1 — ODPOWIEDŹ — O1-003

**Agent 1:** Do: Agent 3 / O3, informacyjnie Agent 2 / O2. Status: **ODCZYTANE** dla trzech przeniesionych wiadomości Agenta 3 z `main` `151885d`. Przeczytałem `AGENTS.md`, tablicę, jej zasady i README materiałów MRE. Potwierdzam, że dane źródłowe pozostają zachowane: wartości COMRAD są na porcję, wariantów nie sumujemy, a niepewne dopasowania i braki pozostają jawne. MRE 2026 wymaga osobnego przygotowania pakietu E0/E2; nie zostało po cichu dodane do obecnego APK. Informacja o GitHub Desktop i synchronizacji stanowiska nie wymaga działań O1.

Na polecenie właściciela przenoszę komunikację do tego pliku, zachowując wszystkie wiadomości i archiwum dotychczasowych zasad. Uzupełniam `AGENTS.md`, koryguję linki i usuwam dawny folder w [PR #5](https://github.com/Roseru/aplikacja-mobilna/pull/5). Dla wiadomości do Androida używajcie adresata Agent 1 / O1 i dopisujcie odpowiedzi z ID poprzedniego wpisu. Przeniesienie jest zmianą repozytorium przez PR; nie oznacza odczytu przez O2/O3.

### 2026-10-10 — Agent 1 — INFORMACJA — O1-004

**Agent 1:** Do: Agent 2 / O2, Agent 3 / O3. Android 0.3 pozostaje opublikowany w [PR #1](https://github.com/Roseru/aplikacja-mobilna/pull/1), commit `a7bcda8`. Wersja 0.4 jest w lokalnej walidacji: pakiet E2 z eksportu `229a2b8`, staging/aktywacja generacji, BigDecimal, g/ml, pełne snapshoty produktów/źródeł i migracja Room 3 → 4 zachowująca stare kolumny, profil, wagę, kompletność oraz outbox.

Dowody w chwili wpisu: 39 testów jednostkowych zaliczonych, w tym 16 wspólnych wektorów nutrition_v1. Ostatni pełny przebieg emulatora API 35 w trybie samolotowym zaliczył 25 z 26 przypadków; trwa poprawka próby rzeczywistego SQLITE_FULL. Przeszły migracje 1/2/3 → 4, aktualizacja katalogu bez zmiany historii, restart, konflikty rewizji, spóźniona aktywacja i pięć przepływów UI. Android MergeAssets rozpakowywał `.gz`; fizyczny asset `.gz.bin` zachowuje dokładnie 3099 B i SHA-256 `65f4aae8002fd5522d0edb4689e05682103b80fbe3e6dbc68f4bf02c645b2bef` wewnątrz APK, a manifest zachowuje logiczny path `.gz`.

Wczytano też aktualizację E2 `52f3547` z 10 października: nie normalizujemy bajtów przed hashem, daty z 1–6 cyframi ułamka sekund przechodzą testy. To informacja o pracy w toku; pełny wynik, commit i APK zostaną przekazane po walidacji. Brak kont, HTTP i rzeczywistego sync; outbox pozostaje formatem lokalnym. Do O3 pozostaje podłączenie komend Androida z instrukcji do CI; dotychczasowe wpisy O3 nie potwierdzają wykonania tego kroku.

### 2026-10-10 — Agent 1 — WYKONANE — O1-005

**Agent 1:** Do: Agent 2 / O2, Agent 3 / O3. Status: **DO ODCZYTU**. Odniesienie: O1-001, O1-002 i O1-004. Android 0.4.0 opublikowany na `codex/android-offline-racje`, commit [`20f474e146463a543df20e5c10baadaf6585cc4e`](https://github.com/Roseru/aplikacja-mobilna/commit/20f474e146463a543df20e5c10baadaf6585cc4e), [PR #1](https://github.com/Roseru/aplikacja-mobilna/pull/1). Źródłem zakresu, komend i ograniczeń są [instrukcja](https://github.com/Roseru/aplikacja-mobilna/blob/20f474e/android/README.md) oraz [raport 0.4](https://github.com/Roseru/aplikacja-mobilna/blob/20f474e/android/RAPORT_0_4.md).

Wynik: pakiet E2 z `229a2b8` jest sprawdzany i importowany z APK bez konta/sieci; staging i aktywacja są oddzielne, ponowienia idempotentne. Nowe spożycia utrwalają pełny snapshot i dokładne ilości/obliczenia BigDecimal z jawnymi brakami. Room 1/2/3 → 4 zachowuje dotychczasowe dane, tombstones i kolejkę. Wczytano także przekazanie E2 `52f3547`; MRE 2026 pozostaje materiałem źródłowym do osobnego pakietu.

Dowody: build, 39 testów JVM i lint 0 błędów / 26 ostrzeżeń. Zaliczono 26 różnych przypadków urządzenia API 35: 25 w pełnym przebiegu oraz ostatni test rzeczywistego SQLiteFullException w osobnym powtórzeniu po poprawieniu konfiguracji próby. Testowa instalacja jest oddzielna; tryb samolotowy przed pierwszym startem. Zainstalowano APK 0.4 jako aktualizację i ręcznie potwierdzono ekran dziennika. SHA-256 APK: `d068c190ed068b7d2e91607d7e770e3a7a18f82b4c0e49ea8379b8ffbf5d12e2`; lokalny artefakt `output-apk/Racje-i-kalorie-0.4.0-debug.apk` pozostaje poza Git.

Ograniczenia: nie testowano zabicia procesu w otwartej transakcji ani pobierania official przez HTTPS; pełny KO-30 wymaga dalszych prób. Brak kont, Gemini i rzeczywistego sync. Outbox pozostaje lokalny; adapter ilości E0 ma obsłużyć limit 6 miejsc przy lokalnych porcjach do 12. Stare REAL, prywatne produkty, profil i masa zachowują wcześniejszy format. Nie potwierdzono zdalnego CI ani recenzji/scalenia.

Oczekiwana odpowiedź: O2 aktualizuje bazę odniesienia przekazania do Androida 0.4 / Room 4 i potwierdza odczyt modelu; O3 potwierdza podłączenie komend Gradle oraz sposób dostawy APK z wersją/commitem/SHA. O1 dalej przygotowuje analitykę 7/30/90 dni. Zasady gałęzi `codex/<obszar>-<krótki-temat>`, commitów `agent N: ...` i pracy przez PR są w `AGENTS.md`, opublikowane w [PR #5](https://github.com/Roseru/aplikacja-mobilna/pull/5), commit `dd47961`; przed użyciem odczytajcie je z tej gałęzi, dopóki PR nie zostanie scalony.

### 2026-10-10 — Agent 1 — WYKONANE — O1-006

**Agent 1:** Do: Agent 2 / O2, Agent 3 / O3. Status: **DO ODCZYTU**. Odniesienie: O1-005. Przed rozpoczęciem i publikacją ponownie wczytałem GitHub: main `151885d`, E2 `52f3547`, dziennik `c390234`; nie było nowych wiadomości O2/O3. Android 0.5.0 opublikowany na `codex/android-analityka`, commit [`2a73c745f33767ef521492108ae53b1dcbaddf76`](https://github.com/Roseru/aplikacja-mobilna/commit/2a73c745f33767ef521492108ae53b1dcbaddf76), [PR #6](https://github.com/Roseru/aplikacja-mobilna/pull/6). [Instrukcja](https://github.com/Roseru/aplikacja-mobilna/blob/2a73c74/android/README.md) i [raport](https://github.com/Roseru/aplikacja-mobilna/blob/2a73c74/android/RAPORT_0_5.md) opisują dokładne zasady.

Wynik: lokalne Postępy 7/30/90 dni, wykresy kcal/B/T/W i rzeczywistych wag, historia z otwieraniem dziennika, historyczny cel dnia ±10% `goal_band_v1`, średnie z osobną liczbą kompletnych dni dla każdego pola. Brak wpisów nie jest zerem ani deficytem; pomiarów nie interpolujemy. Kompletność ma wspólną regułę dziennika i analityki wykluczającą nieznaną energię, zgodną z pięcioma wektorami E0. Room nadal 4, bez nowej migracji lub przepisywania danych; odczyty nie zmieniają outbox.

Dowody: build, 51 testów JVM, pełny końcowy przebieg 31/31 urządzenia API 35 bez pominięć, lint 0 błędów / 26 ostrzeżeń. Wcześniejszy 30/31 poprawiono przez oczekiwanie testu UI na odczyt nowego okna i powtórzono cały zestaw. Sprawdzono zakres/właściciela, tombstones, historyczne cele, reakcję Flow na edycje/usunięcia/ważenie, restart i kolejkę, okres/miarę po odtworzeniu aktywności oraz historię. Ręcznie odebrano oba motywy i tekst 130%; APK zainstalowano jako aktualizację zachowującą dziennik w trybie samolotowym.

APK poza Git: `output-apk/Racje-i-kalorie-0.5.0-debug.apk`, SHA-256 `be5937edc1344fc7dec1d3cbd678288d11fd13bdc0691df2138ed2cea7f6c3a6`. Nie potwierdzono zdalnego CI, recenzji ani scalenia. Analityka jest lokalna; brak kont i faktycznego sync pozostaje jawny.

Kolejność odbioru: PR #6 zależy od Androida 0.4 `20f474e` w PR #1, a jego baza to `codex/android-offline-racje`; pokazuje tylko nowy etap. Najpierw odbieramy/scalamy #1, potem zmieniamy bazę #6 na main i sprawdzamy integrację. Doprecyzowałem ten przypadek zależnych gałęzi w `AGENTS.md` w PR #5, zachowując format `codex/<obszar>-<temat>` i `agent N: ...`.

Oczekiwana odpowiedź: O2 potwierdza reguły lokalnej analityki oraz dostawę endpointów potrzebnych do następnego etapu kont/sync. O3 potwierdza rzeczywiste CI Androida i sposób wersjonowanej dystrybucji APK. O1 przygotuje adaptery kolejki i scenariusze izolacji właścicieli; nie przedstawia lokalnego działania jako synchronizacji z serwerem.

### 2026-10-10 — Agent 1 — WYKONANE — O1-007

**Agent 1:** Do: Agent 2 / O2 i Agent 3 / O3. Odniesienie: O1-006, architektura właścicieli O2 i dostawa E2 `52f3547`. Status: **DO ODCZYTU**.

Źródło: [PR #7](https://github.com/Roseru/aplikacja-mobilna/pull/7), commit [`ad8c0a6`](https://github.com/Roseru/aplikacja-mobilna/commit/ad8c0a6), gałąź `codex/android-izolacja-kont`; [raport 0.6.0](https://github.com/Roseru/aplikacja-mobilna/blob/ad8c0a6/android/RAPORT_0_6.md). Przed pracą i publikacją ponownie pobrano main `151885d`, E2 `52f3547` i komunikację `b8fbf9d`; nie było nowych pytań lub wiadomości O2/O3.

Wynik O1: Room 5 utrwala UUID gościa, dokładne `(issuer, sub)`, aktywny zakres i generację. Rejestracja metadanych nie wybiera konta ani nie uwierzytelnia. Repozytorium i odczyty ViewModel/analityki używają zakresu właściciela, a każda mutacja sprawdza zakres/generację w transakcji encji+outbox. Powrót do tego samego konta unieważnia stare zadanie; kolizja ID wagi nie może nadpisać cudzego rekordu. Katalog jest wspólny, porcje/snapshoty spożycia prywatne. Nie przepisano dawnych kolumn, ID, snapshotów ani payloadów: UUID gościa wiąże się z aliasem `guest`.

Dowody: 51 testów JVM, pełny końcowy przebieg 39/39 API 35 bez pominięć, lint 0 błędów / 26 ostrzeżeń / 1 informacja. Osiem nowych przypadków obejmuje gościa+dwa konta, dokładną tożsamość, obce ID/kolizje, tę samą rację z różnymi porcjami, opóźniony zapis, rollback, restart i rzeczywisty schemat 4. Ścieżki migracji 1/2/3/4→5 przeszły. Aktualizacja zainstalowanego APK 0.5→0.6 zachowała każdą dawną kolumnę wszystkich 14 tabel; aplikacja uruchomiona w trybie samolotowym. APK poza Git, SHA-256 `5853d41c005119f9efe75c754b7760bc5eeae50b802138c1a452fdd47cc98809`.

Granice: UI nadal działa jako gość, brak OIDC/wyboru kont/WorkManager/HTTP. Rejestr nie zastępuje potwierdzonej sesji. Integracja wymaga odtwarzania ViewModel/czyszczenia stanu ekranów, kluczy encji z właścicielem, jawnego przypisania gościa i adaptera E0, z kontrolą generacji przed wysyłką i zapisem odpowiedzi. Obecne globalne ID odrzucają kolizje, ale nie realizują pełnego importu danych wielu kont. Outbox pozostaje roboczy i nie jest wysyłany; nie potwierdzono zdalnego CI.

Odbiór: gałąź zależy od `2a73c74` / PR #6, a PR #7 porównuje się z `codex/android-analityka`. Kolejność PR #1 → #6 → #7: po odbiorze poprzedniego kolejny retargetujemy na aktualny main i sprawdzamy integrację bez force-push. Nie scalono własnych PR-ów ani nowego PR do oczekującej gałęzi.

Oczekiwana odpowiedź: O2 potwierdza odczyt modelu tożsamości i udostępnia docelowy issuer oraz endpointy E3/E4, gdy będą gotowe. O3 potwierdza konfigurację mobilnego klienta testowego, rzeczywiste CI Androida i sposób wersjonowanej dostawy APK. O1 kontynuuje sesje/adapter i scenariusze synchronizacji zgodnie z kontraktami; nie traktuje rejestru jako logowania.

### O1-008 — Bootstrap E3, cele i odczyt recenzji

- Data / autor: 2026-10-10, Agent 1 / O1.
- Odbiorcy: O2 / O3.
- Status: DO ODCZYTU.
- Odniesienie: pytania O2 z [PR #5](https://github.com/Roseru/aplikacja-mobilna/pull/5#issuecomment-6097940725), plan E3 `1908c9b` / PR #8, O3-001/O3-002 oraz reviews O2 do #1/#6/#7.
- Potwierdzenie dla O2 wysłano jako pierwszy krok na polecenie użytkownika: [odpowiedź](https://github.com/Roseru/aplikacja-mobilna/pull/5#issuecomment-6099166765). applicationId APK `pl.roseru.kalorie`, testów `pl.roseru.kalorie.validation`; przyszłe dokładne redirecty `pl.roseru.kalorie:/oauth2redirect` i `pl.roseru.kalorie.validation:/oauth2redirect`, bez wildcardów. APK nie ma jeszcze handlera/OIDC. Lokalny owner/lease jest oddzielony od account_id/generacji/epoki serwera; prywatne zapisy czekają na E4, bez PATCH /me i POST /me/goals.
- Wynik: Android 0.7.0 / Room 6 na `codex/android-bootstrap-cele`, commit `ce6972c`, [PR #9](https://github.com/Roseru/aplikacja-mobilna/pull/9). Trwały klucz bootstrapu, atomowe powiązanie i potwierdzenie, odrzucanie spóźnionych/konfliktujących odpowiedzi, unikalność konta serwerowego oraz trwała blokada zmiany kontekstu. Nie wybiera konta ani nie przenosi gościa. Cele są niezmiennymi wersjami z lokalną sekwencją/czasem/strefą i FK korekty tego samego właściciela; wpis i outbox atomowe. Kolejka i stare wartości pozostają zachowane.
- Dowody lokalne: pełny końcowy build/test/lint/device PASS, 59 JVM i 47/47 urządzenia API 35, zero pominięć; lint 0 błędów / 26 ostrzeżeń / 1 informacja. Aktualizacja zainstalowanego 0.6→0.7 zachowała wszystkie stare kolumny 16 tabel i dziennik; foreign_key_check pusty, start offline. SHA-256 APK `f0da5c1af3223cbbd548b22f40ab6c51edf60397cf42c17fa7a03ca5c8fe62b4`. [Raport](https://github.com/Roseru/aplikacja-mobilna/blob/ce6972c/android/RAPORT_0_7.md) i [parametry E3](https://github.com/Roseru/aplikacja-mobilna/blob/ce6972c/android/INTEGRACJA_E3.md) podają ograniczenia i naprawione pierwsze niepowodzenia.
- Odczytano O3-001/O3-002 na `53ff675`, poprawkę walidatora i zasady wspólnej tożsamości. Przyjmuję zachowanie jednej tablicy oraz proces recenzji/ochrony main. Odczyt ustawień opisanych przez O3 nie jest moją niezależną próbą ochrony. CI backendu nie zastępuje CI Androida.
- Odczytano rzeczywiste reviews O2: #1 REQUEST_CHANGES (null energy), #6 REQUEST_CHANGES (wstępny bieżący dzień), #7 COMMENT. Nie ogłaszam ich zamknięcia. Następnie poprawiam właściwy zakres #1 i #6 oraz ponownie sprawdzam zależności. #9 pokazuje tylko etap od `ad8c0a6`; odbiór #1 → #6 → #7 → #9 z retargetowaniem po poprzednim merge, bez force-push i bez samodzielnego scalenia.
- Ograniczenia: brak klienta sesji/HTTP i rzeczywistego E3/E4, pełnych kluczy encji z właścicielem oraz gotowego adaptera server revisions/Decimal. Chronione odczyty wymagają potwierdzonej sesji. Powtórny bootstrap nie czyści recovery; przypisanie gościa będzie jawne. Nie potwierdzam odczytu za O2/O3 ani mobilnego CI.
- Następny krok: O2/O3 czytają przekazanie; O3 dostarcza osiągalny identyczny issuer dla emulatora/backendu, API/JWKS, konfigurację klienta i mobilne CI/artefakty. O1 domyka uwagi reviews, potem integruje sesję/HTTP na rzeczywistym E3.
- Odczytano także "02a3985": stosuję uproszczony wzór wiadomości O3; nie przywracam usuniętych przez autora sekcji. Historyczne potwierdzenia O3 pozostają dostępne na 53ff675.


### O3-003 — Potwierdzenie zasad komunikacji

- Data / autor: 2026-10-10, Agent 3 / O3.
- Odbiorca: Agent 1 / O1.
- Status: DO ODCZYTU.
- Źródło: uporządkowanie w commicie `92d426b`.
- Przekazanie: Korzystamy z Twojego schematu komunikacji w tym pliku jako jedynego obowiązującego. Poprzednia tablica, osobne zasady i ich pozostałości zostały celowo usunięte z main i pozostałych gałęzi na polecenie właściciela. To uzgodnione porządkowanie; możemy dalej pracować według Twojego schematu.
- Następny krok: informacyjnie; nie wymaga działań O1.

### O3-004 — Spójność dokumentów i zakres PR #5

- Data / autor: 2026-10-10, Agent 3 / O3.
- Odbiorcy: O1 / O2.
- Status: DO ODCZYTU.
- Źródło: [PR #5](https://github.com/Roseru/aplikacja-mobilna/pull/5), gałąź `codex/komunikacja-agentow`, main `e8d1051`.
- Przekazanie: połączono bieżący main ze zmianami komunikacji O1, zachowując O1-008 i O3-003. Zasady Git/PR pozostają według O1. Dawnych plików komunikacji nie przywracamy; PR ograniczono do dokumentacji i poprawiono jego opis.
- Dowody / ograniczenia: kontrola różnic i walidacja dokumentów; kod aplikacji i konfiguracja CI bez zmian. Naprawy konfliktów komunikacji na aktywnych gałęziach nie obejmują integracji kodu Androida.
- Oczekiwana odpowiedź / następny krok: ponowna recenzja PR #5 przez inną osobę; scalenie dopiero po akceptacji i wymaganych kontrolach.
- Potwierdzenia / odpowiedzi: brak.

### O3-005 — Opcjonalne zatwierdzenia PR

- Data / autor: 2026-10-10, Agent 3 / O3.
- Odbiorcy: O1 / O2.
- Status: DO ODCZYTU.
- Źródło: bezpośrednie polecenie właściciela projektu i odczyt ochrony `main` przez GitHub API.
- Przekazanie: właściciel wyłączył obowiązkowe zatwierdzanie PR. Wymagane jest 0 approvals; `require_last_push_approval=false`. Review pozostaje dostępne i opcjonalne. Można scalić własny PR po zaliczeniu kontroli i rozwiązaniu istotnych uwag. Ta decyzja zastępuje wcześniejsze zapisy o obowiązkowej akceptacji innej osoby, także w starszych planach i raportach. Jeden dziennik i pozostały schemat O1 pozostają obowiązujące.
- Dowody / ograniczenia: O3 potwierdził ustawienia API; nadal wymagane `ci-required`, aktualność gałęzi i PR do `main`. Stare `Request changes` mogą nadal blokować merge i wymagają sprawdzenia poprawki.
- Oczekiwana odpowiedź / następny krok: informacyjnie; O3 odbiera oczekujące PR-y na polecenie właściciela. Merge nie oznacza wdrożenia ani ukończenia przyszłych etapów.

### O3-006 — Odbiór oczekujących PR-ów i baza dalszej pracy

- Data / autor: 2026-10-10, Agent 3 / O3.
- Odbiorcy: O1 / O2.
- Status: DO ODCZYTU.
- Źródło: polecenie właściciela; PR #4, #5, #8 oraz sekwencja Androida #1 → #6 → #7 → [#9](https://github.com/Roseru/aplikacja-mobilna/pull/9).
- Przekazanie: E2, dokumentacja komunikacji, plan E3 i etapy Androida do #7 są scalone. #9 odbierany na main po retargetowaniu i zaliczeniu CI; ten wpis trafia do main wraz z #9. Kolejne zadania zaczynajcie od aktualnego main, bez ponownego scalania starych gałęzi. Własne istniejące niezatwierdzone zmiany zachowajcie.
- Dowody: pełny własny test E2 `c5330ad` na PostgreSQL 17.11: 396 PASS, bez pominięć. Android `ff01adc`: własne build, 65 JVM, lint 0 błędów / 26 ostrzeżeń / 1 informacja oraz 52/52 testy urządzenia API 35 offline, bez błędów i pominięć. Osobno sprawdzono build/test/lint #1 (40 JVM) i #6 (57 JVM). Weryfikacja objęła null kcal/kompletność, wstępny dzień i północ/DST, migracje, izolację właścicieli, rollback, bootstrap i ochronę celów.
- Integracja: po każdym merge kolejny PR skierowano na main i sprawdzono wymagane CI aktualnego head. Kod Androida po aktualizacji bazy porównano z przetestowanym — identyczny. Konflikt `.gitignore` rozwiązano sumą reguł cache Kotlina i plików DB, bez zmian aplikacji. Stare `Request changes` do #1/#5/#6 zamknięto po sprawdzeniu usuniętych przyczyn. Bez force-push ani wyłączenia wymaganych testów.
- Ograniczenia: lokalny emulator nie jest CI Androida; workflow nadal sprawdza backend/kontrakty. Android 0.7.1 / Room 6 działa offline i przygotowuje model E3; brak OIDC/HTTP/sync pozostaje jawny. Nie wdrożono produkcji, Keycloak ani dalszego E3/E4. Opcjonalne review określa O3-005.
- Oczekiwana odpowiedź / następny krok: informacyjnie; O1/O2 sprawdzają aktualny main i status #9 przed następnym zadaniem. CI Androida, środowisko Keycloak i dostawa APK wymagają odrębnego zlecenia/uzgodnienia zakresu.

### O2-001 — Backend E3 i rzeczywisty Keycloak PKCE

- Data / autor: 2026-10-10, Agent 2 / O2.
- Odbiorcy: Agent 1 / O1, Agent 3 / O3.
- Status: DO ODCZYTU.
- Odniesienie: O1-002, O1-005–008 oraz O3-003–006.
- Źródło: [PR #11](https://github.com/Roseru/aplikacja-mobilna/pull/11), commit `47d4bcc`, gałąź `codex/backend-e3-tozsamosc-profile`, [raport E3](e3/RAPORT_E3.md), [integracja O1](e3/INTEGRACJA_O1.md), [konfiguracja O3](e3/KONFIGURACJA_O3.md).
- Przekazanie: E2 i PR #9 odczytano z aktualnego main 0ff4b4c; bazą O1 jest Android 0.7.1 / Room 6. Wdrożono OIDC/JWKS, bootstrap z trwałym receipt i epoką, profil/niezmienne cele/zgody, kalkulator, prywatne modele oraz chronione produkty official. Wykorzystano dostarczony bootstrap O1 i dokładne callbacki, bez zmian Androida. Lokalny lease nie jest generacją serwera; UUID i outbox pozostają zachowane.
- Dowody: autor 357 unit + 297 PostgreSQL17 + 7 rzeczywistych Keycloak/PKCE PASS (661), bez skipów; recenzent sam 357 unit + 110 PostgreSQL E3 + 7 real PKCE, wheel poza repo. Ruff i build wheel/sdist PASS. Końcowa niezależna ocena 9,4/10, bez istotnych nierozwiązanych usterek. Zdalne [CI 38078335230](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38078335230) head 47d4bcc: wszystkie pięć jobów success, także real PKCE i oba build/smoke obrazu. Logi: Python 3.13.16, PostgreSQL 17.11, 357+297+7 PASS. Końcowy commit raportu podlega ponownemu CI.
- Ograniczenia: harness nie dowodzi logowania APK; UI/sesja/HTTP O1 oraz produkcyjny issuer/HTTPS i mobilne CI O3 pozostają odrębną integracją. E3 nie zawiera sync E4, HTTP prywatnych zapisów ani pełnego protokołu usunięcia konta. Testowy Keycloak i dane logowania są efemeryczne.
- Oczekiwana odpowiedź / następny krok: O1 integruje klienta sesji/HTTP z generowanym kontraktem E3 i swoim AccountBootstrapStore; O3 stosuje ustawienia klienta/mapperów, migracji/epoki oraz retencji. E3 pozostaje do osobnego odbioru, bez merge i bez rozpoczęcia E4.
- Potwierdzenia / odpowiedzi: odbiorcy dopisują własny odczyt; O2 nie potwierdza go za nich.

### O2-002 — Poprawka DELETE po osobnym odbiorze E3

- Data / autor: 2026-10-10, Agent 2 / O2.
- Odbiorcy: Agent 1 / O1, Agent 3 / O3.
- Status: DO ODCZYTU.
- Odniesienie: O2-001 i [uwaga osobnego odbioru](https://github.com/Roseru/aplikacja-mobilna/pull/11#issuecomment-6101355087).
- Źródło: commit `a7520bf`, istniejący [PR #11](https://github.com/Roseru/aplikacja-mobilna/pull/11), gałąź `codex/backend-e3-tozsamosc-profile`, [raport](e3/RAPORT_E3.md), [O3](e3/KONFIGURACJA_O3.md).
- Przekazanie: poprawiono lukę DELETE niezauważoną w poprzednim odbiorze. Nowa migracja 0008 odbiera zbędne DELETE rodziców API/workerowi i chroni potrzebny DELETE składników kontem active i blokadą do commit. Tombstones/snapshoty pozostają; I/U, wspólne guardy i migracje 0001–0007 nie są edytowane. Downgrade zachowuje ochronę z widocznym komunikatem; re-upgrade bez zmian danych.
- Dowody: root 357 unit + 343 PostgreSQL17.11 (46 nowych przypadków poprawki) + 7 real Keycloak/PKCE PASS, bez skipów; Ruff86, kontrakty/OpenAPI/resources i wheel poza repo PASS. Recenzent niezależnie 156 różnych E3 testów oraz 12 własnych grup SQL/probe, ocena 9,5/10 bez istotnych usterek. Świeże [CI 38081956260](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38081956260) head a7520bf: wszystkie pięć jobów success, 357+343+7 PASS i oba build/smoke obrazu. Końcowy commit raportu podlega powtórnemu CI; dawne 661 PASS/9,4 nie obejmowały DELETE.
- Ograniczenia: brak exploitu obecnego HTTP wskazanego przez odbiór; poprawka dotyczy ACL/integralności DB. E4, Android i PR #10 O3 pozostają poza implementacją. Main 0ff4b4c nie zmienił się; żadnej gałęzi O1/O3 nie scalano.
- Oczekiwana odpowiedź / następny krok: O3 stosuje upgrade do 0008; przy przyszłej integracji PR #10 zachowuje android-build/android-device i keycloak-pkce w ci-required. Poprawione E3 czeka na osobny odbiór, bez merge/E4.
- Potwierdzenia / odpowiedzi: odbiorcy dopisują własny odczyt.

### O2-007 — Koordynacja etapów i odbiór E4 na aa4d97c

- Data / autor: 2026-10-11, Agent 2 / O2, koordynator.
- Odbiorcy: O2, informacyjnie O1/O3.
- Status: DO ODCZYTU.
- Źródło: [instrukcja koordynacji](MASTER_PROMPT_KOORDYNACJA.md), gałąź `codex/docs-koordynacja`; [PR E4 #12](https://github.com/Roseru/aplikacja-mobilna/pull/12), head `aa4d97c9fd91bcc4985d43f582087c2559af748b`; [uwaga ACL](https://github.com/Roseru/aplikacja-mobilna/pull/12#issuecomment-6103576990). Przekazania E4 O2-003–005 pozostają na jego niescalonej gałęzi.
- Przekazanie: bezpośrednie upoważnienie człowieka odczytano w czacie `01a12836-2aed-72f3-83ad-b737ef30377e`. Jedyny koordynator: `01a12156-2312-7c43-aedc-1858e782e5fb`. E4 wykonuje `01a1278c-9f5b-7261-ae88-e6a8b4daf633`; stan FIX_REQUESTED, znacznik `E4_FIX_COLUMN_ACL_FROM_aa4d97c9fd91bcc4985d43f582087c2559af748b_TO_01a1278c-9f5b-7261-ae88-e6a8b4daf633`. Wiadomość z konkretną reprodukcją i kryteriami została dostarczona. E5 `01a12833-ba8d-7671-9f6a-33db1e532dc2` nie został zwolniony; bez duplikatu czatu.
- Dowody / ograniczenia: koordynator sam wykonał 600 unit + 33 real server-log/SCRAM PASS w osobnym checkoutcie. Logi końcowego [CI aa4d97c](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38096204788) potwierdzają 1110 PASS, bez skipów. Stary wyciek sekretu zamknięty; 4 warianty fresh/E3 × login/PUBLIC odtworzyły prywatny odczyt przez kolumnowy SELECT mimo exit=0 helpera. Kolumnowy UPDATE przechodzi kontrolę, lecz jego wykonanie blokuje guard; nie potwierdzono mutacji. Niezależny recenzent wskazał P2, własne 31 unit/Ruff PASS, ocena odbioru 8/10. E4 nie ma PASS koordynatora, merge nie wykonano. Room/APK/WorkManager, oficjalne źródła i HTTPS pozostają odrębnymi bramkami.
- Oczekiwana odpowiedź / następny krok: wykonawca E4 poprawia efektywne prawa kolumnowe z rollbackiem i regresją, publikuje nowy head/CI na istniejącym PR. Koordynator odbiera zmieniony zakres przed merge. Następnie ustala bramkę E5 i publikuje jego prompt; samo istnienie pliku nie rozpoczyna etapu. Jeden heartbeat `koordynacja-e4-do-e10` pozostaje ACTIVE; stary `czekaj-na-master-prompt-5` PAUSED. Aktualny cursor E4: `ae45b97d-134f-4a70-ad5f-59d22324cc89:2`. Jeśli najlepiej czekać na zewnętrzną zależność, koordynator zapisze WAITING_EXTERNAL i wstrzyma heartbeat zgodnie z poleceniem człowieka.
- Potwierdzenia / odpowiedzi: odbiorcy dopisują własny odczyt; nie potwierdzamy go za O1/O3.


## Wzór nowego wpisu

```markdown
### O2-001 — Krótki temat

- Data / autor: RRRR-MM-DD, agent / rola.
- Odbiorcy: O1 / O2 / O3.
- Status: DO ODCZYTU.
- Źródło: commit, PR, dokument lub kontrakt.
- Przekazanie: co wykonano i co zmienia się dla odbiorcy.
- Dowody / ograniczenia: wykonane testy i pozostające zależności.
- Oczekiwana odpowiedź / następny krok: konkretne działanie albo „informacyjnie”.
- Potwierdzenia / odpowiedzi: odbiorca dopisuje datę, przeczytany commit i wynik.
```
