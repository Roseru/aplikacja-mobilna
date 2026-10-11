# Plan manifestu i odbioru referencyjnego E7-R - osoba 2

Status: **nie wykonano / WAITING_EXTERNAL**. Stan zapisany 11 października 2026.
Nie wykonano prawdziwych wywołań Google. Ten plik określa wejścia i sposób
pomiaru; nie zawiera pozyskanych zdjęć ani sztucznego ground truth.
Scenariusze mocka, syntetyczne codec fixture i lokalny HTTP fake provider są
dowodami E7-O2, nie oceną trafności Gemini. Wymagania określają
[master E7](../MASTER_PROMPT_E7.md#11-e7-r-i-zewnętrzne-wejścia),
[decyzje v1](DECYZJE_V1.md) i
[referencje adaptera](REFERENCJE_GEMINI.md).

## Dostarczony runner i aktualna komenda

[tools/ai_reference/run.py](../../tools/ai_reference/run.py) oraz
[instrukcja/ścisły format manifestu](../../tools/ai_reference/README.md) stanowią
odtwarzalne narzędzie tego planu. Runner wymaga legalnych rzeczywistych wejść
i nie uruchomiono go na Google. Nie dostarczono gotowego corpus ani fikcyjnej
referencji rozpoznawania. Z katalogu repozytorium, po przygotowaniu przez operatora
prywatnych wejść i output poza Git:

```powershell
backend/.venv/Scripts/python.exe tools/ai_reference/run.py --manifest C:/private/e7/corpus/manifest.json --output C:/private/e7/result --max-cases 1
```

URL aplikacji HTTPS i access token pochodzą z `E7_REFERENCE_API_URL` oraz
`E7_REFERENCE_TOKEN`; opcjonalny zatwierdzony CA z `E7_REFERENCE_CA_BUNDLE`.
Token nie trafia do argv/stdout/output. TLS, trust_env=False i brak redirects
pozostają włączone. Publiczne capabilities muszą przed uploadem zgadzać się
z manifestowym Gemini profile i notice. Każdy request używa istniejącego API;
nie ma direct Google/countTokens, confirm, Meal lub publikacji E6.

Domyślnie jedno zdjęcie, jawny max do 10 na wywołanie. `state.json` zapisuje
operation key/hash/analysis ID/konto/generację/epokę/profile przed uploadem lub
przed dalszym pollingiem. Rerun po lost ACK zachowuje ten sam key/obraz;
znane ID jest tylko odczytywane. Zmiana manifestu/profilu/epoki nie nadaje nowego
key automatycznie. 429/unknown/safety i brak bramki wymagają operatora.
Raport jest prywatny i zawiera per-case liczniki oraz `manual_review`.
Niepełny run pozostaje WAITING_EXTERNAL, pełny osiągnięty próg wymaga
MANUAL_REVIEW_REQUIRED; narzędzie nie potwierdza samodzielnie ręcznego fallbacku.
Syntetyczne testy MockTransport tego runnera pozostają dowodem transportu/oracle.

## Wejścia, właściciele i dowód wznowienia

| Wejście | Właściciel | Wymagany dowód przed wznowieniem |
|---|---|---|
| Niepubliczny klucz Gemini | O3 | Dostarczenie przez sekret właściwego wydzielonego środowiska; żadnego klucza w repo/APK/CI/raporcie. |
| Datowana konfiguracja projektu/modelu/limitów | O3 | Potwierdzenie jednego stabilnego project/environment ID, modelu, Standard Free Tier, wyłączonego billing i development-only, daty odczytu oraz rzeczywistych RPM/TPM/RPD i dodatkowych wymiarów. |
| Prywatny storage/worker/cleanup i restore gate | O3 wraz z O2 | Działające autoryzowane API/worker, prywatny mount/ACL, monitoring cleanup, aktualna epoka i otwarta uzgodniona pool; stare własne procesy odcięte. |
| Corpus minimum 30 legalnych niesensytywnych zdjęć | O2, z konkretną zgodą źródła/właściciela | Kompletny opis źródeł i prawa/zgody na ten test oraz wysłanie do Gemini; rzeczywiste SHA-256 i komplet referencji. |
| Niezależne kryteria i referencje składników | O2 z niezależnym oceniającym | Datowany manifest zamrożony przed wynikami modelu, opis widoczności i pochodzenia oczekiwanych składników. |

Wznowienie następuje po zapisaniu identyfikatorów powyższych dowodów, hashów
manifestu/corpus, aktualnego commita, profilu i epoki. Brak wejść nie blokuje
odrębnego odbioru kodu E7-O2. Samo `available=true`, mock lub dostarczenie klucza
bez projektu/limitów/corpus nie spełnia tej bramki.

Obecny runtime ma model `gemini-3.5-flash-lite`, prompt `food-photo-prompt-v1`,
schema `food-photo-schema-v1`, preparation `food-photo-preparation-v1` i REST
`gemini-rest-v1beta-2026-10-11`. O3 potwierdza zgodność tego konkretnego modelu
i środowiska; model/profile są przypięte przy przyjęciu analizy. Zmiana modelu
lub istotna zmiana profilu wymaga osobnego jawnego odbioru i ponownego pomiaru.
Nie wybieramy automatycznie latest/paid fallback ani kolejnych projektów do
obejścia puli.

## Plan przekroju corpus

Poniższe identyfikatory oznaczają zarezerwowane miejsca w planie. Dopiero legalne
rzeczywiste pliki i niezależne opisy wypełnią manifest; nie są to ukończone przypadki.

| Grupa / planowane ID | Liczba | Wymagany przekrój i referencja |
|---|---:|---|
| Produkty `P01–P08` | 8 | Różne pojedyncze produkty, napoje/żywność i widoki; tożsamość udokumentowana rzeczywistą etykietą/opisem źródła. |
| Dania mieszane `M01–M08` | 8 | Różne składy i stopień zasłonięcia; składniki referencyjne wynikają z przepisu lub udokumentowanego przygotowania tej konkretnej potrawy. |
| Racje/składniki `R01–R10` | 10 | Różne racje, części racji i ujęcia; referencja odpowiada rzeczywistemu wariantowi/opakowaniu. Niepotwierdzone dopasowania źródeł pozostają jawne. |
| Nieczytelne `U01–U04` | 4 | Rzeczywista nieostrość/zasłonięcie/oświetlenie uniemożliwiające identyfikację; stan czytelności ocenia człowiek przed call. |
| Razem | 30 | Minimum; bez pozornego mnożenia tych samych zdjęć. |

Zdjęcia nie pochodzą automatycznie z Downloads, Random Data, załączników lub
innych czatów. Zgoda na analizę aplikacyjną nie daje domyślnej zgody na corpus,
publikację zdjęcia lub kolejne profile testu. Zdjęcia/sekrety/raw responses pozostają
w prywatnym autoryzowanym miejscu poza Git i logami; w repo można opublikować
jedynie sprawdzony manifest/raport bez prywatnych treści. Backendowa retencja
obrazu do 24 h nie określa retencji Google ani przechowywania corpus przez O2.

## Pola rzeczywistego manifestu przed call

| Pole | Znaczenie i reguła |
|---|---|
| `case_id`, `group` | Stałe ID i jeden z czterech przekrojów; unikalność sprawdzana przed uruchomieniem. |
| `image_sha256`, rozmiar/format/wymiary | Hash dokładnych bajtów wysyłanych przez create oraz kontrola wejściowych limitów; bez publikowania lokalnej prywatnej ścieżki. |
| `legal_source`, `consent_evidence`, `approved_at` | Konkretne źródło/licencja lub uprawnienie oraz zgoda na wybrany provider, zakres testu i profil. |
| `readability`, oceniający/data/uzasadnienie | Czytelne albo nieczytelne, ustalone przed odczytem odpowiedzi modelu; bez późniejszego usuwania trudnych przypadków z mianownika. |
| `reference_main_components` | Lista głównych składników tej konkretnej fotografowanej potrawy/produktu, ustalona niezależnie od Gemini. |
| `reference_source` i locator/weryfikacja | Rzeczywista etykieta, opis przygotowania, przepis lub inny weryfikowalny dokument; nie generowany opis modelu. |
| `identification_rule` | Zamrożone nazwy/aliasy i zasada uznania głównego składnika; wariant/marka tylko przy niezależnym potwierdzeniu. |
| `reference_uncertainty` | Brak/niepewność źródła albo powiązania; nie zastępuje się ich zerem ani wymyśloną pewnością. |
| `manual_fallback_probe` | Ustalona niezależna próba ręcznego zapisu, która ma działać również po failure/cancel/invalid result. |

Dla zdjęć racji alternatywne warianty nie są sumowane; niezidentyfikowane produkty
nie stają się official. Katalog/etykiety i nutrition_v1 służą do niezależnej kontroli
struktur/jednostek/Decimal/null. Referencyjna identyfikacja nie oznacza, że masa
lub kcal widocznej porcji są znane dokładnie; wynik AI pozostaje szacunkiem.

## Wykonanie przez istniejący backend i wspólną pool

Każdy przypadek używa autoryzowanego create multipart ze świadomą zgodą,
UUID key/aktualną epoką, tego API, trwałego workera i wspólnej pool. Nie wykonuj
bocznego SDK/direct call lub referencyjnego countTokens poza limiterem.
Rezerwacje i permits obejmują preflight oraz generateContent. Budżet wynosi
8192 wejściowych/2048 wyjściowych tokenów, do dwóch generate prób po 45 s
w 120 s i 300 s deadline kolejki. Spacing i rozłożenie na doby wynikają z
potwierdzonych limitów O3; nie zakładamy darmowej liczby zapytań.

Manifest wykonania przypina dla każdego przypadku `analysis_id`, key operacji,
commit/profil/epokę, czas przyjęcia/zakończenia, state/error_code, modelVersion,
ograniczone zwalidowane usage i liczbę rzeczywistych prób. Hash oryginału i
prepared hash powinny być związane z przyjętym obiektem; brak publicznego
endpointu zdjęcia nie jest obchodzony przez listing storage.
Nie zapisuj raw provider response, sekretów lub obrazu w raporcie.

Unknown po możliwym dispatch kończy analizę bez automatycznego resend. Nowa
świadoma analiza ma nowy key/zgodę; jej wynik nie usuwa poprzedniej nieudanej
próby z raportu. Wyniki quota/timeout/failed zapisuje się per-case. Retry nie
jest drugim niezależnym zdjęciem ani sposobem zwiększania próbki.

## Ocena, liczniki i warunki PASS

Oceniający porównuje zwalidowaną propozycję z zamrożonymi referencjami, nie tworzy
referencji z tekstu Gemini. Dla czytelnego zdjęcia sukces identyfikacji wymaga
wszystkich wskazanych w jego `identification_rule` głównych składników. Nie
uznawaj samej zbliżonej liczby kcal lub confidence/high matching za sukces.
Sposób traktowania aliasów i składników dodatkowych musi być jawny w regule.

| Kryterium | Wymagany licznik raportu i granica |
|---|---|
| Identyfikacja czytelnych zdjęć | `identification_successes / readable_cases >= 90%`; pokaż dokładny numerator/denominator i per-case wynik. Przy 26 czytelnych przypadkach oznacza to co najmniej 24 sukcesy. |
| Blokowanie błędnej struktury | `invalid_structures_blocked / invalid_structures_observed = 100%`; brak obserwacji oznacza „brak przypadków”, a nie PASS 0/0. Kontrolowane błędne struktury/probes walidatora są opisane osobno od trafności live. |
| Ręczny wpis przy każdym wyniku | `manual_fallback_successes / executed_cases = 100%`, obejmując czytelne/nieczytelne, failure/timeout/quota/cancel i odmowę walidacji. |
| Pełność przekroju | Rzeczywiste minimum 30 opisanych legalnych zdjęć; rozkład 8/8/10/4 i wszystkie wyniki ujawnione. |

W planned corpus 26 przypadków ma reprezentować czytelne zdjęcia, a 4 ujęcia
nieczytelne. Czytelność rzeczywistych zdjęć potwierdza oceniający przed runem;
odstępstwa wymagają jawnej korekty corpus przed wysłaniem, z zachowaniem historii
wersji. Raport ma osobno liczbę zaplanowanych, wykonanych, niewykonanych,
czytelnych, nieczytelnych i terminalnych błędów. Niewykonane wejście nie jest
sukcesem. Nie zaliczaj pełnego E7-R przy niepełnym corpus albo nierozstrzygniętych
przypadkach. Nie sumuj wielokrotnych runów jako nowych zdjęć.

Raport per-case zawiera wynik każdej zamrożonej reguły, zidentyfikowane/brakujące
główne składniki, bezpieczny kod błędu, rezultat ręcznego fallbacku i dowód
usunięcia serwerowego zdjęcia. Zbiorczy raport rozdziela live reference,
unit/mock/fake transport, PG/storage, niezależny odbiór, CI, O1 APK i O3.
Niespełnienie kryterium wymaga jawnej poprawy profilu lub osobno zweryfikowanego
darmowego modelu i ponowienia na tym samym udokumentowanym zbiorze przez pool;
stare wyniki pozostają widoczne.

E7-R development PASS nadal nie otwiera funkcji AI dla użytkowników w Polsce.
Free-only wybór i bramka Paid Services dla EOG/CH/UK pozostają zgodnie z
[wymaganiami 11.6](../../WYMAGANIA_PROJEKTOWE.md#116-gemini-darmowe-api-limity-i-trwałość-zadań).
Pełny E7 wymaga oddzielnego odbioru O1 Room/outbox/APK i O3 środowiska/restore.
