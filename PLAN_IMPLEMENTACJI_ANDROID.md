# Plan implementacji — osoba 1: Android i pamięć lokalna

Android **0.8.10** dodaje odczyt Nemesis: listę rywalizacji, uzgodnione zasady, punkty oraz dozwolone porównania. Pending/hidden/null/zero są oddzielne, a powrót na ekran ponownie sprawdza udostępnianie. [Raport i podglądy](android/RAPORT_0_8_10.md):155 JVM/168 pełny device i końcowe72 affected osobno; Room8 bez migracji,5posiłków zachowane. Zaproszenia/accept/cancel i realny API mają dalsze odbiory.

Android **0.8.9** zagęszcza ranking zgodnie z feedbackiem: wspólny wiersz pozycji/punktów i mniejsze odstępy, z czytelnym układem przy dużym tekście. Poprawia rozróżnienie deklaracji zgody i aktywnego automatu po przekazaniu E9. [Raport i podglądy](android/RAPORT_0_8_9.md):144 JVM i18 zmienionych testów urządzenia PASS, Room8 bez migracji,22tabele/5posiłków zachowane. Nemesis, klientE9 i rzeczywisty API mają dalsze etapy.

## Aktualizacja O1 — lista rankingu0.8.8, 13 października2026

- Dostarczony live ranking:25osób/strona, rank/points/badges, cursor/410/expiry/exact retry, shared Retry-After i private preflight/fencing. Odczyt bez opt-in oraz bez zapisu peer/cursor doRoom/vault. [Raport](android/RAPORT_0_8_8.md), codex/android-ranking-lista.
- Pełny144JVM/156device PASS na92ace79; po końcowym UI14PASS, po pomiarze320dp3QA PASS. Nie sumować zestawów. Install-r/launch zachował22tabele/5posiłków. Końcowa integracja testów O3 ma oddzielne dowody.
- Następne: pairing/scopes/wyniki Nemesis, rzeczywisty API/OIDC/trust, semantyczne E4/push/ACK/import/WorkManager/KO31 i recovery/KO32. Zlecenie backenduE9 należy doO3; O1 odczytuje kontrakt, bez drugiej implementacji backendu lub aktywacjiAI.

Aktualizacja PR50: source36a3b07/test-only selektor po recreation;135JVM/147device pełnyPASS, lint0error. CI ac403a5 miało146/147 przez brak mergednode; historiaRED zachowana w raporcie/O1-023. Runtime/APK5234edb bez zmian. Nowy final-head CI oddzielnie.

## Aktualizacja O1 — świadome zgody rankingu 0.8.7, 13 października 2026

- Dostarczony ekran odczytu i decyzji; exact idempotent PUT zapisany w szyfrowanej sesji przed siecią, świeży source/revision/epoch, zachowany energy consent, konflikty i ochrona starego konta. [Raport](android/RAPORT_0_8_7.md), codex/android-ranking-zgody.
- Układ 0.8.6 po feedbacku zachowany: krótsze podsumowanie i lokalne odznaki przed serwerem. Postępy bez zmian. 135 JVM/lint/build PASS; pełny 146/147 przez datę oracle po nocnym zawieszeniu, końcowe 11 DiaryFlow PASS. Room8 i wszystkie dane 22 tabel zachowane; źródła/manifest i APK zweryfikowane osobno.
- Dołączono aktualny main z odebranym backendem E8.4/E8.5 oraz O3 workers/registry/backup/restore. Te odbiory nie zamykają O1 API/APK. Kolejne: publiczna lista rankingu, pairing/statystyki Nemesis i semantyczne E4/ACK/import/WorkManager; rzeczywisty odbiór na poprawnej konfiguracji API/OIDC/TLS.

## Aktualizacja O1 — potwierdzenie osiągnięć0.8.6, 12 października2026

