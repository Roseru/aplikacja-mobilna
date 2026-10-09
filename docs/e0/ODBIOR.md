# Raport odbioru E0 - osoba 2

Data: 2026-10-09. Zakres: projektowe B-004/B-006/B-007. **E0 ukończone lokalnie:** kontrole artefaktów przeszły, niezależna recenzja po poprawkach **9,2/10**, bez istotnych nierozwiązanych usterek. E1 nie rozpoczęto.

## Stan wejściowy i zachowana praca

Start na `main`, HEAD `0b792d1`. Przed E0 zmodyfikowane były: README.md, WYMAGANIA_PROJEKTOWE.md, docs/ARCHITEKTURA.md, docs/PLAN_PRAC.md, docs/WORKFLOW.md (łącznie46 dodanych/37 usuniętych linii); były też nieśledzone docs/MASTER_PROMPT_E0.md i docs/materialy/. Zmiany obejmowały ustalenia Gemini Free Tier. Zachowano je, nie resetowano/stashowano plików. Nie znaleziono obowiązującego AGENTS.md w repozytorium ani katalogach nadrzędnych.

Pracę wykonano na `codex/e0-kontrakty-osoba-2`. `git ls-remote --heads origin` potwierdził main `0b792d19460e6fea07ba4e2d20c1a72f58c17605` i Android `f5aabfc3aa4ed189a4fa3d9ad245a71faeff46d2`. Pierwsza próba dostępu sieciowego w sandboxie nie powiodła się; odczyt z uprawnieniem sieciowym zakończył się poprawnie. Kod/README/assets Androida odczytano przez git show, bez merge ani zmian w kodzie O1. Brak commita, push, PR i kontaktu z innymi osobami zgodnie z zakresem zadania.

## Dostarczone artefakty

[Mapa kontraktów](../../contracts/README.md) zawiera wszystkie foldery. [OpenAPI](../../contracts/openapi/design-v1.yaml) ma status design draft. [Decyzje integracyjne](KONTRAKTY_I_INTEGRACJA.md) obejmują model, diagramy, Decimal, czas, własność, historię i tabele przekazania O1/O3. [Sync](SYNCHRONIZACJA.md) rozdziela zwykłe uzgodnienie po30d od restore epoki. [Rejestr źródeł](ZRODLA_KATALOGU.md) dokumentuje22/4/3 pozycji i3466/3468/3600kcal, pełne jawne braki oraz demo18 pozycji, gzip i manifest.

## Kontrole wykonywane teraz

Komenda z katalogu głównego: `.\tools\contracts\validate.ps1`. Środowisko przygotowane lokalnie: Python3.13.9, uv0.9.5 i lockfile. Zależności ograniczono do walidacji dokumentów; brak infrastruktury E1.

Komenda zakończyła się kodem **0**, bez sieci:

```text
PASS E0 | Python 3.13.9 | schemas=5 | endpoints=16 | HTTP examples=124
PASS examples valid=64 invalid=20 scenarios=18; refs/formats/orphans/source/gzip/manifest
PASS Decimal vectors=16; day completeness=5; source normalizations=72; local links=65; git diff --check
NOT EXECUTED: server transactions, PostgreSQL, Room, Kotlin, OIDC, deployment (E1-E5).
```

84 indeksowane przykłady obejmują 64 poprawne oraz 20 celowo błędnych, odrzuconych z oczekiwanej przyczyny. Licznik `scenarios=18` obejmuje 17 poprawnych scenariuszy przyszłego serwera i jeden celowo wadliwy scenariusz odpowiedzi z obcym entity_id. Kontrola porównuje komunikaty scenariuszy także bezpośrednio z OpenAPI. Wektory obejmują HALF_UP, brak/zero, g/ml, gęstość, dzielenie niekończące się i części racji. Osobne fixture’y sprawdzają granicę UTC oraz obie jesienne godziny DST i zmianę wiosenną. Obliczenia kalkulatora sprawdzono również dla wejścia z sześcioma miejscami, którego dokładne wyjście wymaga większej skali.

