# Integracja katalogu offline E2 z Androidem - osoba 2

Dokument przekazania O1/O3, 9 października 2026. Opisuje kontrakt dostawy O2 i pracę potrzebną w Androidzie. **Import do Room, instalacja APK i scenariusze urządzenia nie zostały wykonane w ramach tej dokumentacji.** Dowody backendu i importera referencyjnego należy czytać w raporcie E2. Pełny odbiór zespołowy E2/KO-30 wymaga osobnego dowodu O1.

Normatywny format: [schemat katalogu](../../contracts/schemas/catalog.schema.json), [typy wspólne](../../contracts/schemas/common.schema.json), [reguły E0](../e0/KONTRAKTY_I_INTEGRACJA.md), [wektory nutrition_v1](../../contracts/test-vectors/nutrition-v1.json). Pochodzenie i ograniczenia próbki: [audyt źródeł](../e0/ZRODLA_KATALOGU.md).

## 1. Dostawa demo dla O1

Źródłem katalogu jest PostgreSQL. Pakiet gzip jest eksportem danych z tej bazy, a po imporcie źródłem ekranów telefonu jest Room. O1 osadza pakiet oraz manifest w assets APK; pierwszy start nie potrzebuje konta, API ani sieci. Aktualizacja sieciowa jest opcjonalnym późniejszym przepływem tego samego formatu.

Artefakty przekazania: [gzip E2](../../backend/data/demo/export/base-pl.1.json.gz) i [manifest E2](../../backend/data/demo/export/manifest.json). Powstały przez rzeczywisty eksport PostgreSQL 17 i przeszły import referencyjny; fixture `contracts/examples/valid/base-pl.1.json.gz` nadal służy kontraktom E0. Eksport E2 ma ustaloną kolejność i zwarte UTF-8, dlatego jego bajty/hash różnią się od fixture'a E0.

| Parametr demo | Oczekiwana wartość z wejścia E0; musi zgadzać się z eksportem |
|---|---|
| package_id | `47bdff67-e58b-5437-919b-ec00159afbc5` |
| kind / release | `demo` / `1` |
| schema_version / min_reader_version | `1` / `1` |
| source_id | `571bc0bc-0ce2-57ca-b248-7dd43079bdda` |
| Liczności | 18 wersji produktów, 1 racja, 18 komponentów, 1 źródło |
| Rewizje danych | Produkty i racja: `revision=1`; dokładne UUID w eksporcie |
| SHA-256 gzip | `65f4aae8002fd5522d0edb4689e05682103b80fbe3e6dbc68f4bf02c645b2bef` |
| Rozmiary gzip / JSON | 3099 B / 15691 B |
| Komenda importera referencyjnego | Poniżej; działa bez DATABASE_URL i sieci |

Po `uv sync --project backend --locked` z katalogu nowego checkoutu, utwórz lokalny ignorowany `backend/var`:

```text
uv run --project backend --locked python -m calorie_app.modules.catalog.offline_import --database backend/var/catalog.sqlite --manifest backend/data/demo/export/manifest.json --package backend/data/demo/export/base-pl.1.json.gz --expected-package-id 47bdff67-e58b-5437-919b-ec00159afbc5 --expected-kind demo
```

Po instalacji wheel poza repo komenda pozostaje `python -m calorie_app.modules.catalog.offline_import`, ze ścieżkami do przekazanych lokalnych plików. [Importer](../../tools/offline_catalog/README.md) udostępnia też osobne trwałe `stage` i `activate` do prób restartu/wyścigu.

Demo S-RG-1 ma `status=unverified` i `complete=false`. Nie jest specyfikacją ARPOL WZ 1/WZ 4 WEGE ani zweryfikowaną etykietą. 18 policzalnych pozycji pochodzi z próbki 22 pozycji żywności; 4 bez danych pozostają w `excluded_items`, podobnie wyposażenie. Trzech pozycji w sztukach bez masy nie przeliczamy na g. Sól/pieprz wymagają ilości i danych. Źródłowe 3466, 3468 i 3600 kcal są osobnymi deklaracjami; nie dopasowujemy do nich danych.