- Feedback właściciela: „Zmniejsz podsumowanie, pokaż więcej odznak”. Krótsza karta, wyjaśnienia rozwijane; lokalne odznaki przed potwierdzeniem serwera. Postępy0.8.4 zachowane.
- Ukończony prywatny GET motywacji: ścisły DTO, osobne statusy/aktualność, brak cache na dysku, kontrola lease/generation/epoch/revision, odnowienie i trwały Retry-After. Odczyt nie zmienia zgody rankingu ani dziennika/outbox. [Raport0.8.6](android/RAPORT_0_8_6.md), codex/android-osiagniecia-serwer. Pełny126JVM/129device dla odczytu; końcowe18UI po feedbacku; Room8/22tabele/5posiłków zachowane.
- PR40/0.8.5 scalony a6a77fc po8success PR i8success main. Ten etap ma własny PR/CI; dowody wcześniejszego PR nie zastępują bieżącego.
- Następne: rzeczywisty prywatny odczyt APK/API w istniejącym środowisku O3; świadome zgody i publiczny ranking; semantyczny sync E4/push/ACK/import/WorkManager. Nemesis dopiero po odebranym E8.4; obecne issuance/create/accept/statistics pozostają gated.

## Aktualizacja O1 — osiągnięcia0.8.5, 12 października 2026

- Właściciel: „Zachowaj wygląd i rozwijaj osiągnięcia”. Analityka0.8.4/PR38 scalona na c3009f4 po ośmiu success exactffc3027, CI38215019078; Postępy zachowane.
- Osiągnięcia0.8.5/code16/Room8: lokalny podgląd czterech warunków całej historii, stany lokalnie spełniony/wstępny/wtrakcie, daty i korekty, bez potwierdzonych punktów/rangi/rankingu. Profil otwiera osobną stronę. [Raport i podglądy](android/RAPORT_0_8_5.md), branch codex/android-osiagniecia-local, source62779d2. 115JVM/117device PASS, lint0error; rzeczywisty install-r/launch zachował wszystkie stare kolumny22tabel/5posiłków/FK. Nowa nullable pozycja składnika racji jest utrwalana tylko przy nowym zapisie; dawnym wpisom nie dopisujemy dowodu.
- Następne: prywatny GET /me/motivation, ścisłe DTO i osobny stan pending/final/revoked z revision/as_of. Wykorzystać istniejące odnowienie sesji i bootstrap; chronić owner lease/account_generation/sync_epoch/contextRevision i spóźnione odpowiedzi. Odczyt/cache nie może publikować ranking opt-in. Ranking i afirmacja po restore pozostają osobnym świadomym krokiem.
- Nemesis: wczytano scalony PR37/E8.3-I, main7654640 i instrukcję E8.4/PR39. Router0020 jest podłączony, ale issuance/create/accept/statistics nadal zamknięte do odbioru E8.4. Android przygotuje terms/kod/zgody/retry/cache według finalnych interfejsów, bez fikcyjnego partnera lub zerowych wyników. Pełny E8.4/realHTTP/DevOps wymagają własnych odbiorów.
- Dalsze E4: semantyczna projekcja, adapter Decimal i zapisanych markerów racji, trwałe push/ACK, incremental, import/recovery i WorkManager; lokalny outbox nie jest wire DTO.

## Aktualizacja O1 — 12 października 2026

- 0.8.3 / PR34 scalony na main ffc6ab0 po ośmiu success exact302ffae/base2b3ac61; CI38210074687, brak uwag. Trwałe archiwum wire pozostaje oddzielne od semantycznej projekcji oraz kolejki.
- 0.8.4 / codex/android-analityka-wyglad: nowy wygląd Postępów7/30/90, wskaźniki/wykresy, układ320dp/font150%, jasny/ciemny motyw; obliczenia i Room7 bez zmian. 103JVM/107device PASS, końcowe3UI po poprawce fixture PASS. Aktualizacja zachowała22tabele i5posiłków. [Raport i podglądy](android/RAPORT_0_8_4.md); CI tej gałęzi będzie odczytany osobno.
- Kolejny etap implementacyjny: **osiągnięcia**, najpierw jawny lokalny postęp czterech warunków v1, następnie prywatny GET /me/motivation i osobny stan potwierdzony z rewizją/aktualnością/pending/final/revoked. Odczytano finalne przekazanie scalonego E8.1+2 / PR35 i O2-025, a nie tylko master. Ranking wymaga oddzielnego świadomego opt-in z bieżącą epoką; odczyt nie publikuje użytkownika.
- **NEMESIS**: odczytano draftPR37/head27af3a3 i INTEGRACJA_O1_NEMESIS_LIFECYCLE. Jednorazowy prywatny kod w body, pełne terms/zgody, zgoda weight_change/mean_deficit domyślnie wyłączona, Idempotency-Key/X-Sync-Epoch/If-Match i unieważnienie lease/cache. E8.3-C nie jest publicznym routerem, tworzenie/akceptacja/statystyki pozostają zamknięte do E8.4. Nie dołączono niescalonego backendu lub fikcyjnego partnera/wyniku.
- Dalsze E4: semantyczne projekcje, trwałe operacje/push/ACK, incremental, import/recovery i WorkManager. Realny APK/API/TLS pozostaje własnym odbiorem O1/O3, z istniejącego środowiska O3; nie przypisujemy sobie testów backendu lub DevOps.

