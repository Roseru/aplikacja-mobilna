# Amerykańskie MRE — rocznik 2026 (XLVI)

Zawartość wszystkich 24 menu: **Case A — menu 1–12**, **Case B — menu 13–24**. Skład zestawów pochodzi z DLA, a porcje, kalorie, makro, witaminy i minerały z oficjalnej tabeli HPRC COMRAD 2026. Data zebrania: 9 października 2026.

## Pliki

- [Case A: menu 01–12](Case_A_menu_01-12_2026.md) — produkty oraz kalorie i makro obok każdego produktu, rozwinięte pakiety dodatków.
- [Case B: menu 13–24](Case_B_menu_13-24_2026.md) — analogiczna rozpiska drugiej skrzynki.
- [Pełne wartości odżywcze](Wartosci_odzywcze_2026.md) — 114 profili z 36 polami, w tym witaminy, minerały, rodzaje tłuszczu, cukry i kofeina. Każdy potwierdzony produkt w tabelach odsyła do profilu.
- [Dane JSON](mre_2026.json) — wersja do wykorzystania w aplikacji: menu, produkty, alternatywy, pakiety dodatków, profile i pochodzenie danych.
- [Oryginalna tabela COMRAD — PDF](sources/HPRC_COMRAD_MRE_46_2026.pdf).
- [Źródła i sposób opracowania](sources/SOURCES.md) oraz [kontrola danych](sources/VALIDATION.md).

## Jak czytać wartości

Wartości dotyczą **całej porcji o masie wskazanej przez COMRAD**, a nie 100 g. W przypadku proszków nie doliczono wody używanej do przygotowania. Liczba sztuk, jeśli źródło jej nie podaje, pozostaje nieznana; masa porcji nie oznacza automatycznie jednej sztuki.

`—` w tabelach i `null` w JSON oznaczają brak danych, a nie zero. `0` oznacza zero podane w źródle. Sprzęt, chusteczki i opakowania mają oznaczenie „nie dotyczy”. Nie wyliczano brakujących witamin ani makro na podstawie produktów podobnych.

Smaki wymienione jako alternatywy nie występują jednocześnie w jednej paczce — nie należy sumować ich wartości. COMRAD dla części napojów podaje jeden profil ogólny; nie potwierdza on osobnych wartości każdego smaku.

**Case A/B to skrzynki z 12 posiłkami. Accessory Packet A/B to pakiety dodatków wewnątrz posiłków.** Pakiet rozwinięty pod tabelą nie jest dodatkowym pakietem. Dla pakietu B COMRAD podaje średnią zbiorczą z oznaczeniem „MRE 42”; nie należy dodawać jej ponownie do wartości jego składników. Brakuje osobnych profili soli i gumy bez kofeiny, więc pozostają oznaczone jako brak danych.

## Rozbieżności i ograniczenia

- To jeden rocznik: **2026 / XLVI**, nie wszystkie historyczne wersje. DLA dopuszcza zamienniki i przesunięcia zmian produkcyjnych; zawartość konkretnej paczki należy sprawdzić na opakowaniu.
- W menu 3 DLA wymienia cukierki Original, a COMRAD Berry. W czterech pozycjach przyprawa Picante z DLA jest zestawiona z Tapatio w COMRAD. Te pięć dopasowań pozostaje niepotwierdzonych; profil porównawczy nie jest profilem deklarowanego produktu.
- W menu 20 DLA wymienia ciastko Chocolate Chip, COMRAD Chocolate Fudge. Dla Chocolate Chip wskazano profil tego samego nazwanego produktu z menu 16, z opisem pochodzenia.
- DLA nie wymienia worka na gorący napój w menu 2 ani podgrzewacza w menu 16. Nie dopisano ich na podstawie domysłu; brak na liście nie dowodzi braku w fizycznej paczce.
- COMRAD zawiera podejrzane dane: różne masy i wartości dla gumy z kofeiną, w części wierszy 0 mg kofeiny, a także niektóre rozbieżności energii względem makro. Zachowano liczby źródłowe i uwagi przy profilach.
- Nagłówek selenu w PDF to „Sel (mg)”, lecz jednostka wymaga potwierdzenia. W JSON użyto `selenium_source_unit` i nie przeliczano wartości. Dla kwasów linolowego i alfa-linolenowego źródło nie podaje jednostki; także pozostawiono ją nieokreśloną.
- Sumy COMRAD zapisane w JSON są sumami opublikowanymi przez COMRAD, nie wyliczonymi sumami składników DLA i nie gwarantują zgodności dla wszystkich alternatyw.
- Nazwy produktów pozostawiono po angielsku dla zgodności ze źródłami. Dane nie zawierają pełnych składów surowcowych, etykiet alergenów ani marek konkretnych partii, których użyte źródła nie dostarczają.
- PDF DLA zwracał HTTP 403. Listę zawartości przepisano z indeksowanego tekstu oficjalnego dokumentu; oryginalnego arkusza DLA nie zweryfikowano wizualnie. PDF COMRAD został pobrany i sprawdzony.

## Struktura JSON

`menus` zawiera menu i ich `components`. Każdy komponent ma `nutrition.status`, `profile_ids` oraz uwagi. Profile są w `nutrition_profiles`; ich `values` zawiera wartości na porcję. `reference_profile_ids` oznacza wyłącznie niepotwierdzone porównanie. `accessory_packets` rozwija pakiety dodatków. `variant_footnotes` przechowuje warianty smaków DLA. Każdy profil zachowuje adres źródła, stronę PDF i numery menu, w których występuje.

Ten zbiór należy do materiałów źródłowych przyszłej bazy danych całej aplikacji; zobacz [przeznaczenie folderu Random Data](../README.md).