Manifest i rzeczywisty gzip: 3278 B skompresowanych, 24695 B JSON; SHA-256 `307360b84fdac192f434969a323728ec835795e474095d0a1f0c0807a952f7f0`. Hash niezmienionego materiału źródłowego: `e79a1781e40af020e7affe9cac60fb6eb65b5d5b8c72bb568d62bb7edbaa55e2`. Wykonano audyt 22/4/3 pozycji, sumę 3466 kcal i 72 normalizacje pól odżywczych.

Przy starcie lokalnego interpretera na dysku S: pojawia się ostrzeżenie `Failed to find real location...`; interpreter uruchamia się, zgłasza 3.13.9 i wykonuje wszystkie kontrole. Git ostrzega o konwersji LF/CRLF README; `git diff --check` kończy się kodem 0. Nie potraktowano tych komunikatów jako pominięcia testów.

## Mapa wymaganie → artefakt/przypadek → weryfikacja

| Wymaganie / WF / KO | Artefakt lub przypadek | Teraz E0 / przyszły etap |
|---|---|---|
| B-004, WF-03/04, KO-02/23 | common/domain/catalog, nutrition-v1: half-component, parts-of-ration, millilitres-no-density | Schemat i Python Decimal teraz; Kotlin i Room O1/E2 |
| WF-01/02, KO-12/24 | Goal/Estimate, axis revision, history correction; goal i estimate fixtures | Schemat/rachunek teraz; transakcje osi E3/E4, korekty AI E9 |
| WF-03/10, KO-11/25 | Nullable Nutrition, known_sum/missing_count, day_cases | Arytmetyka/kompletność teraz; średnie/analityka E5, punkty E8 |
| WF-05, KO-01/08/30 | catalog-demo/manifest/gzip, catalog-reference/counts/official/unit/duplicate | Hash/ref/liczności/negatywy teraz; APK offline, restart, brak miejsca i wyścig aktywacji E2/O1; oficjalne dane E5 |
| B-006, WF-04/07 | ZRODLA_KATALOGU, nienaruszony source.json, source_locator | Audyt i normalizacja teraz; etykiety/FDC i publikacja official E5 |
| B-007, WF-01/06, KO-05/07/31 | Bootstrap, bearer/consents, scenariusze expired-session/account-switch/guest | Struktura komunikatów teraz; podpisy JWT i izolacja E3, WorkManager i import E4 |
| WF-06, KO-03/04/06/12 | Push/Pull/Entity, scenariusze utraty odpowiedzi/zmienionej treści/konfliktu/usunięcia | Schemat i zgodność opisu teraz; prawdziwe zapisy, retry i konflikt E4 |
| KO-18/19/20 | Granica30dni i+1s,61dni, wygasły snapshot, kolejność commit i retencja | Scenariusze kontraktu teraz; retencja/retry/współbieżność PostgreSQL E4 |
| KO-32 część sync | RecoverySource/Mapping/OperationReceipt, nowa epoka i odzyskiwanie z dwóch urządzeń | Kształt i oczekiwane odpowiedzi teraz; restore PostgreSQL/Room E4; AI E7, pełne odtworzenie E10 |
| Czas / KO-24/29 | UTC/IANA/local_date, dzień DST, cel z decided_at/effective_from | Format i spójność dat teraz; worker północy/punkty E8 |
| O3 / KO-16/17 | Tabela DB/OIDC/health/limitów i przepływ generowania OpenAPI | Dokument teraz; Compose, CI, migracje i health E1, backup/restore E10 |

Scenariusze są indeksowane osobno od błędnych fixture’ów. Każdy ma lokalny wynik i etap przyszłego testu; poprawne żądanie mogące dać409 lub conflict nadal jest lokalnie poprawne. Raport nie uznaje scenariuszy za wykonane operacje serwera.

## Zaprojektowane, ale niewykonane

Nie uruchomiono serwera FastAPI, PostgreSQL17, Keycloak ani Room/emulatora. Nie wykonano transakcji/retry, realnej retencji60d, atomowego przełączenia generacji, wyścigów recovery, migracji Room/SQL, testu utraty odpowiedzi w sieci, Kotlin/BigDecimal ani CI. Te testy należą do E1–E5 zgodnie z mapą. Nie wywołano Gemini; brak klucza/billing nie jest przeszkodą E0.