Poniżej zachowano historię planu i jego wcześniejsze zależności.
## Bieżąca kolejność O1 — 11 października 2026

Właściciel potwierdził: ten etap realizuje **agent 1 / aplikacja Android**. Priorytety produktu obejmują **NEMESIS, osiągnięcia i dopracowany ekran analityki**, obok trwałego działania offline i synchronizacji. Zachowujemy zasady WF-10–12 oraz podział prac O2/O3; ranking i rywalizacja wymagają potwierdzonych wyników i zgód.

1. Domknąć 0.8.3: pełne pobieranie kopii serwera, trwałe strony/wznowienie/Room 7, kontrole sesji i kontekstu; testy, PR/CI i uruchomienie APK bez utraty lokalnych wpisów. Archiwum odpowiedzi nie zastępuje dziennika ani nie potwierdza kolejki.
2. Dopracować **analitykę**: czytelne karty podsumowań, wyróżniony bilans okresu i realizacja celu, wykresy kcal/B/T/W oraz rzeczywistych pomiarów wagi, spójny wojskowy motyw, wygodny wybór 7/30/90 dni. Zachować obliczenia i jawne braki danych; przetestować mały ekran, oba motywy, dużą czcionkę i odtworzenie stanu. Ta część może działać całkowicie offline.
3. Dodać **osiągnięcia** z postępem czterech reguł v1: 10 kompletnych dni z rzędu, 10 dni w celu, pomiary w 4 dniach/14 dni i racje w 5 dniach. Lokalny podgląd ma jawny status; potwierdzone punkty/ranga/odznaki i ich cofnięcia pochodzą z E8.1+2 O2, z rewizją i datą aktualności. Brak wpisu nie daje punktów, dzisiejszy dzień nie jest zamknięty. Ranking dopiero po świadomej, aktualnej zgodzie.
4. Kontynuować **E4**: semantyczna projekcja kopii i jawne konflikty, niezmienna materializacja outbox, pełne ACK push, inkrementalny pull, świadome przypisanie gościa, recovery i WorkManager. Zgodność z serwerem jest podstawą potwierdzonych osiągnięć i wyników rywalizacji.
5. Dostarczyć **NEMESIS** zgodnie z odebranym kontraktem E8.3/E8.4: zaproszenie → wspólne ustawienie celu/okresu/udostępniania → akceptacja → porównanie regularności i realizacji celu → wynik wstępny/ostateczny → anulowanie. Maksymalnie jedna aktywna rywalizacja, izolacja dwóch uczestników, osobne zgody; surowa waga i posiłki nie są domyślnie ujawniane. Większy deficyt nie daje lepszego wyniku. Offline widoczna jest datowana kopia, bez udawanego partnera lub serwerowego zwycięstwa.

Odczytano scalony E7/PR28 i instrukcje E8/PR33. Master E8.1+2 przewiduje `/me/motivation` i `/ranking`, ale publikacja instrukcji nie oznacza dostarczenia tych endpointów. Przed integracją odczytać rzeczywisty kontrakt i przekazanie O2; dla NEMESIS potrzebne są osobne odebrane E8.3/E8.4. O1 nie przejmuje backendu ani nie rozpoczyna zadań O2.

