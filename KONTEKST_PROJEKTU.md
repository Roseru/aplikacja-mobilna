# Kontekst współpracy

- Użytkownik jest osobą 1 w zespole: odpowiada za aplikację Android (Kotlin, Android Studio), interfejs, pamięć lokalną i mobilną część synchronizacji.
- Podział pracy i wymagania: `WYMAGANIA_PROJEKTOWE.md`.
- Użytkownik zaakceptował oba warianty makiet: A (ciemny) i B (jasny). Aplikacja ma oferować oba jako motywy tego samego interfejsu.
- Obecny etap: Android 0.4.0 w `android/`: dotychczasowy lokalny dziennik oraz importer E2, BigDecimal, generacje i pełne snapshoty nowych spożyć, Room 4. Katalog łącznie zawiera 33 produkty i 3 racje DEMO. Kolejka zmian jest lokalna; rzeczywista synchronizacja pozostaje do wykonania.
- Plan implementacji wysłano na GitHub jako commit `74d3d1c` z autorem `agent 1`. Użytkownik poprosił o takie oznaczenie commita.
- Szczegółowa kolejność prac: `PLAN_IMPLEMENTACJI_ANDROID.md`.
- Repozytorium projektu: https://github.com/Roseru/aplikacja-mobilna
- Użytkownik chce aktualizacji GitHuba po ważnych, przetestowanych etapach; commity podpisujemy jako `agent 1`. Zgoda obejmuje publikację kodu projektu i dokumentacji, bez sekretów, lokalnych ścieżek, cache i danych dziennika.
- Wersja Androida 0.2.0 dodaje racje wieloskładnikowe: zaznaczanie zjedzonych części, gramatura, korekty/usuwanie pojedynczego składnika i całej racji. Room 2 ma sprawdzoną migrację 1 → 2. Katalog: 15 produktów i dwa zestawy DEMO, nie rzeczywiste S-R/S-RG. Przeszło 6 testów jednostkowych i 11 testów na API 35 (test migracji powtórzony po naprawie danych testowych).
- Po aktualizacji `origin/main` do `a79b073` obowiązują dokumenty osoby 2: `docs/ARCHITEKTURA.md`, `docs/PLAN_PRAC.md`, `docs/WORKFLOW.md`. Dostępne są kontrakty E0 i fundament backendu E1. Publikujemy kod przez gałąź i PR. Docelowy importer gzip/manifest, identyfikatory UUID katalogu, generacje, Decimal/BigDecimal i sync wymagają integracji z formalnymi przykładami osoby 2; lokalny format 0.3.0 jest roboczy.
- Kod 0.2.0 opublikowano jako commit `f5aabfc` autora `agent 1` na gałęzi `codex/android-offline-racje`; PR https://github.com/Roseru/aplikacja-mobilna/pull/1 czeka na recenzję zgodnie z workflow. Nie jest jeszcze scalony do `main`. Checkout publikacyjny: katalog tymczasowy `codex-aplikacja-mobilna-d1b1632706cf4ee3820824f4b78cdccf` użytkownika; źródła robocze i APK pozostają w bieżącym workspace.
- Wersja 0.3.0 ma Room 3 i migracje 1 → 2 → 3, bez kasowania dziennika, racji, celów ani kolejki. Prywatny produkt zapisuje szkic i pierwsze spożycie w jednej transakcji. Pomiary mają korekty i znaczniki usunięcia; profil nie zmienia celu kcal. Efektywna kompletność dnia wymaga deklaracji i dodatniego, niepustego dziennika.
- Walidacja 0.3.0: APK debug i lint (0 błędów, 25 ostrzeżeń), 6 testów jednostkowych i 17 przypadków urządzenia API 35. W pełnym przebiegu przeszło 16 przypadków; profil/wagę zaliczono osobno po naprawieniu obsługi klawiatury w teście. Testy mają osobny applicationId, więc ich sprzątanie nie usuwa zwykłego dziennika. APK użytkowy: `output-apk/Racje-i-kalorie-0.3.0-debug.apk`.
- Kod 0.3.0 i dokumentację opublikowano w tym samym PR #1 jako commit `a7bcda8` autora `agent 1`; gałąź zawiera też merge aktualnego main `5cbcf67`. PR pozostaje do recenzji i scalenia przez zespół. Łącznik Code Review nie udostępnił kontroli CI bez połączenia konta; nie potwierdzono wyniku zdalnego CI, dowody lokalne są w opisie PR.
- Następna praca osoby 1: lokalna analityka 7/30/90 dni z jawnymi brakami i datowanymi celami. Konta i rzeczywisty sync wymagają gotowych endpointów oraz pełnego adaptera roboczej kolejki; importer katalogu nie zastępuje tej integracji.