Demo dostarczamy lokalnie. Publiczne API E2 obsługuje wyłącznie opublikowany zaufany pakiet `official`. Przy samym demo lista `/api/v1/rations` jest pusta, a szczegół racji, manifest i plik dają 404. Nie istnieje publiczne obejście `include_demo=true`. `/products` i `/products/{id}` pozostają chronione i są podłączane z prawdziwym OIDC dopiero w E3; podstawowy katalog gościa pochodzi z APK/Room.

## 2. Rzeczywisty stan gałęzi O1

Odczytano `origin/codex/android-offline-racje` przez `git show`, bez przełączania, scalania ani edycji Androida. Sprawdzony commit: **`f5aabfc3aa4ed189a4fa3d9ad245a71faeff46d2`**. Jest to Android `0.2.0`, Room schema `2`. Odczyt objął `android/README.md`, `core/Nutrition.kt`, `data/Database.kt`, `data/DiaryRepository.kt` i assets katalogu. README deklaruje testy obecnego lokalnego przepływu; ich wykonania ani zgodności przyszłego adaptera E2 ten odczyt nie potwierdza.

`initialize()` czyta dwa nieskompresowane pliki `catalog/products-v1.json` oraz `catalog/rations-v1.json` przez `JSONObject` po `readText()`. Korzenie mają `version`, tekstowe `source` i listę `products`; racje dodatkowo `rations`. Produkty mają robocze `id`, `name`, liczby JSON `kcal/protein/fat/carbs`, `defaultGrams`, `category`. Składnik racji ma `id`, `productId`, `packageGrams`; kolejność powstaje z indeksu tablicy **0..N-1**. Oba zestawy A/B są osobnym demonstracyjnym katalogiem Androida, nie nowym demo S-RG-1.

Room ma `products`, `rations`, `ration_components`, `meals`, `meal_items`, `goals`, `outbox`. Nutrition i ilości są `Double`/SQLite `REAL`; katalog ma `catalogVersion`, ale nie exact ProductRef ani generację pakietu. Seed używa `OnConflictStrategy.IGNORE`. Historia kopiuje wartości per100 przy spożyciu, co pozwala zachować stare obliczenia, lecz nie przechowuje rewizji produktu, g/ml ani pełnego pochodzenia. Zapis racji i outbox jest transakcyjny. Outbox jest lokalny: używa m.in. `grams`, JSON number, `local_revision` i roboczych ID, a nie payloadów E0. Kod nie wysyła kolejki na serwer. README wskazuje brak uprawnienia INTERNET i konieczność adaptera gzip/manifest/UUID/BigDecimal.

## 3. Adapter i migracja Room po stronie O1

