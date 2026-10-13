# Runner referencyjny E7-R przez API aplikacji - osoba 2

`run.py` wykonuje zatwierdzony corpus przez istniejące API, trwały worker i wspólną
pool. Nie zawiera klienta Google, confirm, zapisu Meal/szkiców lub publikacji E6.
Aktualny odbiór live: **nie wykonano / WAITING_EXTERNAL**. Testy MockTransport
i syntetyczne obrazy sprawdzają transport/oracle, nie trafność Gemini.

## Wejścia i uruchomienie

Wymagany jest kompletny manifest opisany niżej, minimum 30 legalnych niesensytywnych
zdjęć, datowane potwierdzenie O3 i autoryzowane środowisko development Free Tier.
Konto użytkownika musi być wcześniej aktywne/bootstrapped w aplikacji; runner
najpierw odczytuje capabilities, potem powtarza bootstrap w celu związania konta,
generacji i epoki. O3 uruchamia worker i konfiguruje prywatny storage/pool/restore.
Runner nie tworzy klucza Gemini ani nie konfiguruje serwera.

Użyj Pythona ze środowiska backendu z zainstalowanym `calorie-backend` i HTTPX.
Z katalogu repozytorium, po dostarczeniu rzeczywistych wejść:

```powershell
backend/.venv/Scripts/python.exe tools/ai_reference/run.py --manifest C:/private/e7/corpus/manifest.json --output C:/private/e7/result --max-cases 1
```

Na Linux odpowiedni interpreter to `backend/.venv/bin/python`. Ścieżki powyżej
oznaczają prywatne katalogi przygotowane przez operatora; nie są dostarczonymi
artefaktami. Wywołanie bez wejść pozostaje WAITING_EXTERNAL. Nie uruchamiaj tej
komendy jako części CI ani do poszukiwania zdjęć/kluczy.

| Zmienna środowiskowa | Znaczenie |
|---|---|
| `E7_REFERENCE_API_URL` | Dokładny origin HTTPS API aplikacji, np. zatwierdzona przez O3 domena; bez userinfo/query/fragment/prefiksu ścieżki. |
| `E7_REFERENCE_TOKEN` | Ważny access token bieżącego konta, dostarczony poza argv/repo/logami. Runner nie pozyskuje i nie wypisuje tokenu. |
| `E7_REFERENCE_CA_BUNDLE` | Opcjonalny istniejący plik z zatwierdzonym prywatnym CA; TLS pozostaje włączony. |

HTTPX używa `trust_env=False`, weryfikacji TLS, braku redirects i implicit retry.
Bez CA stosuje systemowy zaufany zestaw. Adres providera Google jest odrzucany.
HTTP loopback jest dopuszczony wyłącznie przy wstrzykniętym HTTPX MockTransport
w testach; CLI nie ma przełącznika wyłączenia TLS lub wyboru fixture transportu.

`--output` jest obowiązkowym istniejącym absolutnym prywatnym katalogiem poza
każdym repozytorium Git. O3/operator przygotowuje POSIX owner=bieżący UID/0700
albo Windows protected DACL z dostępem tylko bieżącego SID, SYSTEM i lokalnych
Administrators, z dziedziczeniem dla plików. Pliki mają POSIX 0600 albo sprawdzane
Windows ACL. Runner sprawdza każdy komponent ścieżki, odmawia symlink/reparse
i nie zmienia ACL. Nie ustawiaj output na systemowy Temp lub cudzy katalog.

## Ścisły manifest v1

JSON UTF-8 ma do 256 KiB, brak duplicate keys/NaN/Infinity/NUL i depth do 20.
Top-level zawiera dokładnie `format_version`, `created_at`, `o3_confirmation`,
`o3_evidence_ref`, `expected_profile`, `cases`.
`format_version` wynosi `e7-reference-manifest-v1`. Daty są rzeczywistymi datami
UTC zakończonymi Z, nie przyszłymi. `o3_evidence_ref` identyfikuje rzeczywisty
datowany dowód operatora, bez sekretu.

`o3_confirmation` zawiera dokładnie `provider`, `project_id`, `environment_id`,
`model`, `confirmed_at`, `free_only`, `billing_disabled`, `development_only`,
`rpm`, `tpm`, `rpd`, `model_verified`, `quota_windows`, zgodnie z konfiguracją
backendu O3. Provider to gemini; cztery potwierdzenia bool muszą być true.
Nie wpisuj zgadywanych wartości puli. Project/environment IDs pozostają w prywatnym
manifeście. API nie udostępnia tych identyfikatorów; powiązanie rzeczywistego
projektu z wdrożeniem potwierdza O3.