## Wczytane nowości GitHub — E2, 9 października 2026

- Sprawdzono GitHub ponownie po publikacji 0.3.0. `main` nadal wskazuje `a79b073`; nowa gałąź osoby 2 `codex/e2-katalog-offline` ma commit `229a2b8bcd10948fec7a6aac58c5b8a9b1b3a49c`. W chwili odczytu nie miała PR ani kontroli CI. Nie scalono jej do Androida.
- Wczytano `docs/e2/INTEGRACJA_O1.md`, `docs/e2/RAPORT_E2.md`, dokumentację danych/importera, manifest oraz zasady obliczeń i zmian OpenAPI. Źródło przekazania: https://github.com/Roseru/aplikacja-mobilna/blob/229a2b8bcd10948fec7a6aac58c5b8a9b1b3a49c/docs/e2/INTEGRACJA_O1.md
- Dostawa dla Androida: `backend/data/demo/export/base-pl.1.json.gz` i `manifest.json`, rzeczywisty eksport PostgreSQL, 18 produktów, 1 racja, 18 komponentów, 1 źródło. UUID demo `47bdff67-e58b-5437-919b-ec00159afbc5`, release/schema/reader 1; gzip 3099 B, JSON 15691 B, SHA-256 gzip `65f4aae8002fd5522d0edb4689e05682103b80fbe3e6dbc68f4bf02c645b2bef`. Nie mieszać hasha eksportu E2 ze starszym fixture E0.
- Praca O1: BigDecimal z kanonicznych stringów i TEXT w Room; exact UUID+revision, jednostki g/ml oraz udokumentowana gęstość; pełne snapshoty i pochodzenie. Dla każdego pola osobno znana suma, liczba braków i kompletność; null nie jest zerem. Ilości składników mają pozycje 1..N i nie oznaczają automatycznego spożycia.
- Import: limity manifest 1 MiB/gzip 10 MiB/JSON 50 MiB, hash i graf/referencje, niezmienność wersji, nieaktywna generacja i atomowe przełączenie tylko na nowszy release. Błąd, restart i wyścig nie mogą usuwać aktywnego katalogu, historii ani outbox. Wspólne wektory E0 pozostają normatywne, wyniki zaokrąglamy dopiero przy prezentacji HALF_UP.
- Uwaga: instrukcja osoby 2 opiera porównanie Androida na `f5aabfc` / 0.2.0 / Room 2. Nasz aktualny stan to `a7bcda8` / 0.3.0 / Room 3. Nowa migracja musi zachować także prywatne produkty, profil, pomiary wagi i deklaracje kompletności, oprócz starych posiłków, celów, tombstones i kolejki.
- Demo S-RG-1 pozostaje `unverified`, `complete=false`; nie zastępuje dawnych zestawów A/B przez dopasowanie nazwy. Publiczne API E2 udostępnia wyłącznie official; przy samym demo lista racji jest pusta, szczegół/manifest/gzip mają 404. Demo osadzamy w APK. Chronione produkty HTTP to E3, a sync nadal jest przyszłą pracą.
- Raport O2 deklaruje 327 lokalnych testów i odbiór 9,4/10; nie wykonywano ich w tym odczycie. Importer Python/SQLite nie stanowi dowodu Room/APK. Wczytano tabelę osobnego odbioru O1: pierwszy start offline, części racji, migracja, aktualizacja/powtórzenie, uszkodzona dostawa, awarie/brak miejsca i wyścig importów.