| Obecny format | Adaptacja zgodna z E0/E2 |
|---|---|
| Robocze `basic-*`, `demo-ration-*`, `guest-initial-goal` | Zachować stare rekordy i snapshoty; jawne trwałe mapowanie dawnych ID, jeśli potrzebne. Nowy katalog używa UUID. Nie utożsamiać produktów przez nazwę/kcal ani racji A/B z S-RG-1; nie wysyłać dawnych ID na API |
| `catalogVersion`, jeden rekord na product ID | Oddzielić `package_id+release`, `schema_version`, wersję czytnika, Room schema oraz `product_id+revision` i `ration_id+revision`. Członkostwo generacji wskazuje dokładne wersje |
| `OnConflictStrategy.IGNORE` | Identyczna wersja jest no-op, inna treść pod tym samym UUID+revision jest błędem całego importu. `IGNORE` bez porównania treści ukrywa konflikt |
| `Double`/REAL i JSON number | Kotlin `BigDecimal` od wejścia string; dokładny tekst w Room. Dawną reprezentację konwertować osobną udokumentowaną migracją (do 6 miejsc HALF_UP), zachowując oryginalny snapshot/audyt, bez twierdzenia, że odzyskano utraconą precyzję |
| `kcal: Double`, nullable makra; null całej sumy przy jednym braku | Wszystkie cztery pola Nutrition wymagane i nullable. Dla każdego makra/energii osobno `known_sum`, `missing_count`, `complete`; `null` to nieznane, `"0"` to znane zero |
| `defaultGrams`, `packageGrams`, tylko g | `basis_unit` g/ml, `package_quantity` oraz ilość komponentu z jednostką. Ilość opakowania nie jest podstawą per100. Konwersja g↔ml tylko z dodatnią gęstością i source_id |
| Komponent ma własny roboczy ID i indeks od 0 | E0 identyfikuje komponent w obrębie dokładnej wersji racji przez `position` **1..N**; zachować `group`, `optional`, exact `product` i `quantity`. Wewnętrzny klucz Room może zawierać ration UUID+revision+position |
| Tekstowe source bez źródła rekordu | Zachować tabelę źródeł, source_id/locator/status, aliasy, brand/variant, przygotowanie, kompletność oraz excluded_items. Brak metadanych nie oznacza weryfikacji |
| Snapshot spożycia bez product revision | Nowe wpisy kopiują pełny snapshot, exact ProductRef, ilość/jednostkę, podstawę, Nutrition, pochodzenie, gęstość/źródło i `nutrition_v1`. Nowa rewizja katalogu nie przelicza historii |
| Plaintext assets, brak aktywnej generacji | Jeden adapter pakietu APK/pobrania: ograniczony odczyt, walidacja, staging nieaktywnej generacji i atomowa aktywacja. Dziennik i outbox pozostają poza zastępowanym katalogiem |

Migrację ze schematu 2 należy przetestować na rzeczywistym poprzednim schemacie i reprezentatywnych danych, z kopią przed migracją. Nie używać destructive fallback. Zachować posiłki, cele, tombstones i wszystkie operacje outbox. Wysłanych w przyszłości operacji nie przepisywać w miejscu; lokalne liczniki rewizji pozostają osobne od serwerowych base_revision i epoki. Sync oraz nowe tożsamości kont należą do E3/E4; adapter katalogu E2 nie może udawać ich implementacji.

## 4. Walidacja i aktywacja pakietu

1. O1 konfiguruje oczekiwany `package_id` i `kind` osobno dla demo z APK i zaufanego official. Samo pole `kind` ani poprawny SHA-256 nie potwierdza autentyczności. Dostawę uwierzytelnia podpis APK lub zaufany kanał HTTPS. Nie pobierać URL z rekordów źródła.
2. Sprawdzić obsługę `schema_version=1` i `min_reader_version=1`. Ograniczyć odczyt gzip do **10 485 760 B**, rozpakowanie UTF-8 JSON do **52 428 800 B**; nie tworzyć nieograniczonego obiektu przed sprawdzeniem limitów. Hash manifestu dotyczy dokładnych bajtów gzip. Wymagać zgodności rzeczywistych rozmiarów, metadanych, source_ids i liczności manifestu oraz pakietu.
3. Odrzucić uszkodzony/ucięty gzip, zduplikowane klucze JSON, UUID/revision i źródła, niekanoniczne Decimal, JSON number w polach Decimal, NaN/Infinity, niepoprawne jednostki i niedodatnie ilości. Pole nullable nadal musi istnieć. Limity: 10 000 wersji produktów, 1000 racji, 100 000 komponentów, 10 000 źródeł; obowiązują również pozostałe ograniczenia schematu.
4. Zweryfikować pełny graf: dokładne referencje produktów i źródeł, pozycje komponentów 1..N, liczności, wymaganą proweniencję gęstości. Official dodatkowo wymaga pełnych danych i zweryfikowanych źródeł. Nie zamieniać null na zero ani unverified na verified.
5. Zapisać zwalidowane dane do nieaktywnej generacji. W krótkiej transakcji ponownie porównać aktywny release i aktywować tylko kompletny nowszy release tej samej tożsamości pakietu. Identyczne ponowienie jest no-op; spóźniony starszy import nie zastępuje nowszego.
6. Przerwanie, restart, błąd i brak miejsca pozostawiają dotychczasową kompletną generację. Nie kasować wersji przypiętych do historii lub outbox. Zachować poprzednie snapshoty; sprzątanie nie może naruszać referencji.

