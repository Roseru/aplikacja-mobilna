# Źródła katalogu E5, odczyt 11.10.2026 - osoba 2

To materiały źródłowe przyszłej bazy, wynik audytu E5-O2-R. Nie są seedem ani kompletnym katalogiem official. W E5-O2-C potrzebne jest osobne zlecenie, zamknięcie braków i eksport/import.

- [ARPOL — karty racji](ARPOL/ration_cards.json): 2 faktyczne składy i deklaracje energii całych racji. Nutrition=null każdego komponentu oznacza brak potwierdzenia dla komponentu, a nie zero.
- [ARPOL — kandydaci komponentów](ARPOL/component_candidates.json): odczytane karty indywidualne, 6 oddzielnych wariantów batonu, niepotwierdzone powiązania z konkretną racją i wada kisielu. Alternatyw nie sumujemy. Dostawca ARPOL nie jest automatycznie producentem komponentu.
- [Coca-Cola PL](CocaCola_PL/source.json): faktograficzny odczyt Original na 100 ml, rynek PL. Brak gęstości nie przeszkadza zapisowi w ml; nie wykonywano konwersji na g.
- [USDA — pochodzenie i wybrane wartości](USDA/source.json) oraz [3 pełne rekordy SR Legacy](USDA/sr_legacy_selected_records.json): ID wybrano z rzeczywistego publicznego eksportu, bez klucza API. Wersja danych April2018 jest odrębna od publicationDate FDC2019-04-01 oraz daty odczytu2026-10-11.

Pliki JSON mają pola source URL, checked_on, jednostki, wersję/ograniczenia. ARPOL/Coca-Cola zachowują czas i SHA-256 pobranych bajtów odpowiedzi, bez kopiowania całej strony sklepu, zdjęć i opisów. Hash odpowiedzi obejmuje także dynamiczną treść strony; nie jest wersją produktu. USDA zachowuje hash oryginalnego ZIP i trzy pełne obiekty po ponownej serializacji; cały ZIP nie trafia do repozytorium. USDA to dane publiczne z odsyłaczem do dokumentacji.

Wartości liczbowe w ekstraktach są tekstami dziesiętnymi. Pełne rekordy USDA zachowują liczby i metadane eksportu. Nutrient1005 jest Carbohydrate, by difference; to zakres USDA, nie niejawna deklaracja identyczności z unijną etykietą węglowodanów przyswajalnych. Wartości tego konkretnego JSON: banan22.8 i jabłko13.8 g; nie dopisano dalszych cyfr z innych wersji lub pamięci. Na potrzeby katalogu wybór tej semantyki trzeba zachować w proweniencji.

Nie zgadywano mas sztuki kawy/cukru/cukierków/gumy/soli/pieprzu, instrukcji niepozyskanych proszków ani producentów z fotografii. Woda przygotowania jest rozdzielona od suchego produktu; woda aktywacji podgrzewacza jest akcesorium, nie napojem. MRE2026 oraz S-RG-1 nie zmieniają swojego statusu i nie były importowane.
