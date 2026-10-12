# Recenzja instrukcji E8.4 — projekcje i wynik Nemesis - osoba 2

12 października 2026 r. Niezależny odbiór instrukcji koordynatora Agent 2 i jej integracji z planem oraz wspólnym dziennikiem.

**Wynik: 9,3/10; brak P1/P2. Instrukcja spełnia kryterium niezależnego przeglądu przed publikacją.** Zakres jest wykonalny, zgodny z wymaganiami i dostatecznie konkretny do zlecenia trzeciemu wykonawcy E8 po zakończeniu workflow dokumentacji. Nie znaleziono istotnej brakującej decyzji produktu ani potrzeby dodatkowego zatwierdzenia człowieka.

## Zakres i podstawa

Przeczytano cały `docs/MASTER_PROMPT_E8_4.md` oraz zmienione fragmenty `PLAN_PRAC.md`, `MASTER_PROMPT_KOORDYNACJA_E8.md` i `KOMUNIKACJA_AGENTOW.md`. Porównano istniejące części trzech dokumentów z podstawą. Sprawdzono właściwe interfejsy źródła przez `git show`, bez ponownego audytu niezmienionych etapów E0–E7, uruchamiania PG lub testów.

- Przyjęta podstawa kodu: `b68d645f6bea4c47a385c6aa1b39cd98bd94c814`, scalony PR37.
- Head PR37: `b3d268a1223f355b3024210ab18b0168f2076d8d`.
- Własny odczyt Git potwierdził identyczne całe drzewa obu commitów: `40f22cbb69a5d6e4ee228ba8df4d42e96ac7e51f`.
- Dokładny commit startowy wykonawcy zostanie przekazany przez koordynatora po scaleniu mastera. Ma zawierać przyjęty kod oraz opublikowaną instrukcję. To celowo określona kolejność workflow, a nie pozostawiony source placeholder.

Oceniono następującą treść plików, przed dodaniem niniejszej recenzji:

| Dokument | SHA-256 |
| --- | --- |
| `MASTER_PROMPT_E8_4.md` | `ae7a001a1a0e564f08072b8f7a2a1910d48d53178e67fc5c91e19f37f4f7c20a` |
| `PLAN_PRAC.md` | `e1eaaddeba9cb8ee29f04f684be97aa7cea65e53fc495832be47ce8daaa1baae` |
| `MASTER_PROMPT_KOORDYNACJA_E8.md` | `b8f373d3e180efadbd33621c252c1f34955c8d447764ac8bf1f7ce59e22d69f7` |
| `KOMUNIKACJA_AGENTOW.md` | `40aa537aec90ddb360991263ed2a4a068f342fd19cbfc87e7afff48ebf55ab5f` |

## Ocena wymaganych obszarów

