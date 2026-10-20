# Integracja kolejki Androida — O1, 19.10.2026

Najstarszy otwarty [PR61](https://github.com/Roseru/aplikacja-mobilna/pull/61)
jest skierowany na main. Jego head `3133bccb5bbdb55952420cd6a107a53fec369670`
ma8/8 SUCCESS, lecz wynik dotyczy dawnej bazy `a6e2395`. Bieżący main to
`4228ccafdf01a8936dc39bc1964f5d325504ec04`; GitHub wskazał konflikt.
Nie używamy starego CI jako dowodu aktualnej integracji.

## Przygotowanie aktualnego rodzica

W oddzielnym katalogu roboczym wykonano zwykły merge dokładnego main4228cca
do3133bcc, bez przepisania opublikowanej historii. Konflikt dotyczył tylko
dwóch fragmentów wspólnego dziennika: aktualnej tabeli i dopisanych historii.
Zachowano treść i kolejność historycznych linii wszystkich129 sekcji rodzica
oraz157 sekcji main. W O1-010 zachowano oba historyczne wiersze O2, zamiast
nadpisania wcześniejszego stanu. Aktualne wiersze O2/O3 pochodzą z main.

Całe drzewo Androida przed dopisaniem tego raportu jest identyczne z3133bcc;
zmiana nie wprowadza kodu zależnych zdjęć/AI/synchronizacji. Nowy CI wykonany
na GitHubie ma sprawdzić połączenie Android0.8.11 z aktualnym backendem,
kontraktami i infrastrukturą main. Publikacja nie wdraża nowego obrazu do
używanej instalacji O3 ani nie zmienia jej schematu24/epoki/kont.

## Kolejność zależnych PR

Stan odczytany z GitHuba przed aktualizacją rodzica:

| PR | Zakres | Gałąź docelowa | Kontrole odczytanego head |
|---|---|---|---|
|61|Nemesis0.8.11|main|8/8 SUCCESS starej bazy; potrzebny nowy CI|
|64|Lokalne zdjęcia|android-nemesis-operacje|brak pełnego Project CI|
|73|Odbiór API i późny GET|android-zdjecia-posilkow|brak Project CI; konflikt|
|96|Dostępność analizy|android-odbior-api|brak Project CI|
|105|Zlecenia zdjęć|android-zdjecia-dostepnosc|brak Project CI|
|121|Poprawki składników|android-analiza-zdjec|brak Project CI|
|122|Potwierdzenie i historia|android-poprawki-posilkow|brak Project CI|
|129|Wysyłanie Meal|android-potwierdzenie-posilku|brak Project CI|
|138|Driver replay E4|android-wysylanie-kolejki|brak Project CI|
|139|Ręczny Meal sync-v1|android-wysylanie-kolejki|brak Project CI|

W tabeli pominięto wspólny prefiks gałęzi `codex/`. PR138/139 są niezależnymi
dziećmi PR129, nie kolejnymi rodzicami dla siebie. Stan checks nie oznacza,
że nie wykonano lokalnych testów; rozróżnienie jest konieczne dla odbioru.
Aktualny workflow Project CI uruchamia pełny zestaw tylko dla PR/push do main.

Po odbiorze/scaleniu właściwego rodzica kolejny PR zmienia bazę na aktualny
main i otrzymuje własne wymagane kontrole. Nie scalamy dziecka do oczekującego
rodzica, nie omijamy jobów i nie zmieniamy workflow, aby uzyskać pozorny PASS.
Konflikty kolejnych gałęzi rozstrzyga się po sprawdzeniu ich aktualnych wejść.

## Granice odbioru

Nowy CI/push/merge są osobnymi stanami; wynik zostanie podany z rzeczywistego
run/head. Wymagane joby: contracts, quality, postgres, keycloak-pkce,
android-build, android-device, local-integration i agregator ci-required.
Brak, anulowanie lub pominięcie wymaganej kontroli nie jest sukcesem.
Przed publikacją lokalny E0 PASS:11schematów,98valid/35invalid,
18scenariuszy,729lokalnych linków i diff-check. To walidacja kontraktów
i dokumentacji, bez uruchomienia Androida/backendu lub przypisania CI main.

Rzeczywiste R2/R3 odebrały konkretny zakres starszego APK według
[raportu O2](ODBIOR_R2_R3_ORACLE_E4_O2.md). Nie potwierdzają całego Nemesis,
nowego push, drivera ani ręcznego producenta. Rzeczywiste pairing/zgody,
pełne E4/E7/KO32 i odbiór wydania nadal wymagają własnych dowodów.
Udany CI nie zostanie opisany jako ukończenie tych etapów.

Podczas gry właściciela nie uruchomiono lokalnego Gradle, emulatora, API lub
Gemini. Aktualizacja kodu źródłowego istniejącego PR i zdalne CI nie zmieniają
zainstalowanej aplikacji, prywatnego dziennika, serwera lub ustawień komputera.

## O1-084 — odebrany CI rodzica i integracja zdjęć, 20.10.2026

[CI39330194338](https://github.com/Roseru/aplikacja-mobilna/actions/runs/39330194338)
dla head `7b302e6cad8e10f8cfe2ab3286f7b15487c64ef4` zakończył się ośmioma
SUCCESS. Odczytane podsumowania JUnit:165JVM i179API35 offline,
failures/skipped0; lint0error/29warning/1info. Pozostałe wymagane joby
contracts, quality, postgres, keycloak-pkce, local-integration i agregator
ci-required mają własny sukces. To obecny wynik rodzica0.8.11, nie dzieci.

Przed merge ponownie sprawdzono dokładny head/main4228cca, clean mergeable
oraz reviews/issue/inline0. [PR61](https://github.com/Roseru/aplikacja-mobilna/pull/61)
scalono zwykłym merge jako `7dd8fa36d4ecb599c3403f548d85aa7187950bcd`.
Drzewo źródeł `de95e14b3aeca90060982e905a8aac58e190a862` jest identyczne
z testowym merge `4220990782f535c9ada5b284fa0f794e67e7f68b`.
Osobny push CI nowego main jest odbierany oddzielnie; sukces PR nie jest
deklaracją jego ukończenia. Historyczne129/157 sekcji to unikalne nagłówki;
ponowny guard potwierdził wszystkie130/158 wystąpień obu źródeł, również
powtórzonego starego O1-017. Żadnego z nich nie usunięto.

Następny [PR64](https://github.com/Roseru/aplikacja-mobilna/pull/64),
dotychczasowy head `fe8553fd2ae18b45f80311b5c1498c32a295dfbb`, otrzymał
ten scalony main przez zwykły merge. Tylko dziennik wymagał rozwiązania
dwóch konfliktów; porównanie każdego historycznego wystąpienia potwierdziło
zachowanie164/144 sekcji rodziców. Kod Androida jest identyczny z fe8553f,
poza dopiskami raportów. PR64 jest kierowany na main i po publikacji ma
uzyskać własne osiem wymaganych kontroli. Dalszych dzieci73–139 nie dodano.

Odczytano nowe [O2-045 i instrukcję PR137/head2a8dd57](https://github.com/Roseru/aplikacja-mobilna/blob/2a8dd57bbb574be9496676e878d65e1f6586c8d3/docs/integracja/PRZYGOTOWANIE_REPLAY_E4_O3.md).
Plan przyszłego E4 ma powstać przed C0 z dokładnych utrwalonych bajtów
koperty O1; hash koperty, hash operacji i oczekiwana treść posiłku są różnymi
dowodami. C1 ma być zgodne z uprzednio przygotowanym payloadem, nie tylko C2.
Nie przeniesiono niescalonego kodu O2/O3. Driver138 i ręczny producent139
nadal wymagają integracji oraz własnej pełnej kwalifikacji, potem niezmiennego
APK/drivera/manifestu i osobnego uzgodnionego okna. Nowa próba E4 NOT_RUN;
bez aktywacji API/relay/Gemini, migracji używanego schema24 lub zmian epoki.

Kontrole integracji PR64 przed publikacją: E0 PASS11schematów/98valid/
35invalid/18scenariuszy/737linków i diff-check. Kod backend/infra/tools/CI
jest identyczny z main7dd8fa3, a kod Androida z fe8553f. Liczności E0 dotyczą
dokumentacji i kontraktów; nie zastępują wymaganego nowego Project CI.

## O1-085 — zdjęcia scalone, dowód późnego GET skierowany do CI, 20.10.2026

Własny [push CI main po PR61](https://github.com/Roseru/aplikacja-mobilna/actions/runs/39416170478)
dla7dd8fa3 zakończył się8/8SUCCESS. [PR64](https://github.com/Roseru/aplikacja-mobilna/pull/64)
ma także własny [CI39416910290](https://github.com/Roseru/aplikacja-mobilna/actions/runs/39416910290)
head940a21deb9e47ecb6058b7d8636525d3b387c588 z ośmioma sukcesami.
Z rzeczywistych podsumowań:165JVM i188API35 offline, failures/skipped0,
lint0error/29warning/1info. Nie są to liczności starego rodzica179.
Przy świeżym main7dd8fa3, clean mergeable oraz reviews/issue/inline0 scalono
PR64 jako `79dc7d931547c1b74061606342e5a8112649d236`. Drzewo
`872359a560040ee543a57bec7f02371e964960d3` jest identyczne z przetestowanym
merge1b525140518e5d2242b83b2a382273bc3a8ab2ca. Push CI nowego main jest odrębny.

Kolejny [PR73](https://github.com/Roseru/aplikacja-mobilna/pull/73), poprzedni
head0228ba40d3eb4ec77cc12897793d4e5601881529, otrzymał main79dc7d9 przez
zwykły merge. Dwa konflikty dotyczą tylko dziennika; wszystkie108/179
historyczne wystąpienia sekcji obu rodziców zachowano. Kod Androida jest
identyczny z0228ba4 oraz z e319e53130020b3bbcdb50588ef4a2205a241118,
źródłem rzeczywistej próby R2/R3. Backend/infra/tools/CI pozostają kodem main.
Dalszych dzieci96–139 nie dołączono, API/relay/Gemini nie uruchamiano.

Odczytano [uwagę O2](https://github.com/Roseru/aplikacja-mobilna/pull/73#issuecomment-6187457680).
Dowód wymaga ukończonego DTO tego samego zatrzymanego wyniku, odrzucenia
przez istniejący guard po logout i zachowania gościa. Kod PR73 ma osobne
markery dto_parsed/stale_owner_rejected i wymaga kolejno sześciu markerów, a R2
z19.10 faktycznie zaliczył1PASS/0FAIL/0SKIP. [R2](ODBIOR_APK_API_O1_R2_20261019.md)
i [R3](ODBIOR_APK_API_O1_R3_20261019.md) włączono jako dokładne kopie raportów
z a41a5cb558b39ee2adde29d731fee60eba07bf8f/PR129, bez reszty gałęzi.
[O2 odebrał ten ograniczony zakres](ODBIOR_R2_R3_ORACLE_E4_O2.md).
R1FAIL i pośredni R2SKIP zachowano; nie dopisujemy nowego livePASS w tej zmianie.
Pełne pairing/Nemesis/E4/E7/recovery/KO32 wymagają osobnych odbiorów.

PR73 ma być skierowany na main i otrzymać własne osiem wymaganych kontroli
dokładnego nowego head. Lokalny runtime nie został uruchomiony podczas gry
właściciela; nie instalowano APK i nie zmieniano lokalnego dziennika.

Kontrole przed publikacją PR73: E0 PASS11schematów/98valid/35invalid/
18scenariuszy/753linków i diff-check. Obie kopie R2/R3 zachowują dokładne
bajty źródła a41a5cb; to kontrola dokumentacji i kontraktów, bez nowej próby API.

## O1-086 — wymagane testy JVM obu wariantów, 20.10.2026

Odczyt CI39437485519/head7ad8532 wykazał165JVM debug, ale istniejący skrypt
i workflow nie wykonywały testValidationUnitTest.15 testów receipt/gate/proof
z src/testValidation pozostawało poza tym wynikiem. Nie przypisujemy165PASS
debug do całego nowego kodu obserwacji. R2/R3 zachowują swój rzeczywisty odbiór;
zmiana domyka automatyczne testy regresji i wymaga własnego nowego CI.

Skrypt wykonuje teraz oba zadania jednostkowe. Workflow sprawdza ich katalogi
niezależnie, odrzucając brak raportu, błędy i pominięcia; publikuje także
jvm-validation-summary.json oraz XML/HTML validation. Siedem obowiązkowych
jobów i agregator pozostają bez zmian. Liczności obu wariantów należy podawać
osobno, ponieważ wspólne scenariusze wykonują się dwukrotnie.

Regresja powłoki daje poprawny JUnit debug, a atrapa Gradle zwraca błąd29
wyłącznie przy uruchomieniu testów validation. Nowy wrapper odmawia i zapisuje
diagnostykę. Ten sam przypadek na starym wrapperze zwraca0, odtwarzając lukę.
Lokalnie2testy przenośne PASS, przypadek regresji pod Git Bash PASS,
kontrprzykład starego skryptu odtworzony, bash -n PASS. To nie wykonanie
Gradle lub pełnego Linux CI; te wyniki będą odebrane z nowego run/head.