`expected_profile` jest dokładnym publicznym `AnalysisProfile` z capabilities:
provider/model, prompt/schema/preparation/REST version i `mock_scenario=null`.
Runner porównuje go przed każdym uploadem oraz z create/GET/replay. Nieznany
profil albo model, którego O3 nie potwierdził, zamyka run.

Poniższy pusty szablon jest celowo **niewykonalny**, bez zdjęć, zgód i referencji:

```json
{
  "format_version": "e7-reference-manifest-v1",
  "created_at": null,
  "o3_confirmation": null,
  "o3_evidence_ref": null,
  "expected_profile": null,
  "cases": []
}
```

Każdy rzeczywisty `cases` zawiera dokładnie:

| Pole | Wymaganie |
|---|---|
| `case_id` | Unikalne ID do 40 znaków: litery ASCII/cyfry/myślnik/underscore. |
| `group` | `products`, `mixed`, `rations` albo `unreadable`. |
| `image` | Względna ścieżka z separatorami `/` w katalogu manifestu; bez `..`, root/drive/ADS/backslash lub symlink/reparse. |
| `image_sha256` | SHA-256 dokładnych zatwierdzonych bajtów; wszystkie hashe corpus są unikalne. |
| `legal_source` | Konkretne legalne źródło tej fotografii. |
| `consent` | Pola określone poniżej; zgoda na konkretny obraz i użycie referencyjne. |
| `reference` | Niezależna, zamrożona ludzka referencja określona poniżej. |

Corpus ma 30–100 przypadków, minimum 8 produktów, 8 dań mieszanych, 10 racji/składników
i 4 nieczytelne zdjęcia. Dla podstawowych 30 oznacza to dokładnie przekrój 8/8/10/4.
Nie używaj powielonych zdjęć. Wszystkie ścieżki/rozmiary/hashes są sprawdzane
przed pierwszym requestem; odczyt jest bounded do 5 MiB na obraz i pamięciowy.
Format JPEG/PNG/WebP jest wstępnie sprawdzany z bajtów, a pełny codec egzekwuje backend.
Przed uploadem hash jest sprawdzany ponownie. Runner nie zapisuje kopii obrazu,
raw body, EXIF ani raw provider response do output.

`consent` zawiera dokładnie: `accepted=true`, `reference_use_accepted=true`,
`nonsensitive=true`, `provider="gemini"`, `scope="this_photo"`, aktualny
`notice_version`, `approved_at` i opisowy `evidence_ref`. Zgoda dotyczy tego
testu/dostawcy; nie wywnioskuj jej z nazwy katalogu, załącznika lub istnienia pliku.
Narzędzie nie szuka materiałów w Downloads/Random Data/innych czatach.

`reference` zawiera dokładnie `readable` (bool), `criterion`, `source`,
`reviewed_at`, `reviewer`, `main_components`. Nieczytelne mają `readable=false`
i pustą listę składników. Pozostałe mają `readable=true` i 1–30 głównych składników.
Każdy składnik zawiera jedynie `label` i 1–20 `accepted_aliases`, zatwierdzonych
przez człowieka na podstawie konkretnego źródła. Aliasów nie może być zduplikowanych
ani współdzielonych przez różne składniki po NFKC/casefold/whitespace.

Oracle uznaje wyłącznie dokładną zgodność nazw z tymi aliasami po normalizacji,
bez fuzzy/substring, modeli lub tworzenia ground truth z odpowiedzi. Sukces
czytelnego przypadku wymaga wszystkich głównych składników. Masa/kcal pozostają
szacunkami i nie decydują o trafności identyfikacji. Dowolne tekstowe kryterium
wykraczające poza tę regułę musi być dodatkowo sprawdzone w manual review.

## Przyjęcie, ograniczenia i bezpieczne wznowienie

Każde wywołanie CLI jest świadomą autoryzacją najwyżej `--max-cases` następnych
przypadków manifestu: domyślnie 1, maksimum 10. Runner nie uruchamia automatyzacji
i nie omija limitu 10 zdjęć/konto/dobę UTC ani wspólnej puli. Wysyła jeden multipart
metadata/image ze zgodą i obecnym notice/provider; backend prowadzi worker,
preflight i generateContent. Nie ma bocznych provider/countTokens calls.

