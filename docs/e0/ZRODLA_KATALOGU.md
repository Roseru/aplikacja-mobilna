# Źródła katalogu i audyt próbki - osoba 2

Stan: 9 października 2026. Sprawdzono lokalny [materiał użytkownika](../materialy/racja_wojskowa_S-RG-1.source.json), bez zmiany oryginału. Jest to orientacyjna, niezweryfikowana próbka S-RG-1; nie dowodzi składu ARPOL WZ 1 ani WZ 4 WEGE. Data `checked_on` oznacza rzeczywisty odczyt tego dokumentu, nie potwierdzenie etykiety. Nie przypisano produktu do producenta na podstawie samej nazwy.

Uzupełnienie E2: [seed i eksport PostgreSQL](../../backend/data/demo/README.md) zachowują tę samą próbkę i proweniencję. Eksport/importer są działającymi mechanizmami opisanymi w [raporcie E2](../e2/RAPORT_E2.md); nie pozyskano nowych etykiet ani rekordów FDC i żaden oczekujący wpis nie otrzymał statusu verified. Poniższe braki nadal są bramką oficjalnego seeda E5.

## Rejestr źródeł i braki

| Materiał / produkt | Producent i wariant | Podstawa i identyfikator | Sprawdzenie i status | Do uzupełnienia |
|---|---|---|---|---|
| Próbka użytkownika, 22 pozycje | Producent nieznany, oznaczenie S-RG-1 | Lokalny plik powyżej; każda pozycja ma JSON Pointer w `source_locator`; założona podstawa: wymieniona ilość | 2026-10-09, niezweryfikowany | Etykiety, rynek, producent, warianty, jawna podstawa, instrukcje proszków |
| ARPOL WZ 1 | ARPOL, WZ 1 według wymagań | Adres karty zapisany w wymaganiach 11.4; etykiety składników niepozyskane | Nie sprawdzano zdalnie, oczekujące | Aktualny skład i kcal/B/T/W każdego składnika oraz data odczytu |
| ARPOL WZ 4 WEGE | ARPOL, WZ 4 WEGE według wymagań | Adres karty zapisany w wymaganiach 11.4; etykiety niepozyskane | Nie sprawdzano zdalnie, oczekujące | Jak wyżej |
| Banan, jabłko ze skórką, pomarańcza | Surowe części jadalne; konkretny rekord niewybrany | USDA FDC Foundation / SR Legacy, ID i wersja nieustalone | Nie sprawdzano, oczekujące | Trzy konkretne FDC ID, wersje, 100 g, data odczytu |
| Baton owocowo-zbożowy 35 g wybranej racji | Producent i wariant nieustalone | Brak etykiety | Nie sprawdzano, oczekujące | Etykieta i powiązanie z wybraną racją; próbka nie wystarcza |
| Coca-Cola Original Taste PL | Wariant wskazany w wymaganiach | 100 ml; adres karty w wymaganiach 11.4 | Nie sprawdzano zdalnie, oczekujące | Odczyt aktualnej polskiej karty/etykiety, kcal/B/T/W i data |

Wiersze oczekujące opisują pracę do wykonania, nie certyfikują źródeł ani wartości. Nie dodano fikcyjnych FDC ID, etykiet, dat sprawdzenia lub kalorii. E2 może korzystać z demo; oficjalny katalog jest bramką E5. Brak etykiet nie blokuje E0. Pełna lista pozycji docelowych jest w [wymaganiach 11.4](../../WYMAGANIA_PROJEKTOWE.md#114-katalog-początkowy-i-jednostki).

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
