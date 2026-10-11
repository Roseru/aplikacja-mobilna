# Dziennik poszukiwań — 11.10.2026

Autor: Agent 2 / O2. Zakres: publiczne źródła WZ 1/WZ 4 WEGE i odpowiadających produktów. Przeczytano przykład MRE oraz nowszy audyt E5 na main; istniejące materiały pozostawiono.

| Poszukiwanie | Wynik i decyzja |
|---|---|
| ARPOL WZ 1 / WZ 4 WEGE | Odczytano aktualne karty kompletora; 1517/1433 kcal to deklaracje całych racji. Zachowano wszystkie 30 wystąpień żywności i przypraw. |
| Lazania, risotto, SU-1, mleko, orzeszki | Pobranie pięciu kart HTTP 200. Potwierdzono liczby wcześniejszego audytu; nadal brak dowodu powiązania producenta/wersji z paczką WZ. |
| Smoothie owocowe 50 g | Nowa karta ARPOL: banan/truskawka/pomarańcza, pełne kcal/B/T/W suchego produktu, 50 g + 150 ml zimnej wody, 1–2 min mieszania. |
| Izotoniki 5 g | Pobranie osobnych kart jabłkowej, malinowej i pomarańczowej. Każda ma 500 ml wody i te same opublikowane makra; zaznaczono rozbieżność kcal względem prostego oszacowania z makr. |
| Napój herbaciany 15 g | Pozyskano PDF z domeny specyfikacje.arpol.net.pl; 389 kcal/100 g i 250 ml zimnej wody. PDF zastrzega różnice zależnie od smaku; nie przypisano do wszystkich herbat. |
| Suchary 45 g | Pozyskano oryginalny PDF i obejrzano stronę po renderowaniu. PDF zawiera olej rzepakowy, karta HTML palmowy; nie połączono receptur. |
| Baton 35 g | Odczytano sześć smaków z jednej karty jako osobne alternatywy. Wariant gruszkowy ma niespójną parę kJ/kcal. |
| Kisiel jabłko/mango 30 g | Potwierdzono wcześniejszy problem 1644 kJ / 493 kcal, granice B/T i 150 ml zimnej wody. Nie zmieniono wartości źródłowych. |
| Czekolada do picia 25 g | Publiczna karta Ceneo waniliowej oraz oferta Allegro wiśniowej mają makra i instrukcję. Zapisano jako wtórne tropy, z nieustalonym producentem/powiązaniem; oferta wiśniowa miesza nazwy smaków. Nie pozyskano potwierdzonej karty producenta. |
| Drobne dodatki | Wyszukiwanie cukierków, kawy i gumy nie dostarczyło wiarygodnych kart identyfikujących sztuki WZ 1/WZ 4. Nie przeniesiono wartości z produktów podobnych ani mas ze starszych racji S-R/S-RG. |

Sprawdzono wyszukiwarkę dla nazw racji/produktów oraz domen ARPOL i specyfikacje.ARPOL, kategorie napojów i artykułów spożywczych, wyszukiwanie sklepu po „czekolada”, „herbaciany” i „cukierek”. Część wyników internetowych wskazywała stare lub niedostępne strony.

Bezpośrednio sprawdzone adresy czekolady waniliowej/wiśniowej i dwóch herbat z dawnych wyników zwróciły HTTP 404; dokładne URL i daty są w [manifeście](sources/manifest.json). Błąd pobrania nie oznacza, że produkt nie istnieje. Odczyt tekstu wtórnej oferty nie oznacza zbadania jej etykiety ani fizycznej racji.

Pobrano **13 kart HTML i 2 PDF-y**, zachowano SHA-256 pobranych bajtów. PDF-y mają po jednej stronie i zostały wizualnie sprawdzone. Nie kontaktowano dostawców, nie kupowano racji i nie importowano danych do aplikacji. Nie ogłaszamy wyczerpania wszystkich możliwych źródeł internetowych.
