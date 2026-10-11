# Źródła katalogu i audyt próbki - osoba 2

Stan bazowego audytu próbki: 9 października 2026. Aktualizacja źródeł E5-O2-R: 11 października 2026. Sprawdzono lokalny [materiał użytkownika](../materialy/racja_wojskowa_S-RG-1.source.json), bez zmiany oryginału. Jest to orientacyjna, niezweryfikowana próbka S-RG-1; nie dowodzi składu ARPOL WZ 1 ani WZ 4 WEGE. Data `checked_on` oznacza rzeczywisty odczyt tego dokumentu, nie potwierdzenie etykiety. Nie przypisano produktu do producenta na podstawie samej nazwy.

Uzupełnienie E2: [seed i eksport PostgreSQL](../../backend/data/demo/README.md) zachowują tę samą próbkę i proweniencję. Eksport/importer są działającymi mechanizmami opisanymi w [raporcie E2](../e2/RAPORT_E2.md); w E2 nie pozyskano nowych etykiet ani rekordów FDC. E5-O2-R poniżej dostarcza rzeczywiste odczyty źródeł; nie zmienia demo w official. Niezamknięte braki nadal są bramką osobnego E5-O2-C.

## Rejestr źródeł i braki

| Materiał / produkt | Producent i wariant | Podstawa i identyfikator | Sprawdzenie i status | Do uzupełnienia |
|---|---|---|---|---|
| Próbka użytkownika, 22 pozycje | Producent nieznany, oznaczenie S-RG-1 | Lokalny plik powyżej; każda pozycja ma JSON Pointer w `source_locator`; założona podstawa: wymieniona ilość | 2026-10-09, niezweryfikowany | Etykiety, rynek, producent, warianty, jawna podstawa, instrukcje proszków |
| ARPOL WZ 1 | Dostawca/kompletor ARPOL; producenci/wersje składników nieustalone | [Karta racji](https://arpol.net.pl/produkt/racja-wz-1/), odczyt i lista w [materiale E5](../../Random%20Data/E5_2026-10-11/ARPOL/ration_cards.json) | 2026-10-11: skład/masy i 1517 kcal całej racji odczytane; profile składników niekompletne | Powiązanie wszystkich etykiet z wariantami konkretnie kompletowanej racji i komplet kcal/B/T/W |
| ARPOL WZ 4 WEGE | Dostawca/kompletor ARPOL; producenci/wersje składników nieustalone | [Karta racji](https://arpol.net.pl/produkt/racja-wz-4-wege/), ten sam materiał E5 | 2026-10-11: skład/masy i 1433 kcal całej racji odczytane; profile składników niekompletne | Jak wyżej; smoothie50g, orzeszki i dodatki nadal wymagają konkretnego powiązania |
| Banan surowy | USDA, Bananas, raw | SR Legacy April2018; FDC173944 / NDB9040; 100g części jadalnej | 2026-10-11, pełny rekord pozyskany: kcal89 / B1.09 / T0.33 / W22.8g | Zachować zakres nutrient1005 i proweniencję; osobny official eksport/import w C |
| Jabłko surowe ze skórką | USDA, Apples, raw, with skin (Includes foods for USDA's Food Distribution Program) | SR Legacy April2018; FDC171688 / NDB9003; 100g części jadalnej | 2026-10-11, pełny rekord: kcal52 / B0.26 / T0.17 / W13.8g | Jak wyżej; nie zastąpić rekordem konkretnej odmiany jabłka |
| Pomarańcza surowa | USDA, Oranges, raw, all commercial varieties | SR Legacy April2018; FDC169097 / NDB9200; 100g części jadalnej | 2026-10-11, pełny rekord: kcal47 / B0.94 / T0.12 / W11.8g | Jak wyżej; nie przyjmować masy owocu ze skórką za spożytą część |
| Baton owocowo-zbożowy35g wybranej racji | ARPOL jako dostawca; producent i smak racji nieustalone | [Karta 6 wariantów](https://arpol.net.pl/produkt/baton-owocowo-zbozowy-35-g/) na100g, netto35g | 2026-10-11, wartości wariantów odczytane; powiązanie niepotwierdzone | Konkretna etykieta producenta/smaku występującego w WZ1/WZ4; dostępność sklepu nie dowodzi zawartości racji |
| Coca-Cola Original Taste PL | Coca-Cola, Original; polski rynek | [Polska karta](https://www.coca-cola.com/pl/pl/brands/brand-products-coca-cola),100ml | 2026-10-11: 180kJ/42kcal, B0/T0/W10.6g odczytane | Oficjalny eksport/import dopiero C; brak gęstości nie oznacza1g/ml |

Materiały trwałe: [zbiór E5 i ograniczenia](../../Random%20Data/E5_2026-10-11/README.md), [USDA źródło/wersja](../../Random%20Data/E5_2026-10-11/USDA/source.json), [3 pełne rekordy](../../Random%20Data/E5_2026-10-11/USDA/sr_legacy_selected_records.json), [Coca-Cola faktograficznie](../../Random%20Data/E5_2026-10-11/CocaCola_PL/source.json). Publiczny [ZIP USDA](https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_json_2018-04.zip) pobrano rzeczywiście bez klucza API; SHA-256 `0fe8ae486a2c8eb42cb96413f058deb51863a46c8fb8eeb4b1fb45006dd338ef`. Nazwy i ID odczytano z eksportu. `publicationDate=4/1/2019` FDC nie zmienia wersji SR Legacy April2018. Podstawa100g części jadalnej wynika z [dokumentacji SR Legacy, tabela6, strona12](https://www.ars.usda.gov/ARSUserFiles/80400525/Data/SR-Legacy/SR-Legacy_Doc.pdf). W oznacza tu źródłowy `Carbohydrate, by difference` (nutrient1005), nie domyślnie węglowodany przyswajalne z etykiety UE. Eksport JSON ma W22.8/13.8, więc nie uzupełniono dalszych cyfr innym źródłem. Żaden materiał nie został opublikowany jako kompletny official.

## Audyt komponentów ARPOL i dokładna bramka C - osoba 2

[Indywidualne karty kandydatów](../../Random%20Data/E5_2026-10-11/ARPOL/component_candidates.json) sprawdzono11.10.2026. Poniżej są wartości100g **konkretnych kart**, nie potwierdzone profile składników WZ1/WZ4. Nazwa/gramatura podobna do racji jest wskazówką do sprawdzenia, nie dowodem producenta/wersji; fotografie opisano jako poglądowe.

| Karta indywidualna / wariant | kcal / B / T / W g na100g | Co nadal wymaga dowodu |
|---|---|---|
| [Lazania300g TACKA](https://arpol.net.pl/produkt/lazania-300-g-tacka/) | 109 /6.8 /4 /11 | Racja mówi lazania300g, nie potwierdza tego opakowania/producenta |
| [Risotto pomidorowe WEGE300g TACKA](https://arpol.net.pl/produkt/risotto-pomidorowe-wege-300-g-tacka/) | 114 /2.6 /2.1 /20 | Jak wyżej dla WZ4 |
| [Suchary specjalne SU-1 45g](https://arpol.net.pl/produkt/suchary-specjalne-su-1-45-g/) | 386 /8 /6.8 /72.1 | Racje nie podają SU-1; osobna specyfikacja Suchary45g ma olej rzepakowy, karta sklepowa palmowy — potrzebna wersja etykiety |
| [Mleko zagęszczone słodzone150g](https://arpol.net.pl/produkt/mleko-zageszczone-150-g/) | 328 /7 /8 /57 | Powiązanie z tubą WZ1; PDF100g nie zastępuje identyfikacji150g |
| [Orzechy ziemne solone50g](https://arpol.net.pl/produkt/orzechy-ziemne-solone-50-g/) | 625 /24.6 /51.4 /12.6 | WZ4 nie podaje prażenia/solenia/producenta; w sklepie jest kilka50g wariantów |
| [Izotonik jabłkowy5g](https://arpol.net.pl/produkt/napoj-izotoniczny-jablkowy-5-g/) | 238 /0 /0 /44 | WZ1/4 nie podają smaku; karta5g mówi500ml wody, nie przypisać innym wariantom |
| Baton żurawinowy / wiśniowy / limonkowy | 384/5.54/9.1/66.4; 374/5.26/9.4/62.5; 387/5.53/9.8/66.3 | Smak i producent racji niepotwierdzone; nie sumować alternatyw |
| Baton gruszkowy / figowy / morelowy | 373/5.25/8.5/64; 367/5.54/13.3/56.3; 369/5.53/8.8/62.8 | Jak wyżej; karta gruszki1516kJ/373kcal jest wewnętrznie niespójna |
| [Kisiel jabłko/mango30g](https://arpol.net.pl/produkt/kisiel-jablko-i-mango-30-g/) | źródło1644kJ/**493kcal**, B<0.4, T<0.2, W97 | Korekta źródła/etykieta: kJ/kcal niespójne; nierówności B/T nie są dokładnym zerem ani granicą. Nie zmieniać samemu493 na393. Powiązanie smaku z WZ1 niepotwierdzone |

Karta kisielu podaje30g suchego produktu +150ml zimnej wody. Zachowujemy tę instrukcję wyłącznie dla odczytanego wariantu. Woda nie dodaje energii; nie zapisujemy150ml jako masy suchego kisielu. Zebrane daty najlepiej spożyć przed z kart nie są identyfikatorami faktycznie zakupionej partii racji.

Dokładne pozostałe braki E5-O2-C:

1. Dla WZ1: producent/wersja i dowód powiązania lazanii300g, sucharów45g, czekolady do picia25g, mleka w tubie150g, batonu35g, kisielu30g, izotonika5g. Dla czekolady nie pozyskano karty właściwego25g proszku. Dla kisielu dodatkowo poprawna energia oraz sposób reprezentacji wartości poniżej progu wymagają jawnego rozstrzygnięcia na podstawie etykiety.
2. Dla WZ4: jak wyżej dla risotta300g, sucharów45g, czekolady25g, orzeszków50g, smoothie50g, batonu35g i izotonika5g. Nie pozyskano właściwego profilu smoothie50g; profile podobnych owoców lub MRE nie zastępują go.
3. W obu racjach akcesoria **jadalne**: napój herbaciany owocowy instant15g, kawa naturalna1szt., cukier2szt., cukierki wit.C2szt., guma1szt., cukierek kawowy1szt., sól1szt. i pieprz1szt. — brak konkretnego producenta/wersji, kcal/B/T/W i (dla sztuk) masy jednostkowej. Nie zamieniać na0 ani pomijać pod nazwą akcesoria. Brak instrukcji herbaty/proszków pozostaje jawny.
4. Powiązania wymagają konkretnej partii/etykiet lub jednoznacznej dokumentacji dostawcy. O2 zbiera i mapuje źródła; materiał niepubliczny/zdjęcia właściwych opakowań może dostarczyć właściciel albo ARPOL po osobnym upoważnieniu do kontaktu. Sam audyt nie wysyła wiadomości do dostawcy.
5. Po pozyskaniu kompletu: osobno zwolnione C tworzy official seed z proweniencją/stabilnymi ID, eksport/import, manifest/hash i dowody KO-01–02/KO-30. O1 wykonuje własną instalację/Room/APK/KO-31, O3 potwierdza HTTPS/konfigurację/artefakty; R ani plik źródeł ich nie poświadcza.

Nie rozdzielamy1517/1433kcal na składniki ani nie dopasowujemy sum. [Specyfikacja SU-1](https://specyfikacje.arpol.net.pl/Suchary_45g.pdf) odczytana w audycie wyszukiwania ujawniła różnicę składów; potrzebne jest potwierdzenie właściwej wersji, nie arbitralny wybór. [MRE2026 README](../../Random%20Data/MRE/README.md) przeczytano; materiały zachowano bez importu. Porcje MRE, alternatywy i dodatki nie zmieniają listy ARPOL.

## Audyt i założenie normalizacji

Źródło ma **22 pozycje żywności**: 6 śniadaniowych, 4 obiadowe, 4 kolacyjne i 8 dodatków. **4** nie mają wartości odżywczych: kawa 4 g, cukierki z witaminą C 3 szt., cukierki kawowe 3 szt. i guma 6 szt. Ostatnie **3** nie mają masy sztuki. Nie zamieniamy sztuk na gramy ani nieznanych danych na zero.

| Suma energii | kcal | Znaczenie |
|---|---:|---|
| Suma 18 źródłowych pozycji z danymi | 3466 | Obejmuje opcjonalny baton 174 kcal |
| Ta sama suma bez opcjonalnego batonu | 3292 | Nadal nie obejmuje czterech pozycji bez danych |
| Podsumowanie źródła | 3468 | Różnica +2 względem pozycji |
| Deklaracja racji w źródle | 3600 | Różnica +134 względem pozycji |

Sumy pozycji grup: śniadanie 926, obiad 799 (źródłowe podsumowanie 800), kolacja 882, dodatki z danymi 859 kcal. Źródłowe podsumowania i makra zachowuje niezmieniony materiał. Żadnej wartości nie dopasowano do deklaracji 3600. Suma jest audytem spisu, a nie deklaracją zjedzenia racji.

[Demo](../../contracts/examples/valid/catalog-demo.json) obejmuje wszystkie **18** pozycji z masą i wartościami. Przyjęto jawne założenie, że wartości źródłowe dotyczą ilości przy pozycji: `per_100 = source_value × 100 / source_mass_g`. To interpretacja do testów, nie potwierdzona podstawa etykiet. Normalizacja Decimal zaokrągla HALF_UP do 6 miejsc i usuwa końcowe zera; mnożenie gotowego katalogu nie odtwarza zawsze dokładnie liczby źródłowej. Przykładowo suchary: `347 × 100 / 90 = 385.555556` kcal/100 g, po przemnożeniu przez 90 g: `347.0000004`. Dopiero końcowa prezentacja energii daje 347 kcal. Odtworzenie całych 18 porcji z zaokrąglonego katalogu daje `3466.00000145` kcal, prezentowane jako 3466 kcal; suma źródłowa pozostaje osobną dokładną liczbą audytu.

Proszki i napoje instant pozostają w **g suchego produktu**, z informacją o nieznanej instrukcji przygotowania. Nie przypisano im ml gotowego napoju. Dwie pozycje „Pieczywo chrupkie” mają oddzielne UUID: taka sama nazwa nie dowodzi tożsamości produktu. Identyfikatory UUIDv5 demo pochodzą z przestrzeni `2ccbaad4-8912-4a95-a100-ac7707af0162` i źródłowych JSON Pointerów; są stabilne dla danego wystąpienia w niezmienionym materiale, ale nie certyfikują producenta. Zmiana źródła wymaga mapowania tożsamości i nowej rewizji, nie automatycznego ponownego numerowania.

`optional=true` na batonie zachowuje opcjonalność. `group` przechowuje układ śniadanie/obiad/kolacja/dodatki; żadna grupa nie tworzy wpisu dziennika. Użytkownik wskazuje faktyczne spożycie. Cztery pozycje żywności pominięte w obliczeniach i wszystkie osiem pozycji wyposażenia są w `excluded_items`, z nazwą, lokatorem, ilością/jednostką źródłową i przyczyną. Siedem pozycji to wyposażenie niejadalne. „Sól i pieprz” są osobno sklasyfikowane jako `seasoning`: wymagają ilości i danych, nie oznaczają automatycznie zerowych kcal. Demo ma `complete=false` i `status=unverified`.

## Format dostawy i aktywacja

[Schemat](../../contracts/schemas/catalog.schema.json) ma wspólne definicje Package, Manifest, Product, ProductRef, Ration i Source. Korzeń wskazuje Package. [Rzeczywisty fixture gzip](../../contracts/examples/valid/base-pl.1.json.gz) powstał przez `gzip.compress(raw, mtime=0)` w Pythonie 3.13.9 z dokładnych bajtów demo JSON; sprawdzono rozpakowanie i zgodność hasha. Manifest zawiera hash **bajtów gzip**, rozmiary, źródłowe UUID i te same nagłówki/liczności co pakiet. W pakiecie brak hasha własnej treści: zapobiega to samoodniesieniu. `schema_version=1`, `min_reader_version=1` są niezależne od wersji Room; `release` rośnie dla danego `package_id`. Demo i oficjalny katalog mają różne package_id; importer oficjalny musi sprawdzić przypisanie ID/kind do zaufanego kanału. Samo pole `kind` nie jest dowodem autentyczności.

Limity: gzip 10 MiB, JSON 50 MiB, 10 000 wersji produktów, 1000 racji, 100 000 składników łącznie. Technicznie ograniczono także źródła do 10 000. `path` dopuszcza wyłącznie `base-pl.<release>.json.gz` pod zatwierdzonym endpointem HTTPS, bez hosta, `..`, parametrów ani przekierowania na dowolny host. Każda referencja wskazuje dokładną parę UUID/rewizja; `position` musi tworzyć kolejność 1..N. Źródło gęstości jest wymagane przy g↔ml, a nie przy ilości zgodnej z podstawą.

Przed aktywacją O1 kontroluje rozmiary strumieniowo, hash, nagłówek, obsługę czytnika, schemat, referencje, unikalności, liczności i jednostki. Istniejący UUID+rewizja z inną treścią odrzuca import. Dane trafiają do nieaktywnej generacji Room. W jednej transakcji ponownie sprawdza się release i przełącza aktywną generację wyłącznie na nowszą. Dziennik/outbox pozostają zachowane; wersji przypiętych do historii lub niewysłanych operacji nie wolno sprzątać. Restart lub błąd pozostawia kompletną poprzednią generację. To kontrakt do E2/O1, nie zaimplementowany importer.

Lokalny checker odrzuca niekompletny lub niezweryfikowany pakiet `official`, brakujące referencje, duplikaty, złe liczności i konwersje bez gęstości. Nie zastępuje merytorycznej weryfikacji etykiet ani atomowej publikacji w PostgreSQL. Hash i manifest należy przeliczyć po każdej zmianie bajtów fixture'a; nie kopiować wcześniejszej sumy.
