# Android 0.8.4 — czytelniejsza analityka

12 października 2026. Agent 1 / O1. Gałąź `codex/android-analityka-wyglad`, baza main po scaleniu [PR34](https://github.com/Roseru/aplikacja-mobilna/pull/34), `ffc6ab01a0740c93369a7921f65204785c02258d`. Końcowy kod `302cb1503e6ecd9997dbeba220d2de1195583269`. To niezależny etap wyglądu Postępów; Room pozostaje w wersji7.

## Wynik

Ekran 7/30/90 dni pokazuje wyróżnioną średnią kalorii, dwa osobne wskaźniki kompletności i realizacji historycznych celów oraz wykresy kcal/B/T/W i rzeczywistych pomiarów wagi. Subtelna siatka i zaokrąglone słupki poprawiają odczyt; obrys rozróżnia dane niepełne lub wstępne od zamkniętych, kompletnych dni. Historia nadal otwiera właściwy dzień dziennika.

Wąskie ekrany i powiększona czcionka układają wskaźniki pionowo. Przełączniki makroskładników zawijają się do kolejnego wiersza i mają pełne nazwy dostępne dla czytnika ekranu. Daty mogą zawijać się wewnątrz przycisków nawigacji. Jasny i ciemny motyw korzystają z istniejącej palety aplikacji.

Obliczenia Analytics, repozytorium, profile, cele, outbox, sesja i schemat Room nie zostały zmienione. Brak wpisów nie jest zerem; brak dni możliwych do oceny nie daje fikcyjnego procentu realizacji. Dzisiejszy wynik pozostaje wstępny. Wykres wagi nie uzupełnia przerw. Raport jawnie dotyczy lokalnego dziennika; archiwum wire serwera nie jest jeszcze jego projekcją.

## Sprawdzenie

Końcowy JVM: **103 PASS**, zero failures/errors/skips. Lint poprawionych źródeł: **0 błędów / 4 ostrzeżenia / 1 informacja**. **107/107 testów urządzenia PASS**, zero failures/errors/skips, pełny build/JVM/lint/device **16m38s**. API35/Android15, 1080×2400/density420/font1, emulowane AC/StayOn/Awake; osobny pakiet validation. Aktualizacja zainstalowanej0.8.3→0.8.4 oraz pierwszy start zachowały wszystkie kolumny **22 tabel i5posiłków**, również kolejkę i archiwum; Room7/foreign_key_check bez zmian. Prywatny punkt odniesienia pobrano tuż przed install-r, bez clear/uninstall. Po wizualnym sprawdzeniu zrzutów poprawiono tylko tło syntetycznego fixture na rzeczywisty kolor background ze Scaffold; osobna końcowa próba **3/3 UI PASS**, zero failures/errors/skips, **1m23s** po korekcie tła; końcowe **3/3 PASS/1m29s** po poprawce eksportu z weryfikacją sygnatury PNG. Kod APK nie zmienił się po pełnym run. Powtórzenia nie są dodatkowymi unikalnymi testami. Nie sumujemy powtórzonego zakresu do107.

Trzy nowe testy komponentu korzystają wyłącznie z syntetycznych danych: zamknięte dni kontra dzisiejszy wynik/braki, rzeczywiste pomiary i wybór dnia; ekran320dp/fontScale1,5 w ciemnym motywie z dostępnością wszystkich kontrolek; pusty raport bez wymyślonej średniej lub oceny celu. Testowe zrzuty nie zawierają prywatnego dziennika.

Pierwsza kompilacja/JVM przeszły, lecz lint przerwał run: dwa `SuspiciousIndentation` w nowych pętlach rysowania siatki. Zmieniono konstrukcję na `forEach`, zachowując tę samą geometrię; bez suppressions, baseline albo osłabienia kontroli. Pierwszy raport zachowany prywatnie. Końcowa weryfikacja poprawionych źródeł przeszła, bez zmiany reguł Analytics lub tolerancji testów. Runner usuwa pakiet validation po próbie; pierwszy eksport po tym usunięciu odmówił odczytu. Pierwszy helper z przekierowaniem także nie zapisał PNG, ponieważ API nie uruchamiało interpretera przekierowania. Końcowy helper używa bezpośredniego screencap do stałych ścieżek emulatora i sprawdza PNG, wyłącznie gdy widoczny jest syntetyczny fixture validation. Cztery końcowe pliki odczytano i obejrzano; prywatna aplikacja nie służy do publicznych podglądów.

APK `0.8.4` / versionCode15 / Room7, SHA-256 `a5b254bbe58e580b3f895fd38c636cd1cfe8ae56762baf3f81fc4c7abdfb738f`, pozostaje poza Git. Aplikacja jest otwarta do testów manualnych. Zrzuty użytkownika i wszystkie prywatne dane pozostają poza repozytorium.

## Podglądy

Syntetyczne zrzuty komponentu, z końcowej próby na tle aplikacji (bez prywatnego dziennika i bez symulowania potwierdzonego serwera): [jasne podsumowanie](../propozycje-ui/analityka-0.8.4/light-summary.png), [wykres](../propozycje-ui/analityka-0.8.4/light-chart.png), [ciemny320dp/font150%](../propozycje-ui/analityka-0.8.4/dark-large-text.png), [zawijanie kontrolek i wykres](../propozycje-ui/analityka-0.8.4/dark-large-chart.png).

## Integracja zespołu

O1 odczytał scalony backend E8.1+2 / [PR35](https://github.com/Roseru/aplikacja-mobilna/pull/35), O2-025, [przekazanie Androida](../docs/e8/INTEGRACJA_O1_MOTYWACJA.md), normatywny schemat i przykład `motivation-final`. Stany pending/final/revoked, rewizja i świeżość zgody nie mogą zostać zastąpione lokalnym wynikiem. Ta dostawa UI nie wywołuje jeszcze motywacji/rankingu ani nie wysyła zgody. Odczytano też niescalone [PR37](https://github.com/Roseru/aplikacja-mobilna/pull/37) / head27af3a38965dd4f8ac518835604206ce0f8c4e17 i jego INTEGRACJA_O1_NEMESIS_LIFECYCLE: prywatny jednorazowy kod, pełne terms/zgody, Idempotency-Key/X-Sync-Epoch/If-Match, lease/cache oraz zamknięta bramka do E8.4. E8.3-C nie jest podłączonym produkcyjnym routerem/statystykami. Nie dołączono niescalonego kodu i nie przypisujemy O1 wyników O2.

PR34 scalono po własnym odczycie ośmiu success dla `302ffae63536e3d16cb66b6cf7178c3d32fd8dd4`, baza `2b3ac613dcd0a7950e3e14183bdd1a5d3caee7d2`, [CI38210074687](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38210074687), brak reviews/inline comments. Merge `ffc6ab0` zachowuje kod Androida0.8.3. To nie dowód CI0.8.4 ani rzeczywistego odbioru APK/API.

Następny etap O1: osiągnięcia z jawnym rozróżnieniem lokalnego postępu i potwierdzenia serwerowego, dalszy adapter E4 oraz NEMESIS po przekazaniu kontraktów lifecycle i wyników. Rzeczywisty odbiór API/TLS nadal wymaga istniejącego środowiska O3.

## Próba manualna

1. Otwórz Postępy, przełącz7/30/90, przejdź do poprzedniego okresu i wróć do dzisiaj.
2. Wybierz kcal/B/T/W i otwórz dzień z historii; sprawdź jego faktyczny dziennik.
3. Porównaj zamknięty kompletny dzień z dzisiejszym wstępnym oraz datą bez wpisów.
4. Sprawdź pomiary z dwóch różnych dni; przerwy nie powinny dostawać wymyślonej wagi.
5. Porównaj jasny i ciemny motyw oraz powiększoną czcionkę. Przyciski i pełne opisy mają pozostawać dostępne przez przewijanie.