Przed wysłaniem trwale zapisuje key UUID, hash i kontekst w `state.json`.
Po 202 zapisuje analysis ID i przypięty profil, następnie polluje co 2 s z limitem
420 s (5 min kolejki + 120 s obsługi). Request ma bounded JSON do 1 MiB i timeout
do 15 s ograniczony pozostałym deadline. Błąd sieci nie ponawia requestu w tym
samym wywołaniu. 429 zatrzymuje cały run; operator respektuje Retry-After.
Unknown/safety/quota terminalny wymaga manual review, bez nowej analizy tego
zdjęcia lub automatycznego ponowienia u Google.

Ponowne świadome wywołanie z tym samym manifestem/output zachowuje run ID,
bootstrap key, operation key, SHA-256, konto/generację/epokę i profile:

- Brak ACK create: ponawia ten sam create/key/bajty, aby backend rozpoznał receipt.
- Znane analysis ID: wyłącznie GET tego samego ID; bez kolejnego uploadu.
- Zakończony przypadek: nie wysyła go ponownie; może przejść do kolejnego przypadku
  przy nowym wywołaniu operatora.
- Zmiana manifestu/API origin/profilu/konta/generacji/epoki: WAITING_EXTERNAL,
  bez automatycznego nowego key. O3/operator rozstrzyga kontekst i uzgadnia restore.

Nie usuwaj journalu, aby obejść odmowę lub resetować quota. Nowy referencyjny run
po jawnej zmianie profilu lub nowej zgodzie ma osobny prywatny output/manifest
i zachowuje poprzedni raport. Każdy failed/unknown pozostaje ujawniony.
Refresh tokenu w env dla tego samego konta nie zmienia tożsamości zlecenia.
OS lock zapobiega współbieżnym writerom; crash zwalnia lock, zachowując journal.
Zapisy są fsynced i atomowe, bez systemowego Temp.

## Raport i manual review

Output ma `state.json`, `report.json` oraz `run.lock`. `state.json` jest minimalnym
stanem do resume, nie kopią payloadu. Raport zawiera profile, manifest hash,
analysis IDs, stabilne codes/stany, model version i per-case porównanie do
niezależnych label/aliasów. Nie zapisuje raw odpowiedzi, tokenu, obrazów lub
prywatnych lokalnych ścieżek. Na stdout trafia jedynie status.

Liczniki obejmują numerator/denominator identyfikacji czytelnych zdjęć, completed/planned,
nieczytelne oraz błędne struktury zgłoszone i zablokowane przez backend. 0/0 ma
`invalid_structure_ratio=null`, nie fikcyjny PASS. Dla 26 czytelnych potrzebne
są minimum 24 sukcesy. `manual_fallback_verified=0` i `manual_review=required`
pozostają jawne: runner nie wykonuje confirm, sync ani ręcznego zapisu.
Ludzki odbiór/O1 musi dostarczyć dowody fallbacku i sprawdzić wynik kryterium.

Niepełne/odmówione wejścia: `WAITING_EXTERNAL` i exit 2. Pełny transport/ref
z osiągniętym progiem: `MANUAL_REVIEW_REQUIRED`; nieosiągnięty próg: `NOT_PASSED`.
Oba mają exit 3 i wymagają osobnego odbioru. Runner nigdy nie deklaruje końcowego
E7-R PASS, mock accuracy PASS, pełnego E7/APK lub wydania AI w EOG.
Wymagania i dowody wznowienia: [manifest E7-R](../../docs/e7/E7_R_MANIFEST.md).

## Weryfikacja narzędzia

`backend/tests/unit/test_e7_reference_runner.py` używa wyłącznie HTTPX MockTransport
i syntetycznych PNG generowanych w pamięci. Testowe pliki/ACL są tylko we własnym
basetemp; nie odczytuje istniejących prywatnych zdjęć/kluczy i nie łączy się z Google.
Testy sprawdzają manifest/zgody/unikalność/ścieżki, bounded IO, reference oracle,
privacy, multipart, lost ACK, resume, 429, profile/epoch/account i prywatny journal.

## Kwalifikacja offline zdjęć (13.10.2026)

[Pakiet propozycji](<../../Random Data/AI_REFERENCE_E7_R_2026-10-13/reference_proposals.json>)
i [raport przejścia](../../docs/e7/RAPORT_PRZYGOTOWANIA_ZDJEC.md) pozostają
NOT-RUNNABLE, bez human approval/consents/O3.
`python tools/ai_reference/validate_proposals.py` (Pillow) kontroluje spójność
publicznego pakietu; `python -m unittest discover -s tools/ai_reference -p
test_validate_proposals.py` sprawdza7 negatywnych/pending reguł offline.
Nie generuje manifestu, nie wywołuje API i nie daje E7-R PASS.
Ścisły runner i bramki pozostają bez zmian.