**Aktualizacja 0.8.2:** zaimplementowany podgląd GET me po bootstrapie, bez zmiany lokalnego profilu i celu. 87JVM/86device PASS; [raport](android/RAPORT_0_8_2.md), [kontrakt i granice](android/ODCZYT_PROFILU.md). PR31 zależy od PR26; rzeczywisty bootstrap/GET ze środowiskiem O3 pozostaje otwarty. Następnie odczyty celów i trwały adapter E4/Room/WorkManager, z jawnym przypisaniem gościa.

Data: 9 października 2026 r.

Podstawa: `WYMAGANIA_PROJEKTOWE.md` oraz zaakceptowane makiety. Użytkownik jest osobą 1 w trzyosobowym zespole. Ten dokument wyznacza kolejność implementacji; bieżący zakres kodu jest opisany w [android/README.md](android/README.md).

**Aktualizacja 0.7.2:** przewijany cały wybór produktów, IME „Gotowe” bez zapisu oraz poprawiony odbiór lazy-list po odtworzeniu. 65 JVM i osobne pełne 53/53 urządzenia na rozmiarach 1080×1920 i 1080×2400. Room nadal 6; aktualizacja APK zachowała wszystkie kolumny 18 tabel. [Raport i testy manualne](android/RAPORT_0_7_2.md). Kolejny zakres to sesja/HTTP E3.

**Postęp:** A-01–05 są zaimplementowane i sprawdzone w wersji 0.1.0. Wersja 0.2.0 dodaje lokalne racje DEMO i migrację Room 1 → 2. Wersja 0.3.0 dodaje prywatny produkt, profil, pomiary wagi i kompletność dnia oraz Room 3. Wersja 0.4.0 dodaje importer E2, BigDecimal, generacje i pełne snapshoty, z migracją Room 3 → 4. Wersja 0.5.0 dodaje lokalną analitykę 7/30/90 dni z datowanymi celami i jawnymi brakami. Wersja 0.6.0 dodaje rejestr właścicieli, prywatny zakres repozytorium i ochronę przed nieaktualnym zapisem, z migracją Room 4 → 5. Wersja 0.7.0 przygotowuje trwały bootstrap E3 i niezmienne wersje celów, z Room 5 → 6. Wersja 0.7.1 łączy poprawki recenzji: energia wszystkich składników wymagana do kompletności, wynik wstępny dzisiaj oraz odświeżanie po lokalnej północy. Pełny odbiór: 65 JVM i 52/52 urządzenia. Logowanie, przełączanie kont w UI, przypisanie gościa, rzeczywista synchronizacja i adapter dawnych danych do API pozostają do wykonania. [Instrukcja Androida](android/README.md) i raporty [0.4](android/RAPORT_0_4.md), [0.5](android/RAPORT_0_5.md), [0.6](android/RAPORT_0_6.md), [0.7](android/RAPORT_0_7.md), [0.7.1](android/RAPORT_0_7_1.md) opisują zakres oraz ograniczenia.

## 1. Od czego zaczynamy

Pierwszym wynikiem ma być **działający lokalnie dziennik z dodawaniem posiłku**, uruchamiany na emulatorze i telefonie:

1. Użytkownik otwiera aplikację bez logowania i bez internetu.
2. Widzi dziennik wybranego dnia, cel kcal i sumy B/T/W.
3. Naciska „Dodaj posiłek”, wyszukuje produkt i ustawia gramaturę.
4. Zatwierdza zapis, wraca do dziennika i widzi przeliczone wartości.
5. Po zamknięciu i ponownym uruchomieniu aplikacji wpis pozostaje.
6. Przełącza jasny/ciemny motyw bez zmiany danych.

To pierwszy odbierany fragment aplikacji. Obsługa kont, prawdziwego API i Gemini wchodzi w kolejnych etapach. Przygotowanie modelu danych i kolejki synchronizacji zaczyna się jednak już teraz.

## 2. Decyzje na start

