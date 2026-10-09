# Raport z realizacji etapu E0 - osoba 2

**Projekt:** Wojskowy licznik kalorii

**Data:** 9 października 2026 r.

**Zakres odpowiedzialności:** backend, dane, API i integracje
**Wynik:** E0 ukończone lokalnie, niezależna recenzja 9,2/10.

W etapie E0 przygotowano kontrakty, przykłady danych i reguły integracji potrzebne do dalszych prac Androida oraz backendu. Dostarczone artefakty przeszły lokalną walidację i niezależny przegląd. Etap obejmuje projektowe części zadań B-004, B-006 i B-007. Implementacja backendu w E1 pozostaje następnym krokiem.

## Zakres wykonanej pracy

Przeanalizowano master prompt, wymagania, architekturę, plan prac, workflow i plan Androida. Uwzględniono wcześniejsze lokalne zmiany dokumentacji oraz kod Androida z gałęzi `origin/codex/android-offline-racje`. Kod O1 odczytano przez `git show`, aby oprzeć przekazanie na rzeczywistych modelach Room, obliczeniach, katalogu i kolejce zmian.

Praca odbyła się na gałęzi `codex/e0-kontrakty-osoba-2`, przy HEAD `0b792d1`. Zachowano wcześniejsze zmiany w README.md, WYMAGANIA_PROJEKTOWE.md, docs/ARCHITEKTURA.md, docs/PLAN_PRAC.md i docs/WORKFLOW.md, w tym ustalenia dotyczące Gemini Free Tier. Rezultat pozostaje lokalny; nie wykonano commita, push ani PR.

## Dostarczone artefakty

| Obszar | Rezultat |
|---|---|
| HTTP API | [OpenAPI 3.1.1](../../contracts/openapi/design-v1.yaml) obejmujące 16 operacji, uwierzytelnienie, parametry, odpowiedzi i błędy; status design draft |
| Modele i formaty | Pięć schematów JSON Schema 2020-12 dla typów wspólnych, domeny, katalogu, synchronizacji oraz struktur przykładów i wektorów |
| Przykłady integracyjne | [Indeks](../../contracts/examples/index.json) obejmujący 64 poprawne i 20 celowo błędnych przykładów, z oczekiwanym wynikiem lokalnym i etapem przyszłego testu |
| Obliczenia | [16 wektorów Decimal](../../contracts/test-vectors/nutrition-v1.json) oraz pięć przypadków kompletności dnia |
| Katalog demonstracyjny | Demo 18 produktów, niepełna racja S-RG-1, rzeczywisty plik gzip i manifest z rozmiarami oraz SHA-256 |
| Synchronizacja | [Protokół push i pull](SYNCHRONIZACJA.md), checkpointy, konflikty, idempotencja, usunięcia, import gościa, izolacja kont i odzyskiwanie po zmianie epoki |
| Integracja zespołu | [Model logiczny i tabele O1/O3](KONTRAKTY_I_INTEGRACJA.md), w tym adaptacje Androida i wymagania konfiguracji infrastruktury |
| Walidacja | Narzędzie w `tools/contracts`, przypięte zależności i uv.lock; jedna komenda uruchomienia z katalogu repozytorium |

Pełną mapę plików i instrukcję przygotowania środowiska zawiera [README kontraktów](../../contracts/README.md). Szczegółowy dowód odbioru i powiązania z wymaganiami WF/KO pozostają w [raporcie technicznym ODBIOR](ODBIOR.md).

## Najważniejsze decyzje techniczne

Wartości dziesiętne w kontraktach mają postać kanonicznych ciągów znaków. Obliczenia korzystają z Decimal, a Android otrzymuje wspólne wektory do wykonania w BigDecimal. Sumowanie poprzedza końcowe zaokrąglenie HALF_UP: energia do całkowitych kcal, makra do 0,1 g. Ilości w g i ml mają jawne jednostki; konwersja między nimi wymaga udokumentowanej gęstości. Nieznana wartość pozostaje `null`, a sumy wskazują brakujące dane.

Historia posiłku przechowuje własny snapshot wartości odżywczych i referencję do dokładnej wersji produktu, jeżeli taka referencja istnieje. Aktualizacja katalogu zachowuje dawny obraz spożycia. Lokalna rewizja Androida i rewizja serwera mają odrębne znaczenie.

Synchronizacja przyrostowa obejmuje dokładnie 30 × 24 godziny, z granicą włącznie. Po przekroczeniu limitu klient uzgadnia pełny stan, zachowując historię i kolejkę zmian. Odtworzenie starszej kopii serwera zmienia `sync_epoch` i uruchamia osobną procedurę odzyskiwania, obejmującą także wcześniej potwierdzone dane. Zaprojektowano trwałe potwierdzenia operacji i unikalne mapowanie odzyskanego wpisu między urządzeniami.

