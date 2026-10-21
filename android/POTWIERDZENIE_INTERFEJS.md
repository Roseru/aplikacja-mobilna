# Zatwierdzanie posiłku z ekranu analizy — 0.8.21

To historyczny odbiór0.8.21. Aktualny0.8.22 dodaje
[powrót do poprawek po odrzuconej decyzji i trwałą historię](POWROT_DO_POPRAWEK.md).

Agent 1 / O1, 18 października 2026. Gałąź `codex/android-potwierdzenie-posilku`,
[PR122](https://github.com/Roseru/aplikacja-mobilna/pull/122), zależny od
`0068232d80c0e33b0b33bf15e86cad2174774707` / [PR121](https://github.com/Roseru/aplikacja-mobilna/pull/121).
Podstawa: [WF-09](../WYMAGANIA_PROJEKTOWE.md),
[kontrakt E7](../docs/e7/INTEGRACJA_O1.md),
[trwała decyzja i materializacja](POTWIERDZENIE_POSILKU.md).

## Zachowanie

Po zapisaniu poprawek użytkownik wybiera „Dodaj do dziennika”. Osobny dialog
pokazuje nazwę oraz dzień i wymaga zatwierdzenia. Decyzja odnosi się do dokładnej
rewizji propozycji i poprawek. Zmiana konta, poprawek lub opuszczenie aplikacji
zamyka niezapisany dialog. Brak ważnej sesji, recovery albo inna trwająca operacja
blokują wysyłkę; lokalny dziennik nadal działa.

SessionController utrwala pełną decyzję z jednym UUID przed odświeżeniem tokenu.
Przed HTTP zapisuje znacznik próby. HTTPS wysyła zamrożony JSON na ścieżkę
`/ai/food-analyses/{analysis_id}/confirm` z tym samym Idempotency-Key i X-Sync-Epoch.
Nie wysyła ponownie obrazu i nie wywołuje bezpośrednio dostawcy AI.

HTTP200 nie wystarcza do sukcesu: walidujemy pełne dopasowanie analizy, Meal,
szkiców i provenance do zamrożonej decyzji. Parsowanie i plan zapisu są poza
blokadą sesji. Pod blokadą ponownie sprawdzamy lease, kontekst, sesję i oryginalny
wiersz, następnie atomowo zapisujemy Meal/Items, provenance, rejestr materializacji
i kanoniczny outbox oraz zwalniamy tylko to zlecenie zdjęcia. Sprzątanie
przygotowanego wejścia następuje po commicie; zdjęcie źródłowe pozostaje.

Posiłek jest wtedy dostępny lokalnie. Komunikat wyraźnie informuje, że
synchronizacja wpisu czeka na osobne potwierdzenie. Brak kcal lub B/T/W pozostaje
brakiem danych; porcje zachowują dokładne ilości g/ml.

## Utrata odpowiedzi i błędy

- Wejście na ekran lub restart aplikacji odtwarza wyłącznie zapis lokalny.
  Przycisk „Ponów dodanie posiłku” wysyła ten sam klucz i body. Nie tworzymy
  automatycznie kolejnej decyzji, nie cofamy nowszych edycji dziennika.
- Po401 jest najwyżej jedno odświeżenie i ponowienie w danym wywołaniu, nadal
  z identycznym żądaniem.429/503 oraz ai_operation_busy zachowują trwały termin
  i wspólny backoff API. Nie ma automatycznej pętli POST.
- Błędny ACK nie zapisuje części dziennika. Spóźniona odpowiedź po wylogowaniu,
  A→B→A, zmianie kontekstu lub zatrzymaniu ekranu nie przechodzi kontroli sesji.
- GET z decision_state=confirmed sam nie zastępuje ACK własnej niepewnej
  decyzji i nie dodaje wpisu. Jawny replay pozostaje dostępny.
- Konflikt rewizji/katalogu lub odrzucona decyzja zachowują poprawki do odczytu
  i wymagają sprawdzenia wyniku. Nie generujemy nowego klucza za użytkownika.
  Na etapie0.8.21 nowe przygotowanie decyzji po definitywnym odrzuceniu wymagało
  dalszego interfejsu; stara decyzja pozostawała wtedy zablokowana także po GET.
  Zmiana epoki/generacji/kontekstu przechodzi do recovery bez utraty danych.

## Walidacja i granice

Build0.8.21/code32/validation1032 zakończony:310 testów JVM debug i325 validation,
bez błędów, pominięć lub error; lint0error.14 celowanych przypadków urządzenia
API35 PASS:10 sesji/Room,3 Compose i zapis trzech celów kalorii, przy braku
sieci przed i po przebiegu.
Sprawdzono250 niezmienionych wejść buildu. Room pozostaje12, bez nowej migracji
lub zmiany eksportów1–12. Końcowa pełna regresja: **286/286 PASS**, bez błędów
i pominięć,280,158s instrumentacji/282,719s całego przebiegu, offline przed i po.

Pierwszy odbiór urządzenia wykrył brak trybu confirm w warunku wejścia dla
istniejącego zlecenia:3 UI PASS,9 przypadków sesji FAIL; żaden confirm POST
nie został wysłany. Poprawiono bramkę kodu, zachowano pierwszy log i APK.
Następnie wykonano ponowny build/JVM/lint oraz13/13 nowych przypadków, w tym
dodatkową regresję opuszczenia ekranu. Nie zwiększano timeoutów ani nie osłabiano asercji,
żeby uzyskać zielony wynik.

Pierwszy pełny przebieg po poprawce bramki zakończył się285 PASS i jednym
timeoutem istniejącego testu celu: zapis profilu/celu przeszedł, ale test
oczekiwał na czasowe zniknięcie komunikatu. Zachowano log i wynik FAIL.
Test używa teraz rzeczywistej akcji dostępności Snackbar Dismiss po
sprawdzeniu komunikatu; nadal sprawdza zniknięcie, wszystkie trzy cele,
profil i odtworzenie ekranu, z tym samym limitem10s. Nie przesuwano zegara
ani nie zwiększano timeoutu. Po tej zmianie14/14 celowanych przypadków PASS.
Oba APK aplikacji mają identyczne SHA jak przed zmianą testu; zmienił się
wyłącznie pakiet testowy. Końcowa pełna regresja ma oddzielny log i wynik.

Zwykły APK zainstalowano przez install-r jako aktualizację. Wszystkie26 tabel,
ich kolumny/wartości i rowid pozycji dziennika są identyczne przed instalacją,
po instalacji oraz po pierwszym uruchomieniu; foreign_key_check bez błędów.
Po końcowej kontroli aplikację ponownie otwarto, potwierdzono wersję0.8.21,
widoczny ekran i brak ANR. Surowe kopie bazy i UI pozostają prywatne poza
repozytorium i OneDrive; nie resetowano ani nie odtwarzano danych urządzenia.

## Źródło i artefakty

Kod: `d9b5a975cae00c1c2d7366e5d33ed3e3d902ede5`, versionCode32,
validation1032. APK są lokalnymi niezmiennymi artefaktami, bez publikacji w Git.

| Artefakt | SHA-256 |
|---|---|
| debug0.8.21 | `544a29f2eef150ec80c9e354dde8374c48654488cecd754355a765868a154abf` |
| validation0.8.21 | `50c55f10c061b239e6cfc32942739c1f2fcac958a2403b703849ad4208ab07aa` |
| domyślny test APK | `5a58892f8746de945c0a27634f22b556eb5fcc82902ea3bcff5e0d89463b4a4d` |

Końcowy log286: `d4049fac18446f84c984c20c0429668c90c636d8166f859750797b1b798d358d`.
Celowany log14: `c4b876c11ee4bae9d2ea44d186ed989bbf9ab7154279b6278ef828adcf6e560a`.
Domyślny test APK wyklucza driver rzeczywistego API; zwykły debug nie zawiera
obserwatorów walidacyjnych. Trzy APK i250 wejść zweryfikowano hashami.

Transport confirm jest podłączony do istniejącej konfiguracji API i OIDC.
Dowody syntetyczne nie zastępują rzeczywistego odbioru APK/API/Keycloak/TLS.
Nie uruchamiano Gemini ani poprzedniego relay. Standardowy transport push/pull,
konwersja legacy, pełne recovery, retencja oraz pełne E4/E7/KO32 są oddzielnymi
etapami. Obecny edytor zatwierdza spożycie bez publikowania produktów do katalogu;
wybór kandydatów i publikacja szkiców wymagają dalszego interfejsu.
