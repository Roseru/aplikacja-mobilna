# Android 0.8.5 — lokalny podgląd osiągnięć

12 października 2026. Agent 1 / O1. Gałąź `codex/android-osiagniecia-local`, kod `62779d2401866a3cf84c6353ab190f51eef49313`, baza main `c3009f44ca966ef6b70513e0bfb028bc0c52fcbb` po scaleniu [PR38](https://github.com/Roseru/aplikacja-mobilna/pull/38). Właściciel zaakceptował wygląd Postępów 0.8.4; ten ekran pozostaje zachowany.

## Wynik i granice

„Profil → Osiągnięcia” pokazuje cztery warunki `regularity_v1`: 10 kolejnych kompletnych dni, 10 kolejnych dni w celu ±10% historycznej wersji celu, pomiary w 4 różnych dniach w dowolnych 14 dniach i racje w 5 różnych dniach. Karty mają postęp, lokalny stan oraz rozwijane daty pierwszego spełnienia. Jasny i ciemny motyw korzystają z tej samej palety co Postępy.

Jest to **podgląd lokalny**, bez serwerowego przyznania nagród, punktów, rangi lub publikacji rankingu. Osobny panel potwierdzenia serwerowego wskazuje „Jeszcze nie pobrane”. Nie ma żądania GET /me/motivation, opt-in rankingu lub zgody Nemesis. Nie utożsamiamy lokalnego wyniku z pending/final/revoked backendu. Stan ładowania i błąd odczytu nie pokazują fikcyjnych zerowych odznak; błąd pozwala ponowić odczyt.

Wynik obejmuje całą historię tego właściciela na urządzeniu, bez ograniczenia do zakresu 7/30/90 dni. Pokazuje najlepszy historyczny postęp i pierwszy aktualnie prawidłowy zestaw dat. Korekta deklaracji, posiłku, celu lub usunięcie danych przelicza wynik i może usunąć spełnienie warunku; następny poprawny zestaw nie tworzy drugiej odznaki. Nie przechowujemy zmyślonej daty przyznania nagrody. Brak energii odbiera kompletność; brak makr nie odbiera znanej energii. Większe spożycie/deficyt nie podnosi wyniku.

Dzisiejsza seria może mieć wstępny postęp 10/10, ale nie zamknięte spełnienie. Serie używają aktualnej strefy urządzenia, tak jak lokalna analityka; jest to jawna granica lokalnego podglądu względem kanonicznego wyniku serwera. Pomiary i racje dojrzewają po północy w strefie zapisanej we wpisie, niezależnie od bieżącej daty telefonu. Odczyt reaguje na zmiany bazy oraz zegar co najwyżej co minutę; używa jednego transakcyjnego obrazu wszystkich źródeł. Baza archiwum wire E4 pozostaje osobno, bez semantycznej projekcji do dziennika.

## Room 8 i kompatybilność

Migracja 7→8 dodaje wyłącznie nullable `meal_items.rationComponentPosition`. Istniejące wiersze pozostają NULL, bez historycznego backfill z bieżącego katalogu. Starsze posiłki nadal zachowują kalorie i zwykłą kompletność, ale nie stanowią dowodu odznaki racji; ekran wyjaśnia ich liczbę.

Nowy zapis racji utrwala dodatnią pozycję wybranego składnika i ilość w chwili spożycia. Pozycje dawnego demonstracyjnego katalogu są normalizowane z indeksu 0 na pozycję 1; E2 zachowuje własną dodatnią pozycję. Edycja ilości i późniejszy katalog nie zmieniają pochodzenia. Marker jest w nowym lokalnym payloadzie outbox; wcześniejsze payloady nie są przepisywane. To lokalny format kolejki, nie ukończony adapter serwerowego sync/push.

Schemat 8 jest wyeksportowany. Aplikacja i dotychczasowe testy migracji obejmują cały łańcuch 1→8; nie zmieniono wcześniejszych migracji ani ich schematów. Sesje/właściciele nadal oddzielają prywatne dane; zmiana lease zamyka stronę poprzedniego kontekstu.

## Sprawdzenie końcowe

- **115 JVM PASS**, w tym 12 nowych przypadków: historyczne świadectwo, przerwy/korekty, wstępne dzisiaj, brak energii/makr/celu, historyczne wersje i granice ±10%, wiele wpisów jednego dnia, 14/15 dni, strefy/DST, pochodzenie racji i przyszłe daty. Zero failures/errors.
- Lint: **0 błędów / 4 dotychczasowe ostrzeżenia / 1 informacja**. Kompilacja debug oraz testów validation PASS.
- Pierwsza próba urządzenia: 3 przypadki UI i 1 rzeczywista nawigacja/odtworzenie aktywności PASS; klasa nowych testów storage nie uruchomiła się z powodu jednej niewłaściwej sygnatury JUnit (`runBlocking` zwracał wartość zamiast Unit). To była nieudana próba, nie sześć zaliczonych testów. Po poprawieniu deklaracji na `runBlocking<Unit>`: **9/9 PASS**, sześć przypadków storage plus trzy istniejące migracje od wersji 4/5/6.
- Storage obejmuje pełną historię i izolację właścicieli/tombstones, żywą korektę i restart, dojrzewanie w strefie źródła bez zmiany daty urządzenia, niezmienność markerów racji, błąd zamiast fikcyjnego zera oraz rzeczywistą migrację schematu7 z porównaniem wszystkich starych kolumn 22 tabel/FK. Odczyt nie zapisuje outbox.
- UI obejmuje jawny stan serwera i lokalny, 10/10 wstępne wobec 9 zamkniętych dni, rozwijane daty i ich zniknięcie po korekcie, ciemny ekran320dp/fontScale1,5 oraz loading/error/retry/empty. Osobny test MainActivity sprawdza „Profil → Osiągnięcia”, odtworzenie aktywności, powrót i usunięcie strony po zmianie lease bez dopisywania operacji dziennika. Nie deklarujemy próby fizycznego obrotu urządzenia.
- **Pełna regresja 117/117 testów urządzenia PASS**, zero failures/errors/skips, wraz z assembleDebug/JVM/lint. Końcowy XML został odczytany i zachowany prywatnie. Gradle odnotował 2h6m44s przy przerwanym przebiegu rozmowy; nie jest to benchmark szybkości. Powtórzone przypadki nie zwiększają liczby unikalnych testów.

API35/Android15, emulator1080×2400/density420/font1; testy wyłącznie w osobnym pakiecie validation. APK 0.8.5/code16/Room8, SHA-256 `577b98a74e659e7b6cd2ed7b5c7d4cb22409216f2115255b1325a15d74d0364d`, poza Git. Prywatny punkt odniesienia sprawdzono ponownie bezpośrednio przed install-r: wszystkie kolumny 22 tabel/5posiłków/Room7/FK bez naruszeń. Instalacja i pierwszy rzeczywisty start 0.8.5 zachowały wszystkie te wartości oraz kolejkę i archiwum, Room8/FK bez naruszeń. Nowa kolumna istniejących składników pozostała NULL. Bez clear/uninstall. Aplikację otwarto na Osiągnięciach; zrzut prywatnej aplikacji pozostaje poza Git.

## Podglądy i próba manualna

Wyłącznie syntetyczne dane testów komponentu validation, bez prywatnego dziennika lub pełnego chrome produkcyjnej aplikacji: [jasne podsumowanie](../propozycje-ui/osiagniecia-0.8.5/light-summary.png), [karty i daty](../propozycje-ui/osiagniecia-0.8.5/light-badges.png), [ciemny320dp/font150%](../propozycje-ui/osiagniecia-0.8.5/dark-large-text.png). PNG sprawdzono po sygnaturze i obejrzano wizualnie.

1. Otwórz „Profil → Osiągnięcia” offline, sprawdź cztery karty i wyraźny lokalny charakter wyniku.
2. Przy spełnionym warunku otwórz i zamknij daty; brak warunku nie powinien wymyślać dat nagrody.
3. Dzisiejszy kompletny dzień powinien być wstępny aż do zamknięcia; wyłączenie kompletności starszego dnia przelicza serię.
4. Kilka pomiarów jednego dnia liczy się raz. Starsze racje bez zapisanego markera mają zachowane wartości spożycia.
5. Wróć do Profilu/Postępów, sprawdź jasny/ciemny motyw i powiększony tekst; istniejący dziennik ma pozostać zachowany.

## Zespół i następny etap

PR38 został scalony na `c3009f4` po ośmiu success dla dokładnego `ffc3027bd4a580440ada46726ed807c19690ec5b`, [CI38215019078](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38215019078), bez reviews/inline comments. Właściciel wybrał „Zachowaj wygląd i rozwijaj osiągnięcia”. Niniejsza dostawa korzysta z finalnego przekazania E8.1+2 O2; nie przypisuje O1 wyników testów backendu.

Kolejny etap: prywatny GET /me/motivation z osobnym stanem pending/final/revoked, rewizją i aktualnością oraz unieważnianiem odpowiedzi po zmianie konta/generation/epoch. Ranking wymaga osobnego świadomego opt-in. Po walidacji Androida odczytano aktualny main7654640, O2-024/026 i finalne przekazanie E8.3-I: PR37 jest scalony, produkcyjny router jest podłączony na migracji0020. Wydanie kodu/create/accept/statystyki nadal mają zamkniętą capability do odebranego E8.4. PR39 publikuje instrukcję E8.4, nie gotowe wyniki. Zwykły merge main do własnej gałęzi zachował całą komunikację i nie zmienił żadnego pliku Androida wobec przetestowanego62779d2. Dostaw/testów backendu nie przypisujemy O1. Rzeczywisty odbiór APK/HTTPS/API pozostaje osobnym scenariuszem O1/O3.

Baza publikacji po zwykłym merge: `76546405d2c549278a9826c0223204e98698015c`. Android pozostaje identyczny z przetestowanym `62779d2401866a3cf84c6353ab190f51eef49313`. Zdalne CI własnego PR i jego scalenie mają osobny odbiór; lokalny PASS nie potwierdza zdalnych kontroli.
