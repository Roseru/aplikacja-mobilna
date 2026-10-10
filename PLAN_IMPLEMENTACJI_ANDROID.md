# Plan implementacji — osoba 1: Android i pamięć lokalna

Data: 9 października 2026 r.

Podstawa: `WYMAGANIA_PROJEKTOWE.md` oraz zaakceptowane makiety. Użytkownik jest osobą 1 w trzyosobowym zespole. Ten dokument wyznacza kolejność implementacji; bieżący zakres kodu jest opisany w [android/README.md](android/README.md).

**Postęp:** A-01–05 są zaimplementowane i sprawdzone w wersji 0.1.0. Wersja 0.2.0 dodaje lokalne racje DEMO i migrację Room 1 → 2. Wersja 0.3.0 dodaje prywatny produkt, profil, pomiary wagi i kompletność dnia oraz Room 3. Wersja 0.4.0 dodaje importer pakietu E2, BigDecimal, generacje i pełne snapshoty nowych spożyć, z migracją Room 3 → 4. Rzeczywista synchronizacja i pełny adapter dawnych danych do API pozostają do wykonania; [instrukcja Androida](android/README.md) i [raport 0.4](android/RAPORT_0_4.md) opisują zakres i ograniczenia.

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

Lokalny rdzeń A-01–05, formularze profilu/wagi/prywatnego produktu/kompletności oraz importer eksportu E2 i obliczenia BigDecimal są zaimplementowane. Następny spójny etap to lokalna analityka 7/30/90 dni: historia spożycia, realizacja datowanych celów i masa z jawnymi brakami oraz kompletnością dnia. Konta i faktyczny sync wymagają wdrożonych endpointów kolejnych etapów backendu i jawnej konwersji roboczej kolejki do kontraktu. Import materiałów MRE 2026 jest osobnym zadaniem katalogu: nie sumujemy alternatyw ani zbiorczego pakietu dodatków ze składnikami.

## Dokumentacja techniczna

Dobór rozwiązań bazuje na oficjalnej dokumentacji Androida:

- Wspólne motywy i komponenty: [Material 3 w Compose](https://developer.android.com/develop/ui/compose/designsystems/material3).
- ViewModel, repozytoria i przepływ stanu: [zalecenia architektury Android](https://developer.android.com/topic/architecture/recommendations).
- Lokalna warstwa danych: [offline-first](https://developer.android.com/topic/architecture/data-layer/offline-first), [Room](https://developer.android.com/training/data-storage/room).
- Trwałe zadania synchronizacji: [WorkManager](https://developer.android.com/develop/background-work/background-tasks/persistent).