HTTP API pozostaje projektem. Od E1 wdrożone operacje będą przechodziły do OpenAPI generowanego z FastAPI, z porównaniem semantyki do ustaleń E0. Format pakietu offline zachowuje własne wersjonowanie.

## Audyt próbki racji

Zachowano niezmieniony [materiał źródłowy S-RG-1](../materialy/racja_wojskowa_S-RG-1.source.json). Audyt potwierdził 22 pozycje żywności, w tym cztery bez wartości odżywczych oraz trzy rozliczane w sztukach bez znanej masy.

Suma 18 pozycji z dostępnymi danymi wynosi **3466 kcal**. Podsumowanie źródła wskazuje **3468 kcal**, a deklaracja racji **3600 kcal**. Zachowano wszystkie trzy liczby i ich rozbieżność. Demo korzysta z jawnego założenia, że wartości przy produkcie odnoszą się do wymienionej ilości; nie uznano tego za potwierdzoną podstawę etykiety.

Składnik opcjonalny wymaga wskazania faktycznego spożycia. Proszki pozostają produktami suchymi w g. Wyposażenie wyłączono z obliczeń, a sól i pieprz sklasyfikowano jako dodatki wymagające ilości oraz danych. Demo ma status niezweryfikowany i niepełny; oficjalny katalog ARPOL WZ 1 i WZ 4 WEGE wymaga osobnej weryfikacji źródeł. Szczegóły zawiera [rejestr źródeł](ZRODLA_KATALOGU.md).

## Wynik walidacji

Z katalogu repozytorium uruchomiono:

```powershell
.\tools\contracts\validate.ps1
```

Komenda zakończyła się kodem **0** na Pythonie 3.13.9. Po przygotowaniu zależności kontrola działała bez sieci.

| Kontrola | Wynik |
|---|---|
| Schematy i OpenAPI | PASS: 5 schematów, 16 operacji i 124 odwołania do przykładów HTTP |
| Przykłady JSON | PASS: 64 poprawne oraz 20 celowo błędnych, odrzuconych z oczekiwanej przyczyny |
| Scenariusze sync | PASS: 17 poprawnych scenariuszy przyszłego serwera i jeden negatywny przypadek wadliwej odpowiedzi |
| Obliczenia | PASS: 16 wektorów Decimal, 5 przypadków kompletności dnia i 72 normalizacje pól próbki |
| Spójność plików | PASS: lokalne referencje, formaty UUID/dat/stref, brak osieroconych przykładów, gzip, hash i manifest |
| Dokumentacja i Git | PASS: 65 lokalnych linków w końcowej kontroli E0 oraz `git diff --check` |

Wyniki dotyczą walidacji artefaktów E0. Rzeczywiste transakcje PostgreSQL, migracje i trwałość Room, wykonanie wektorów w Kotlin, izolacja kont w działającym API oraz wyścigi odzyskiwania wymagają testów kolejnych etapów.

## Niezależna recenzja i poprawki

Końcową weryfikację wykonał subagent, który nie tworzył ocenianych artefaktów. Pierwszy przegląd zakończył się oceną 8/10. Poprawiono trzy istotne niespójności: różny kształt błędów sync w OpenAPI i scenariuszach, zbyt małą skalę wyników kalkulatora oraz kolizję tożsamości profilu z usuwaniem i odzyskiwaniem.

Uzupełniono także kontrolę zgodności `entity_id` odpowiedzi, walidację profilu wewnątrz `ProfileRead` oraz sprawdzanie jednostki opakowania szkicu produktu. Dodano przypadki regresji i porównanie komunikatów scenariuszy bezpośrednio z OpenAPI.

Po poprawkach recenzent ponownie uruchomił pełną komendę, sprawdził negatywne przypadki i dodatkowo porównał 41 odpowiedzi HTTP scenariuszy z OpenAPI. **Ocena końcowa wyniosła 9,2/10, bez istotnych nierozwiązanych usterek.** Próg odbioru E0 został spełniony.

## Pozostałe zadania zespołu

| Odpowiedzialny | Następne działania |
|---|---|
| O1 | Adaptacja roboczych identyfikatorów i Double, migracje Room z zachowaniem danych, jednostki g/ml, wersje i snapshoty, importer gzip/manifestu, generacje katalogu oraz outbox z epoką; wykonanie wektorów w Kotlin |
| O2 | Pozyskanie etykiet i konkretnych rekordów FDC do oficjalnego katalogu E5; w E1 zadanie B-001: szkielet FastAPI/Pydantic 2 na Pythonie 3.13 z konfiguracją, błędami, health i testami |
| O3 | Oddzielne bazy i role PostgreSQL, konfiguracja OIDC/JWKS/PKCE, URI powrotu uzgodnione z O1, HTTPS oraz dalsze przygotowanie CI i kopii |

Gemini pozostaje późniejszą integracją Free Tier, z mockiem w CI. Brak klucza i billing nie ogranicza gotowości kontraktów E0. Etap E1 nie został rozpoczęty.