| Obszar | Decyzja |
|---|---|
| Interfejs | Kotlin, Jetpack Compose i Material 3 |
| Motywy | Ciemny A i jasny B, wspólny układ i komponenty; ustawienia: systemowy/jasny/ciemny |
| Paleta | Stałe kolory zgodne z makietami; dynamiczne kolory systemu wyłączone w pierwszym wydaniu |
| Architektura | ViewModel, niezmienny stan ekranu, jednokierunkowy przepływ zdarzeń i repozytoria |
| Odczyt dziennika | Z lokalnej bazy Room; po integracji API nadal przez lokalne repozytorium |
| Stan i operacje | Kotlin Coroutines, Flow/StateFlow |
| Dane urządzenia | Room/SQLite dla danych strukturalnych; DataStore dla preferencji, m.in. motywu |
| Synchronizacja | Trwała kolejka w Room, później wykonywana przez WorkManager |
| Katalog startowy | Mały wersjonowany plik w zasobach aplikacji, importowany do Room |
| Organizacja kodu | Początkowo jeden moduł aplikacji z podziałem na pakiety funkcjonalne |
| Wersje SDK/bibliotek | Uzgodnione po sprawdzeniu Android Studio, JDK i SDK; przypięte w konfiguracji projektu, bez przypadkowego mieszania wersji |

Nie trzeba budować osobnych ekranów dla każdego motywu. Zmieniają się kolory i wygląd elementów; zachowanie, nawigacja i dane pozostają wspólne. Motyw wizualny i tryb poligonowy są niezależnymi ustawieniami.

Grafiki są kierunkiem wizualnym. W kodzie odtwarzamy hierarchię informacji i styl przy użyciu komponentów Compose, bez wstawiania całego obrazka jako interfejsu. Zdjęcia produktów są dodatkiem; brak miniatury nie blokuje wyboru produktu.

## 3. Pierwszy pakiet prac — dokładna kolejność

### A-01. Utworzenie i uruchomienie projektu

- Sprawdzić zainstalowane Android Studio, JDK, SDK i dostępność emulatora/telefonu.
- Utworzyć projekt Kotlin/Compose w katalogu `android/` i dodać Gradle Wrapper oraz katalog wersji zależności.
- Ustalić `applicationId` i minimalną obsługiwaną wersję Androida z zespołem przed pierwszym wydaniem.
- Dodać konfigurację `.gitignore` dla plików IDE, buildów, lokalnych ścieżek SDK i sekretów. Nie publikować `local.properties` ani klucza podpisywania.
- Uruchomić pustą aplikację oraz polecenie budowania debug z Gradle Wrapper.

**Odbiór:** projekt otwiera się w Android Studio, buduje się i uruchamia na uzgodnionym urządzeniu. Osoba 3 otrzymuje komendy potrzebne do CI.

### A-02. Wspólny wygląd i nawigacja

- Zdefiniować jasną i ciemną paletę, typografię, odstępy i kształty.
- Przygotować komponenty: bilans kcal, wskaźnik makra, wiersz posiłku, wiersz produktu, kontrolka gramatury, główny przycisk i informacja o zapisie lokalnym.
- Dodać nawigację `Dziennik → Dodaj posiłek → Dziennik` oraz proste ustawienie motywu.
- Przygotować Compose Preview obu motywów na małym i większym ekranie. Treść ma się przewijać, respektować klawiaturę i obszary systemowe.
- Przejściowe dane przykładowe służą tylko podglądowi komponentów. Następny krok podłącza rzeczywiste repozytorium Room.

**Odbiór:** oba motywy mają czytelne stany wybrania, przyciski i teksty po polsku. Zmiana motywu nie resetuje wprowadzonej gramatury.

### A-03. Lokalny model danych i obliczenia

- Utworzyć Room, DAO i repozytoria oraz wersję schematu.
- Dodać lokalnego właściciela `guest` i przygotować izolację danych przyszłych kont.
- Utworzyć encje produktu, wpisu posiłku, składnika wpisu, wersji celu i operacji kolejki.
- Każdy wpis i operacja mają UUID. Produkt ma stabilny identyfikator zgodny z przyszłym pakietem katalogu.
- Zapisywać masę i odżywcze wartości użyte w danym spożyciu, aby aktualizacja produktu nie zmieniła historii.
- Przechowywać czas, strefę i lokalną datę spożycia; nie przypisywać wpisów do dnia późniejszej synchronizacji.
- Obliczać wartości porcji według masy, sumę dnia i pozostałe kcal. Brak B/T/W jest brakiem danych, nie zerem.
- Przygotować transakcyjny zapis `wpis + operacja w kolejce`, także dla edycji i usunięcia. Na tym etapie kolejka nie wysyła żądań.