Manifest `path` ma wyłącznie `base-pl.<release>.json.gz`, bez hosta, `..` i parametrów. Dla HTTP O3/O1 zachowują `Content-Type: application/gzip`, zgodny `Content-Length` i brak `Content-Encoding: gzip`, aby klient liczył hash pobranych skompresowanych bajtów. Publiczne adresy official mają stabilną tożsamość package_id ustaloną przez O2/O3; nowego package_id nie podstawia się po cichu pod te same URL.

## 5. Obliczenia i prezentacja części racji

Użytkownik wybiera tylko rzeczywiście zjedzone komponenty. Początkowo nic nie jest zaznaczone, `optional` i `group` nie oznaczają spożycia. Ilość wybranej części nie przekracza ilości komponentu racji. Pozostałe pozycje nie są tworzone jako MealItem z zerem. Niepoliczalne `excluded_items` są informacją o niekompletności, a nie zerowym spożyciem. Proszki pozostają w g suchego produktu bez potwierdzonej instrukcji przygotowania.

`nutrition_v1`: dokładne BigDecimal `wartość_per100 × ilość / 100`. Przy g↔ml potrzebna udokumentowana gęstość; ogólne dzielenie ma skalę 12 i HALF_UP, następne mnożenie dokładne. Nie obcinać obliczonego wyniku do 6 miejsc. Kcal i makra sumujemy przed zaokrągleniem; prezentacja dopiero na końcu: kcal do integer i makra do 0,1 g HALF_UP. Nie przeliczać energii ze wzoru 4/4/9.

| Przypadek O1, wspólny z E0 | Oczekiwany wynik |
|---|---|
| Połowa komponentu A/1: 150 g, 87 kcal/100 g | `130.5` kcal, prezentacja `131`; B/T/W `16.5/4.95/4.35` g |
| Powyższa połowa plus 25 g A/3 po 330 kcal/100 g | `213` kcal; B/T/W `18.5/5.5/20.7` g; pozostałe niezaznaczone |
| Syntetyczny napój 250 ml po 42 kcal/100 ml | `105` kcal bez konwersji na g |
| Suchary demo: 90 g po `385.555556` kcal/100 g | `347.0000004` kcal, prezentacja `347` |
| Całość 18 normalizowanych porcji demo | `3466.00000145` kcal, prezentacja `3466`; racja nadal niekompletna |
| null i zero | Znane zero uczestniczy w sumie; null zwiększa missing_count i nie jest zerem |
| Ilość niezgodna z podstawą bez gęstości | Konwersja blokowana, pozostałe zgodne pozycje nadal policzalne |

Wszystkie przypadki i dokładne oczekiwane makra są w wektorach E0. O1 uruchamia te same wejścia w Kotlinie; wynik Python/SQLite nie zastępuje tego dowodu. Dawny przypadek Androida „50 g konserwy + 22,5 g sucharów = 222 kcal” dotyczy zestawu A z jego dawnymi wartościami i nie jest oczekiwanym wynikiem nowego demo.

## 6. Osobny odbiór Room/APK — do wykonania przez O1