| Obszar | Ocena instrukcji i zgodności ze źródłem |
| --- | --- |
| Architektura i źródłowy zapis | Istniejący `source_mutated` rzeczywiście ma fazy lock → plain refresh → qualified context → apply. Master wymaga zastąpienia tego jedną jawną ścieżką DB orchestratora, bez dodatkowego refresh, ticketów lub drugiego sync. Adapter jest zbiorczy, a produkcyjny sync tworzy go w source savepoincie. |
| Kwalifikacja i blokady | Wymagane account/counter/all challenges UUID ASC, sprawdzenie provenance i pełnego discovery oraz jedno q z DB są spójne z przyjętym seamem. Jeden SQL call wykonuje refresh i wewnętrzny writer; caller nie dostarcza q/punktów. Apply porównuje konkretne zwrócone q i nie zapisuje ponownie. Commit po terminie, rollback i retry mają jednoznaczne reguły WF-12/11.7/KO-22/26/27. |
| Accept i trwałe projekcje | Master wymaga rzeczywistego DB seed obu stron i wszystkich N dat. Poprawnie traktuje obecny callback jako niewystarczający do ochrony direct EXECUTE. Seed, slots, zgody i receipt są atomowe; replay nie inicjalizuje drugi raz. |
| Kalendarz i punktacja | Accepted zone, utrwalone granice i maturity nie zależą później od profilu/tzdata. Master wskazuje rzeczywisty boundary CHECK0018, który trzeba zmienić nową migracją. Regularity_v1 daje bazowy punkt bez celu, bonus ma inclusive ±10%, a brak kcal lub pusty dzień nie jest zerowym spożyciem. Dojrzewanie bez klienta odpowiada KO-29. |
| Cel, E i procenty | Faktyczna oś goal heads rozstrzyga historyczny cel; `GoalPayload.estimate` zawiera maintenance_kcal. Master wymaga pobrania E z wybranej wersji, nie z celu kcal/profilu. Średnia dziennych procentów, deterministyczny reprezentant wagi i counts są jednoznaczne. Addytywny typ procentu ze znakiem przyjmuje stringi "-50", "-15", "0" bez zmiany dotychczasowego unsigned ComputedDecimal. |
| Statistics i zgody | Kontrakt hidden/insufficient/available oraz pending nie ujawnia brakujących lub nieuzgodnionych danych. Provisional ma jeden spójny snapshot. Odczyt ponownie sprawdza uczestnictwo, oba generations, epoch/status/sharing; metadata nie stanowią uprawnienia do statistics. Cancel/deletion/restore oraz receipt/cache/304 nie przywracają sharing. |
| Finalizer | Wynik pochodzi z własnych trwałych projekcji. Master wyklucza live-source obliczenia, późne refresh, owner sync H i ukryty account FK po challenge lock. Wymaga fizycznej blokady tabel źródeł jako oracle, atomowego final result i legalnego cancel po final. Istniejące provisional CHECK i accepted-field guard są wskazane jako wymagające nowych definicji. |
| Role i capability | Default-closed gate ma wiązać rzeczywistą zgodność schema/initializer/projector/finalizer z bieżącą epoką. Operator activation, zamknięty definer path, explicit REVOKE i cały role graph są objęte kontrolą. Worker nie dostaje ogólnego source SELECT, consent/identity admin lub DDL. Testowa revision pair i env nie mogą otworzyć funkcji. |
| Migracje, purge i restore | Faktyczna0020 deleguje zachowany parent chain i tworzy scoped deletion context wyłącznie we wrapperze. Master wymaga rozszerzenia tego protokołu, a nie zastąpienia go. Nowe private projections/results i peer dane podlegają cleanup; restore odcina stare wyniki natychmiast przez epoch. Published0001–0020 pozostają immutable; następna migracja najwcześniej0021. Legacy accepted bez seed nie otrzymuje fikcyjnego wyniku. |
| Testy i przekazania | Oracles obejmują rzeczywisty PG17, wyścigi/rollback/restart, raw grants/EXECUTE, instalowany pakiet i pełną ścieżkę operatora. Zakres O2 jest oddzielony od własnych odbiorów O1/O3. Nie ma nowego czwartego głównego wykonawcy, E9 lub automatyzacji; E8.5 pozostaje u koordynatora. |

Duży zakres testów odpowiada konkretnym granicom transakcji, historii i prywatności; nie jest nieuzasadnionym komplikowaniem instrukcji. Można współdzielić setup i powiązane oracles, zachowując ich rzeczywiste asercje. Nazwy nowych helpers/DTO, mechanizm spójnego snapshotu, szczegóły batch/backoff oraz podział plików pozostają decyzjami wykonawczymi w obrębie wskazanych wymagań.

## Integracja dokumentacji i zachowanie komunikacji

Porównanie linii z bazą wykazało:

- W planie zmieniono tylko wiersz E8.4, dodając link do mastera.
- W masterze koordynacji zmieniono tylko wiersz E8.4 i dopisano aktualną podstawę oraz rezerwację. Historyczne ustalenia zachowano; nowy dopisek jawnie zastępuje stare rezerwacje numerów migracji.
- W dzienniku zmieniono wyłącznie własny wiersz O2 w tabeli, a po wszystkich 860 liniach podstawy dopisano aktualne przekazanie O2-024. Pozostałe istniejące linie, w tym wszystkie wpisy O1/O3 i historia O2, są identyczne. O2-027 pozostaje rezerwacją dla przyszłego wykonawcy, nie deklaracją dispatch.