## Niezależna recenzja

Recenzent `review_e0` nie był autorem artefaktów. Przeczytał wynik i wymagania, odczytał Androida przez git show, samodzielnie uruchomił komendę i wykonał negatywne próby w pamięci. Pierwsza ocena: **8/10**. Zgłosił trzy istotne niespójności i trzy luki walidacji; wszystkie poprawiono przed ponownym przeglądem:

| Uwaga | Poprawka i dowód |
|---|---|
| Błędy sync w OpenAPI miały inny kształt niż scenariusze | Wszystkie używają SyncError, wspólny kod rate_limited; sześć przykładów błędów i bezpośrednia walidacja scenariuszy przeciw OpenAPI |
| Dokładny wynik kalkulatora nie mieścił się w skali wejściowej | Osobny ComputedDecimal do 12 miejsc dla wyników; fixture estimate-submicro oraz dokładny rachunek w checkerze |
| UUID profilu równy kontu kolidował z delete/recovery | Niezależny UUID, jeden żywy profil na owner, nowe UUID po usunięciu/restore, uzgodnienie istniejącego profilu; scenariusz restore_missing_profile |
| Obcy entity_id w odpowiedzi scenariusza przechodził | Kontrola korespondencji operation_id oraz entity_id; negatywny sync-result-entity |
| Wrapper ProfileRead pomijał walidację profilu | Rekurencja do Profile; negatywny profile-read-height |
| Szkic pomijał jednostkę package_quantity | Kontrola ilości opakowania i wymaganej gęstości; negatywny draft-package-density |

**Wynik ponownej niezależnej recenzji: 9,2/10, brak istotnych nierozwiązanych usterek; próg odbioru spełniony.** Recenzent samodzielnie uruchomił pełną komendę ponownie (kod 0, liczności zgodne z raportem powyżej) i dodatkowo sprawdził 41 odpowiedzi HTTP scenariuszy przeciw OpenAPI. Potwierdził poprawne wyniki kalkulatora o większej skali oraz odrzucenie przedwcześnie zaokrąglonych wyników. Negatywne próby potwierdziły odrzucenie obcego entity_id, błędnego wzrostu we wrapperze, brakującej gęstości opakowania, ponownego użycia źródłowego UUID recovery oraz niekompletnych struktur indeksu i wektorów. Nie zmieniał ocenianych plików.

Nieblokujące uwagi recenzenta: uporządkować ostrzeżenie lokalnego interpretera przed E1; przy rozwoju walidatora można dodatkowo porównywać parametry GET scenariuszy z pojedynczymi deklaracjami query OpenAPI (obecnie pełny zestaw waliduje wspólny PullRequest). Ocena dotyczy artefaktów E0, nie wykonania przyszłego serwera. Lokalny odbiór nie oznacza merge ani wydania.

## Braki danych i przekazanie

Nie ma potwierdzonych etykiet każdego składnika ARPOL WZ1/WZ4 WEGE, wybranych rekordów FDC i kompletnego źródła napoju/batonu. Źródłowa S-RG-1 jest niezweryfikowana i niepełna;4 pozycje nie mają wartości,3 nie mają masy, sól/pieprz wymagają ilości. Braki blokują oficjalny katalog E5, nie demo/E0.

O1 wdraża migrację roboczych ID/Double i outbox, jednostki g/ml, snapshoty, manifest/gzip/generacje, właścicieli i protokół epok; wykonuje wspólne wektory w Kotlin i testy zachowania danych. O3 dostarcza dwie bazy/role, issuer/JWKS, PKCE/redirect uzgodniony z O1, HTTPS, konfigurację i później CI/kopie. Szczegóły są w tabelach integracji.

Pierwsze zadanie E1: **B-001 — uruchamialny szkielet FastAPI/Pydantic2 na Python3.13, konfiguracja, błędy, health i testy**, następnie B-002/B-003 z O3/PostgreSQL. E0 kończy się lokalnymi artefaktami; publikacja i merge wymagają osobnego polecenia.