| Scenariusz | Wymagany dowód O1 |
|---|---|
| Pierwszy start APK bez sieci | Zainstalowana wskazana wersja APK, tryb samolotowy przed pierwszym startem, zgodny hash assets, import i dostępność 18 produktów/1 racji w Room bez API/konta |
| Części racji i restart | Wybór połowy i części innego składnika; zgodne wyniki wektorów, zapis jednego Meal z wybranymi elementami; restart zachowuje wpis i snapshot |
| Walidacja wyboru | Pusty wybór i ilość ponad komponent blokują zapis; obrót/odtworzenie aktywności zachowują poprawny wybór; baton opcjonalny nie jest automatycznie zjedzony |
| Migracja ze schematu 2 | Rzeczywisty stary plik Room, posiłki/cele/outbox/tombstones przed i po aktualizacji APK; brak utraty danych, zachowana stara wartość historyczna i mapowanie roboczych ID |
| Aktualizacja i przypięte rewizje | Nowy release zmienia aktywny katalog; wcześniej zapisany posiłek nadal wskazuje dawną wersję i zachowuje wartości; powtórny import bez duplikacji |
| Wadliwa dostawa | Hash, gzip, nadmiar rozmiaru/liczności, zduplikowane klucze/ID, obcy package_id, zły reader/schema, Decimal, referencje i gęstość odrzucane bez zmiany aktywnego katalogu |
| Awaria staging/aktywacji | Przerwanie procesu przed przełączeniem, restart, symulacja braku miejsca i rollback; poprzedni katalog, historia i outbox pozostają kompletne |
| Wyścig dwóch importów | Nowszy release kończy pierwszy, starszy ostatni; aktywny pozostaje nowszy. Inna treść tego samego release/UUID+revision odrzucona |

O1 dołącza commit Androida, wersję i SHA-256 APK, wersję urządzenia/emulatora, pakiet i manifest, wyniki Kotlin/Room/UI oraz logi awarii bez prywatnych danych. Odczyt gałęzi, testy O2 i importer referencyjny nie są wykonaniem tej tabeli.

Komendy istniejącej gałęzi O1 z katalogu `android/` (wymagają JDK 17/21, SDK 35 i emulatora/urządzenia):

```powershell
.\gradlew.bat :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
.\gradlew.bat :app:connectedValidationAndroidTest
```

O1 rozszerza zestaw o scenariusze adaptera E2. APK debug trafia do `app/build/outputs/apk/debug/app-debug.apk`. Istniejąca aplikacja testowa `pl.roseru.kalorie.validation` służy izolacji od zwykłego dziennika `pl.roseru.kalorie`; nie testować migracji kosztem danych użytkownika.

## 7. Obowiązki O3 i granice odbioru

Publiczne official v1 ma stałe package_id **`c12631e2-1a02-547c-a7f9-ebf87bb42e55`** w kodzie kontraktu; O3 nie przełącza go konfiguracją. Inny package_id wymaga nowego jawnego kanału/kontraktu. `CATALOG_ARTIFACT_ROOT` wskazuje trwały magazyn: operator zapisuje, API czyta ten sam filesystem obsługujący hard link/fsync. Nie wystawiać magazynu jako publicznego statycznego mountu. Magazyn rozdziela `kind/package_id`, nawet gdy basename demo i official jest taki sam; opublikowane bajty pozostają niezmienne, a starsze release dostępne. Najpierw trwały kompletny plik, potem transakcyjna publikacja metadanych; manifest nie wskazuje pliku częściowego. Bez prawdziwych etykiet demo pozostaje lokalnym materiałem, a oficjalny seed jest bramką E5.

Migracje uruchamia oddzielny migrator dla PostgreSQL 17, baza `calorie_app`, schemat `app`. API i worker nie mają DDL; Keycloak ma własną bazę i rolę. O3 przekazuje sekrety środowiskiem, nie w APK/repo; komendy importu/eksportu/publikacji i aktualny head migracji podaje dokumentacja backendu E2. CLI operatora nie jest publicznym endpointem. Kopie obejmują DB i opublikowane artefakty. O3 zapewnia HTTPS, poprawne nagłówki pobierania, CI dla rzeczywistego obrazu oraz współpracuje z O1 przy buildzie i testach urządzenia.

O2 odpowiada za ścieżkę PostgreSQL → eksport → manifest/gzip → referencyjny SQLite, walidację i dowody backendu. O1 odpowiada za BigDecimal, migrację Room, adapter pakietu, działające APK i scenariusze powyżej. O3 odpowiada za środowisko, sekrety, trwały magazyn, dostawę i kontrole infrastruktury. Dopóki nie ma dowodów O1, właściwy status brzmi: **„część O2 gotowa po jej odbiorze; integracja O1 oczekuje”**, a nie pełne E2/KO-30.