Dziewięć lokalnych linków dokumentacyjnych w masterze wskazuje istniejące pliki. Zapis o odczycie O1-018/O1-019 nie przypisuje koordynatorowi testów Androida ani nie potwierdza odczytu nowej dostawy za O1. Bieżący status nie zaciera historycznego niewyjaśnionego przypadku E7. Wcześniejsze oceny prywatnego szkicu 8,9→9,3 zachowują historię korekty; obecny wynik dotyczy uzupełnionej instrukcji i integracji dokumentów.

## Granice tego odbioru i następny krok

To **formalny odbiór instrukcji**, a nie odbiór produktu E8.4. E8.4 nie jest jeszcze zaimplementowane: DB orchestrator/writer/seed/statistics/finalizer i ich nowe ACL/cleanup wymagają własnego wykonania oraz niezależnych dowodów na zamrożonym źródle.

Stan odebranej podstawy i wykonane kontrole PR37/push main przyjęto z przekazania koordynatora: PR CI38233564729 oraz osobny main CI38236250411. W tej recenzji nie otwierano GitHuba, nie wykonywano tych testów i nie sumowano ich zakresów; własny odczyt potwierdza źródło i tożsamość drzew, nie nowe wyniki runtime/CI.

Koordynator ma wykonać własne kontrole dokumentacji, opublikować master przez docs PR, odczytać wymagane CI, scalić i odebrać main. Następnie może przekazać dokładny start SHA i utworzyć jeden trzeci główny czat E8.4. Nie ma dodatkowej zależności od pełnego Androida lub wdrożenia O3 dla tej samodzielnej implementacji. Pełne zespołowe E8, rollout i odbiory O1/O3 pozostają odrębnymi wymaganymi rezultatami.

## Suplement: normalizacja końca pliku i metadane recenzji

12 października 2026 r. Aktualny SHA-256 mastera: `4dc04e364a6f4c4b6333ef60fbe44df2114938bc977e8cbbe1870664308b4c51`. Sprawdzenie ograniczono do zakończenia pliku oraz nowych metadanych; nie powtarzano audytu źródła, PG, testów ani CI.

Własne porównanie kryptograficzne potwierdziło tożsamość treści merytorycznej: z bieżącego mastera odtworzono wcześniejszy hash `ae7a001a1a0e564f08072b8f7a2a1910d48d53178e67fc5c91e19f37f4f7c20a` wyłącznie przez przywrócenie terminalnych znaków LF. Oba warianty mają identyczną treść przed końcowymi pustymi liniami. Historyczny hash i ocena w powyższym raporcie pozostają zapisem poprzedniego stanu.

Publiczny `docs/e8/RECENZJA_MASTER_NEMESIS_WYNIKI.md`, po normalizacji zakończeń linii, odpowiada w całości raportowi sprzed tego suplementu; jedyną różnicą tekstową jest dopisek „- osoba 2” w nagłówku. W dzienniku doszedł wyłącznie akapit z wynikiem przeglądu, linkiem do recenzji, aktualnym hashem mastera i nadal otwartymi krokami docs PR/CI/main/dispatch. Po usunięciu tego nowego akapitu w pamięci odtworzono wcześniejszy hash dziennika `40aa537aec90ddb360991263ed2a4a068f342fd19cbfc87e7afff48ebf55ab5f`; wcześniejsze wpisy pozostają identyczne.

**Wynik pozostaje 9,3/10, zero P1/P2.** Normalizacja EOF, nagłówek i metadane nie zmieniają zakresu ani granic odbioru. Nie stanowią dowodu implementacji E8.4, nowego runtime lub CI. Zmieniono wyłącznie niniejszy prywatny raport.
