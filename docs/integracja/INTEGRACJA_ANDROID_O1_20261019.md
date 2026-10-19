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
