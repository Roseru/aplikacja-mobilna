# Kontrakty E0 i walidacja - osoba 2

Status: schematy i przykłady E0 oraz **design draft przyszłych operacji**. Wdrożone operacje health, katalog E2 i tożsamość/odczyty E3 opisuje wyłącznie [OpenAPI backendu](../backend/openapi.json), generowane z FastAPI. Przykłady demo opisują kształt payloadów i lokalną integrację; nie stanowią oficjalnego katalogu żywności ani publikacji kanału official. [Decyzje i przekazanie](../docs/e0/KONTRAKTY_I_INTEGRACJA.md), [sync](../docs/e0/SYNCHRONIZACJA.md), [źródła](../docs/e0/ZRODLA_KATALOGU.md), [raport odbioru E0](../docs/e0/ODBIOR.md).

| Ścieżka | Zawartość i status |
|---|---|
| [openapi/design-v1.yaml](openapi/design-v1.yaml) | Przyszłe HTTP OpenAPI3.1.1; definicje przez lokalne `$ref`, przykłady i błędy. Zawiera przyszłe operacje E4/E5; siedem wdrożonych operacji E3 usunięto z aktywnego draftu |
| [backend/openapi.json](../backend/openapi.json) | Generowane OpenAPI3.1.0 FastAPI: health oraz publiczne `/api/v1/rations`, `/rations/{id}`, `/offline-package/manifest`, `/offline-package/{filename}`. Obejmuje także bootstrap/me/goals/consents/energy-estimates/products E3 z bearerAuth. Wdrożone operacje usunięto z aktywnego design draft |
| [schemas/common.schema.json](schemas/common.schema.json) | UUID, daty, IANA, kanoniczne Decimal, ilości i nullable Nutrition |
| [schemas/domain.schema.json](schemas/domain.schema.json) | Prywatne payloady, snapshot posiłku, cele, kalkulator, zgody i odczyty |
| [schemas/catalog.schema.json](schemas/catalog.schema.json) | Product/Ration/Source, pełny Package i Manifest; format offline ma własne wersjonowanie |
| [schemas/sync.schema.json](schemas/sync.schema.json) | Typowane kontenery push/pull, cztery wyniki, odzyskiwanie i format scenariuszy |
| [schemas/fixtures.schema.json](schemas/fixtures.schema.json) | Ścisły rejestr przykładów i struktura wspólnych wektorów testowych |
| [examples/valid](examples/valid) | Przykłady integracyjne i mały rzeczywisty gzip; demo o osobnym package_id, niepełna/niezweryfikowana S-RG-1 |
| [examples/invalid](examples/invalid) | Celowo błędny schemat lub semantyka fixture’a, oczekiwany powód w indeksie |
| [examples/scenarios](examples/scenarios) | Poprawne komunikaty i opis oczekiwanego przyszłego zachowania; konflikty serwera nie oznaczają niepoprawnego JSON |
| [examples/index.json](examples/index.json) | Rejestr każdego JSON przykładu; wynik lokalny, warstwa błędu, przyszły etap; osobny status materiału źródłowego |
| [test-vectors/nutrition-v1.json](test-vectors/nutrition-v1.json) | Wspólne wejścia i ręcznie ustalone wyniki Decimal/BigDecimal wraz z rachunkami; wykonanie Kotlin należy do O1 |
| [tools/contracts](../tools/contracts) | Mały walidator i rozdzielone checkery artefaktów, pyproject/uv.lock; nie zawierają ORM, endpointów ani symulatora sync |
| [docs/e0](../docs/e0) | Decyzje, relacje, adaptacje Androida, konfiguracja O3, protokół sync, źródła i jawny odbiór |

## Uruchomienie

Jedna komenda z katalogu repozytorium w PowerShell:

```powershell
.\tools\contracts\validate.ps1
```

Skrypt wybiera `uv` z PATH albo lokalne `.tools/uv/bin/uv.exe`, uruchamia `uv run --project tools/contracts --locked --offline --cache-dir .uv-cache python tools/contracts/validate.py` i propaguje błąd. Działa bez sieci po przygotowaniu zależności. Bezpośredni odpowiednik na Linuxie/macOS: to samo polecenie `uv run` z katalogu repozytorium.

Pierwsze przygotowanie nowego checkoutu (wymaga sieci): uv**0.9.5** i Python**3.13**, następnie:

```plaintext
uv sync --project tools/contracts --locked --python 3.13 --cache-dir .uv-cache
```

`uv.lock` przypina także zależności przechodnie. Bez uv lub bibliotek kontrola kończy się błędem; nie pomija testów. Narzędzie technicznie dopuszcza Python3.12–3.13, backend nadal wymaga3.13. W tej sesji wykonano na3.13.9, z uv0.9.5 zainstalowanym lokalnie w ignorowanym `.tools/`; `.venv` i cache nie są artefaktami do wersjonowania. Nie trzeba Docker/PostgreSQL/Keycloak/Gemini.

Kontrola obejmuje przyszłe OpenAPI3.1.1 i generowane OpenAPI3.1.0, brak podwójnych aktywnych operacji, zachowanie auth produktów w E3 oraz wszystkie przykłady kształtu przeniesionego katalogu. Sprawdza je równolegle względem wygenerowanych response schemas i normatywnych JSON Schema2020-12. Przykład błędu429 pozostaje kontrolą wspólnego formatu błędów przyszłej warstwy limitowania; nie deklaruje wdrożenia tej odpowiedzi w E2. Pobranie wymaga `application/gzip`, właściwego `Content-Length`, ograniczonej nazwy pliku i braku `Content-Encoding`.

Pozostałe kontrole obejmują wszystkie lokalne `$ref`, UUID/daty/IANA, oczekiwane odrzucenia, brak osieroconych przykładów, semantykę domeny/katalogu, gzip/hash/manifest, wektory Decimal, struktury scenariuszy sync, linki lokalne (także backend, E1/E2 i importer referencyjny) oraz `git diff --check`. Ten walidator nie wykonuje transakcji serwera, migracji ani kodu Kotlin; dowody backendu E2 są osobnym wynikiem testów. Szczegółowy dowód E0 oraz zakres przyszłych testów zawiera raport odbioru E0.

Materiał użytkownika pozostaje w [oryginalnym pliku źródłowym](../docs/materialy/racja_wojskowa_S-RG-1.source.json); jego hash kontroluje indeks. Znormalizowany katalog jest oddzielnym przykładem. Zmiana bajtów demo wymaga ponownego przygotowania gzip i manifestu; walidator **nie naprawia** plików w trakcie testu.

## Tożsamość i odczyty E3

Bootstrap/me/goals/consents/energy-estimates/products przejęto do generowanego OpenAPI, usuwając z aktywnego draftu. Kontrakt błędów obejmuje account_bootstrap_required, account_deleting oraz zmianę epoki/generacji bootstrapu w kontrolowanym details. [Integracja O1](../docs/e3/INTEGRACJA_O1.md) opisuje kolejność bootstrapu, receipts, Decimal i tokeny stron. nbf jest opcjonalny; obecny podlega kontroli czasu. JWKS/role oraz rzeczywisty PKCE opisuje [konfiguracja O3](../docs/e3/KONFIGURACJA_O3.md).