**Odbiór:** zmiana gramatury zmienia wynik, restart zachowuje wpis, usunięcie aktualizuje sumę, a zmiana produktu katalogowego nie przepisuje starego posiłku.

### A-04. Baza produktów i wybór posiłku

- Dołączyć mały katalog produktów podstawowych jako zasób aplikacji. Dane demonstracyjne oznaczyć; przed wydaniem użytkowym zastąpić je wartościami ze źródeł.
- Importować katalog tylko w razie potrzeby; ponowne uruchomienie nie tworzy duplikatów.
- Dodać wyszukiwanie lokalne, listę ostatnio używanych produktów i wybór produktu.
- Zaimplementować edytor gramatury: wpisanie liczby, przyciski zmiany, walidacja dodatniej ilości i podgląd kcal/B/T/W.
- Uzgodnić z osobą 2 precyzję i zaokrąglenia oraz jednostki. W pierwszej wersji ilości produktów są w gramach.
- Zabezpieczyć zatwierdzenie przed podwójnym zapisem wskutek szybkiego wielokrotnego naciśnięcia.
- Przycisk zatwierdzenia zapisuje do Room i wraca do dnia/posiłku, z którego użytkownik rozpoczął dodawanie.

**Odbiór:** można znaleźć produkt, wybrać ilość i dodać go do dziennika w trybie samolotowym. Wpis nie wymaga backendu.

### A-05. Dziennik dzienny na rzeczywistych danych

- Podłączyć ekran dziennika do Flow z Room, bez osobnego ręcznego przechowywania sum na ekranie.
- Dodać wybór daty, cel z datą obowiązywania, kcal spożyte/pozostałe, B/T/W i grupy posiłków.
- Obsłużyć pusty dzień, niepełne makra i przekroczenie celu. Wskaźnik postępu może kończyć się na 100%, ale tekst pokazuje rzeczywiste przekroczenie.
- Dodać edycję gramatury i usuwanie pozycji oraz lokalną zmianę celu.
- Gość widzi „Zapisano lokalnie” i informację o możliwości późniejszej synchronizacji. Konto będzie widziało liczbę faktycznie oczekujących operacji.
- Zachować czytelność przy powiększonym tekście, przewijaniu i obu motywach. Kolor nie może być jedynym nośnikiem informacji o błędzie/stanie.

**Odbiór pierwszego pakietu:** pełny przepływ z sekcji 1 działa na emulatorze/telefonie, również po restarcie i bez sieci. Dostarczamy APK debug do sprawdzenia przez użytkownika.

## 4. Następne etapy

| Etap | Zadania osoby 1 | Warunek wejścia / odbiór |
|---|---|---|
| 2. Racje i pełny tryb poligonowy | Racje/składniki, wybór zjedzonej części, ręczny produkt, lokalny profil, waga, oznaczenie dnia jako kompletnego, blokada ruchu sieciowego | Gotowy pakiet 1; 14 dni różnych operacji zachowanych offline, bez wymuszonego logowania |
| 3. Konta i synchronizacja | Klient logowania, przypisanie gościa, API, WorkManager, push/pull, konflikty, wygasła sesja, izolacja kont | Uzgodniony kontrakt i testowe API; brak duplikatów i utraty wpisów po ponowieniu lub zmianie konta |
| 4. Historia i wykresy | Historia posiłków, masa, spożycie i realizacja celu dla 7/30/90 dni; jawne braki danych | Gotowe dane lokalne; synchronizacja rozszerza historię. Część lokalną można rozpocząć równolegle z etapem 3 |
| 5. Katalog społeczności i zdjęcia | Wyszukiwanie online, szkic/publikacja produktu, oceny, aparat/galeria, zgoda, wynik Gemini i ręczne poprawki | API produktów i analizy; zapis zdjęcia offline, analiza online, brak cichego dodawania rozpoznania |
| 6. Motywacja i Nemesis | Osiągnięcia, ranga, ranking, zaproszenie/akceptacja, porównanie i zakończenie rywalizacji | Backend nalicza wyniki i sprawdza zgody; Android pokazuje wynik oraz jego aktualność |
| 7. Dopasowanie zapotrzebowania | Widok propozycji AI, uzasadnienie, decyzja użytkownika i opcjonalna automatyzacja | Backend dostarcza wersjonowane propozycje; klient nie wylicza niezależnego konkurencyjnego wyniku |
| 8. Wydanie zespołowe | Testy krytycznych przepływów, migracji i zgodności motywów; instrukcja, APK i konfiguracja środowisk | Przejście scenariuszy KO-01–17 ze specyfikacji wraz z osobami 2 i 3 |