## Wspólny plik komunikacji agentów

- Na polecenie użytkownika dodano `docs/KOMUNIKACJA_AGENTOW.md`, link w README i regułę odczytu/dopisywania w workflow. Dokument zawiera statusy trzech osób, wzór wpisu oraz O1-001 (Android 0.3) i O1-002 (odczyt E2, aktualny Room 3).
- Na początku następnej pracy wczytać aktualny wspólny dziennik i wpisy dotyczące O1; po ważnym kroku dopisać rezultat, commit/PR i zależności. Nie potwierdzać odczytu za O2/O3. Plik sam nie powiadamia ani nie uruchamia innych rozmów.
- Checkout publikacyjny przywrócono do czystej gałęzi `codex/android-offline-racje` na `a7bcda8`. Dokument komunikacji jest dostępny w osobnej gałęzi/PR; przy kolejnej aktualizacji pobrać stan `main` i zachować cudze wpisy.

## Android 0.4 i wspólne zasady — 10 października 2026

- Wczytano nowy main `151885d`, `AGENTS.md`, trzy wiadomości i zasady Agenta 3 oraz README danych MRE 2026. Dane MRE pozostają materiałami źródłowymi do osobnego przygotowania katalogu, z wartościami na porcję i jawnymi niepewnymi dopasowaniami. Zachowano je w gałęzi Androida po zwykłym merge.
- E2 przekazuje obecnie także poprawki `52f3547`; bajty eksportu demo i kontrakt Decimal są niezmienione. Daty z 1–6 cyframi ułamka sekundy pozostają w oryginalnej pisowni, a hash liczymy na gzip przed rozpakowaniem.
- Wersja 0.4 implementuje walidację manifestu/gzip/UTF-8/JSON/schematu/grafu, staging i atomową aktywację tylko nowszej generacji, niezmienność UUID+revision, g/ml i pochodzenie. Nowy snapshot spożycia utrwala produkt, ilość/jednostkę, źródła/gęstość i nutrition_v1 w TEXT. Aktualizacja katalogu nie zmienia historii ani operacji kolejki.
- Migracja Room 3 → 4 dodaje pola/tabele bez zmiany dawnych kolumn REAL. Zachowuje prywatne produkty, profil, wagę, kompletność, cele, tombstones i outbox. Stare wartości nie mają deklarowanej odzyskanej precyzji; pełny adapter dawnych typów i kolejki do API pozostaje do wykonania.
- Zaliczono 39 testów JVM, w tym wszystkie 16 wspólnych wektorów, i 26 różnych przypadków urządzenia API 35: 25 w pełnym przebiegu, rzeczywisty SQLITE_FULL osobno po poprawce próby. Pakiet w APK ma zgodny hash 65f4aae8…; fizyczne rozszerzenie .gz.bin zapobiega rozpakowaniu przez MergeAssets. Szczegóły i ograniczenia twardego przerwania procesu/KO-30 w `android/RAPORT_0_4.md`.
- `AGENTS.md` wskazuje wspólny plik i format nowych gałęzi `codex/<obszar>-<temat>` dla android/backend/devops/docs. Istniejące Android i komunikacja pozostają na swoich nazwach oraz osobnych PR #1/#5. Tożsamość jest lokalna poza publikacją; nie potwierdzamy odczytu za innych autorów.

## Aktualne miejsce komunikacji

Komunikacja odbywa się wyłącznie w `docs/KOMUNIKACJA_AGENTOW.md`, według schematu Agenta 1.
