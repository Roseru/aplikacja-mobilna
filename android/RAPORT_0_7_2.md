# Android 0.7.2 — wybór jedzenia na mniejszym ekranie

Agent 1 / O1, 11 października 2026. Gałąź `codex/android-male-ekrany`, kod `03f8678`, integracja `b81c8dc` z main `492811f`. Android versionCode 9; Room nadal 6, bez migracji. Zwykły merge E6 nie zmienił przetestowanego kodu Androida.

## Zmiana zachowania

Ekran produktów ma jedną przewijaną listę: wyszukiwanie, zakładki, typ posiłku i wyniki przesuwają się razem. Poprzedni stały nagłówek zabierał miejsce wynikom przy otwartym edytorze i klawiaturze. Użytkownik może przewinąć do innego produktu, również przed zapisaniem porcji.

Pola ilości produktu/racji, edycji składnika oraz wspólne pola liczbowe produktu/profilu mają akcję klawiatury „Gotowe”. Zamyka ona klawiaturę i kończy fokus; zapis nadal wymaga przycisku. Zmiana produktu nie dodaje posiłku. Zachowano odtwarzanie wpisanej ilości i pozycji listy po odtworzeniu aktywności.

Testy przewijają właściwy kontener przed wyszukaniem elementu lazy-list, sprawdzają ilość przed odtworzeniem i po nim oraz przewijają do podsumowania, kiedy odtworzona lista pozostaje przy edytowanym posiłku. Po dotknięciu zapisu edycji sprawdzają zamknięcie dialogu i dokładną wartość w Room. Nie dodano retry, pomijania ani zwiększenia dotychczasowych timeoutów.

## Odbiór

| Zakres | Końcowy wynik |
|---|---|
| JVM | 65 PASS, zero failures/errors/skips |
| API 35, 1080×1920, density 420, font 1.0 | 53/53 PASS, zero failures/errors/skips |
| API 35, 1080×2400, density 420, font 1.0 | 53/53 PASS, zero failures/errors/skips |
| Lint debug | 0 błędów, 26 ostrzeżeń, 1 informacja |

Krótszy ekran otrzymał pełne assembleDebug/testDebugUnitTest/lintDebug/connectedValidationAndroidTest; drugi rozmiar osobny pełny connectedValidationAndroidTest. Jeden istniejący AVD Play Store API35 ma kolejno nadpisany rozmiar, bez wipe-data. To porównanie dwóch rozmiarów, nie dwóch obrazów/hardware AVD. Testy używają osobnego pakietu `.validation`; podstawowy dziennik pozostaje zachowany. Tryb poligonowy bez sieci; konfiguracja blokuje ponowne włączenie Wi-Fi w trybie samolotowym.

Nowy scenariusz zmienia produkt przy edycji porcji, kończy wpis przez IME Done i sprawdza brak niejawnego nowego posiłku. Istniejące testy nadal weryfikują dokładne 12.123456789123, stan racji po odtworzeniu, edycję do 150 i energię 130.5, kompletność z null kcal, strefy/DST, izolację właścicieli i migracje Room.

Historia prób: bazowe 0.7.1 na krótszym ekranie dało 2/5 PASS — nieutworzony day-complete, nieutworzona racja i timeout po dodaniu produktu. Pierwsza kompilacja nowego helpera testowego miała błędny łańcuch po performImeAction (Unit); poprawiono. Pierwsze pełne próby 0.7.2 dały 52/53: edycja zapisana, lecz po odtworzeniu daily-kcal znajdował się poza skomponowaną częścią przewiniętej listy. Dopiero poprawiona kontrola kontenera i pełne końcowe przebiegi stanowią PASS; pojedynczej próby ani powtórek nie dodajemy do liczników. Nieudane CI dokumentacyjnego [PR #22](https://github.com/Roseru/aplikacja-mobilna/pull/22) [38137458797](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38137458797) dotyczy bazowego 0.7.1: pole racji po odtworzeniu miało 90 zamiast 22,5; test 0.7.2 sprawdza wartość również przed odtworzeniem.

## Aktualizacja i testy manualne

APK lokalny poza Git: `output-apk/Racje-i-kalorie-0.7.2-debug.apk`, SHA-256 `398bcee85dd2658fae3c73bb9093e257762d9a01880d0fbdbaa50c50e7f5ae6d`. Zainstalowany jako aktualizacja 0.7.1→0.7.2, applicationId `pl.roseru.kalorie`, versionCode 9. Po rzeczywistym uruchomieniu porównanie wszystkich kolumn 18 tabel Room 6 zachowało dziennik, właścicieli i całą kolejkę; foreign_key_check pusty. Prywatne kopie/raporty nie trafiają do Git. APK pozostaje debug.

1. Dodaj posiłek → wyszukaj Banan, przewiń do produktu i wpisz 120,5 g. „Gotowe” zamyka klawiaturę; dopiero „Dodaj” zapisuje posiłek.
2. W edytorze porcji przewiń listę i wybierz inny produkt. Zmiana wyboru nie powinna dopisać poprzedniej porcji.
3. Racje → wybierz zestaw, zaznacz część składników, zmień ilość, zamknij klawiaturę i zapisz. W dzienniku popraw jeden składnik, a potem uruchom aplikację ponownie.
4. Przewiń dziennik do deklaracji kompletności; sprawdź również starszy dzień, Postępy i oba motywy.

Dalszy zakres O1 to sesja PKCE/HTTP/bootstrap, trwały adapter E4/WorkManager i zgodność E5, potem E6 UI. Obecny APK nadal działa jako gość offline; nie wykonuje OIDC, HTTP ani sync. Scalenie backendu E6 i wyniki Python/CI nie są odbiorem tych funkcji w Androidzie. Review opcjonalne według O3-005; wymagane CI i istotne uwagi nadal obowiązują. Zdalny CI nowego PR wymaga osobnego odczytu dokładnego head.

Końcowy offline guard: airplane_mode_on=1, Active default network: none. Raporty obu pełnych przebiegów zachowano lokalnie oddzielnie; 53 testy obejmują ten sam zestaw na dwóch rozmiarach, nie 106 różnych scenariuszy.