W etapach 1–2 działa prawdziwa pamięć lokalna. Symulowane odpowiedzi sieciowe mogą pomóc w rozwoju etapu 3, ale nie są kryterium odbioru prawdziwej synchronizacji.

## 5. Co równolegle przygotowują pozostałe osoby

### Osoba 2 — backend

Najpierw dostarcza mały, stabilny kontrakt obejmujący profil, cele, katalog/pakiet oraz synchronizację. Potrzebujemy:

- OpenAPI i przykładów produktu, porcji, posiłku, celu oraz dat/stref.
- Wspólnych przykładów obliczeń i zaokrągleń, stabilnych identyfikatorów produktów i formatu pakietu.
- Struktury push/pull, kolejności zmian encji, wersji rekordów, sposobu potwierdzania operacji i rozwiązywania konfliktów.
- Zasad przypisania danych gościa, pustej pierwszej synchronizacji i odzyskania pełnego stanu przy nieważnym kursorze.
- Przykładów błędów 401/403/409/422/429 oraz środowiska z co najmniej dwoma kontami testowymi.

Osoba 1 może ukończyć pierwszy lokalny przepływ przed uruchomieniem serwera. Format synchronizacji trzeba jednak uzgodnić przed implementacją etapu 3.

### Osoba 3 — DevOps

- Przygotowuje repozytorium i GitHub Actions dla budowania Androida z Gradle Wrapper, lint oraz testów.
- Zapewnia adresy i konfigurację środowiska testowego oraz parametry klienta logowania, gdy rozpoczyna się etap 3.
- Dba o sekrety i podpisywanie wydania; osoba 1 nie wpisuje sekretów backendu/Gemini do aplikacji.
- Uzgadnia z osobą 1 publikowanie APK jako artefaktu workflow, z opisanym numerem wersji i commitem.

## 6. Proponowana struktura Androida

```text
android/
  app/src/main/
    assets/catalog/             # wersjonowany katalog startowy
    java/<pakiet>/
      core/model/               # modele i wspólne jednostki
      core/nutrition/           # obliczenia porcji i sum
      data/local/               # Room, encje, DAO, import danych
      data/preferences/         # DataStore i ustawienia motywu
      data/repository/          # repozytoria danych
      data/network/             # klient API i DTO, etap 3
      data/sync/                # kolejka, synchronizacja, Worker
      feature/diary/            # ekran, ViewModel i stan dziennika
      feature/foodselection/    # wyszukiwanie, wybór i gramatura
      feature/rations/          # etap 2
      feature/settings/         # motyw, lokalny profil i ustawienia
      ui/theme/                 # kolory, typografia, jasny/ciemny motyw
      ui/components/            # współdzielone elementy UI
      navigation/               # przejścia i argumenty ekranów
```

Nazwę pakietu ustalimy przy utworzeniu projektu. Późniejsze funkcje otrzymają własne pakiety. Klasy Room, DTO API i modele ekranów nie muszą mieć identycznego kształtu.

## 7. Kontrole pierwszej wersji

1. **Obliczenia:** część porcji, kilka składników, brak makr, sumowanie przed zaokrągleniem, cel przekroczony i niepoprawna gramatura.
2. **Trwałość:** wpis i operacja kolejki zapisują się razem; restart, edycja i usunięcie nie tracą danych. Import katalogu nie duplikuje rekordów.
3. **Przepływ:** wyszukanie produktu, podanie ilości, zatwierdzenie i aktualizacja dziennika bez sieci, z ochroną przed podwójnym naciśnięciem.
4. **Wygląd:** oba motywy, pusty dzień, długie nazwy, klawiatura, mniejszy ekran i powiększony tekst. Ręczny przegląd zamiast testów powielających każdy element układu.

Nie potrzebujemy na start kompletnego backendu ani działającej analizy AI. Do rozpoczęcia potrzebne są Android Studio/JDK/SDK, urządzenie do uruchomienia, makiety i mały katalog lokalny.

## 8. Pierwsze zadanie do wykonania w kodzie

Lokalny rdzeń A-01–05, formularze profilu/wagi/prywatnego produktu/kompletności, importer E2, BigDecimal i analityka 7/30/90 dni są zaimplementowane. Fundament 0.6 utrwala UUID gościa/tożsamości, rozdziela zakres repozytoriów/kolejek i chroni lokalne transakcje generacją. Nie dodaje autoryzacji ani przełączania kont w UI; zachowuje dawny alias gościa i globalne klucze encji.

W 0.7 przygotowano trwałe żądanie bootstrapu, atomowe mapowanie account_id/generacji/epoki i blokadę zmiany kontekstu oraz niezmienne cele. Parametry przyszłego klienta i granice są w [przekazaniu E3](android/INTEGRACJA_E3.md). Android 0.8.1 łączy klienta sesji AppAuth/PKCE i odtwarzanie ViewModel/formularzy z trwałym bootstrapem HTTP, przechwyconym tokenem/tożsamością/lease i bezpiecznym ponawianiem. [Raport](android/RAPORT_0_8_1.md) opisuje lokalne testy i granice transportu zastępczego; [konfiguracja](android/BOOTSTRAP_HTTP.md) rozdziela połączenie konta od synchronizacji. Następny etap: rzeczywisty odbiór APK/HTTPS/Keycloak O3 z ograniczonym publicznym CA, odczyty API, docelowe klucze właściciela oraz adapter E0 i scenariusze synchronizacji. Wymaga endpointów E3/E4 O2 i konfiguracji środowiska O3. Przed wysyłką oraz zapisem odpowiedzi trzeba sprawdzać właściciela/generację zadania; import gościa wymaga jawnej zgody i trwałego potwierdzenia. Roboczy outbox nie jest gotowym payloadem HTTP. Do dostawy API można przygotować adaptery i scenariusze offline bez udawania rzeczywistego sync. MRE 2026 pozostaje osobnym importem katalogu: nie sumujemy alternatyw ani zbiorczego pakietu dodatków ze składnikami.

## Dokumentacja techniczna

Dobór rozwiązań bazuje na oficjalnej dokumentacji Androida:

- Wspólne motywy i komponenty: [Material 3 w Compose](https://developer.android.com/develop/ui/compose/designsystems/material3).
- ViewModel, repozytoria i przepływ stanu: [zalecenia architektury Android](https://developer.android.com/topic/architecture/recommendations).
- Lokalna warstwa danych: [offline-first](https://developer.android.com/topic/architecture/data-layer/offline-first), [Room](https://developer.android.com/training/data-storage/room).
- Trwałe zadania synchronizacji: [WorkManager](https://developer.android.com/develop/background-work/background-tasks/persistent).

Przekazanie E9 odczytane na main2b4073e i PR57/58. Po kliencie Nemesis wydzielimy `codex/android-korekty-zapotrzebowania`: state/history/requested/effective, osobne świadome notice/affirm i decyzje analizy, oś E oddzielona od celu kcal. Ten etap nie jest wykonany ani opublikowany jako PR. Pierwszy rzeczywisty APK/API wymaga osiągalnego z urządzenia issuer/origin/publicCA i poprawnego discovery/readiness od O3; lokalny rollout0024 nie zastępuje tego warunku. SemantyczneE4/WorkManager/KO31/recovery pozostają otwarte.
