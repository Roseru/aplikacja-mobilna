# Poprawiony prompt do zbierania danych racji

Zbierz sprawdzalne dane o składnikach wojskowych racji żywnościowych do przyszłej bazy aplikacji. Zacznij od polskich ARPOL WZ 1 (lazania) i WZ 4 WEGE (risotto pomidorowe), wskazanych w wymaganiach projektu. Amerykańskie MRE mogą być osobnym uzupełnieniem. Nie ma obowiązku pozyskania zdjęć: pełna karta producenta/dostawcy, specyfikacja PDF lub jednoznaczny link są wystarczającym źródłem.

Przed zmianami przeczytaj WYMAGANIA_PROJEKTOWE.md, AGENTS.md, workflow i najnowszą komunikację zespołu. Sprawdź lokalny i zdalny stan repozytorium. Najpierw odczytaj istniejące Random Data/MRE/README.md, zbiór E5 oraz audyt źródeł, żeby nie dublować materiałów i zachować ich ograniczenia. Pracuj na osobnej gałęzi z aktualnego main, zachowując wcześniejsze zmiany innych autorów.

Dla każdej racji zapisz dokładną nazwę, wariant/menu, kraj, producenta lub kompletora, znany rocznik/wersję/partię oraz pełny wykaz produktów jadalnych, w tym napojów, cukru, cukierków, gumy i przypraw. Oddziel wyposażenie, wodę do spożycia i wodę do aktywacji podgrzewacza. Nie utożsamiaj oferty typu wojskowego z potwierdzonym kontraktem dostawy do wojska.

Dla każdego produktu zbierz:

1. Dokładną nazwę, producenta, markę, smak/wersję i identyfikator, jeżeli źródło go podaje. Kompletora racji nie wpisuj automatycznie jako producenta dodatku.
2. Dowód występowania w konkretnej racji: źródło listy składników oraz dokument potwierdzający przypisanie dokładnego wariantu. Sama zgodna nazwa ogólna i gramatura oznacza kandydata do dopasowania.
3. Masę netto opakowania lub jednej sztuki oraz liczbę sztuk. Nie zastępuj netto masą brutto. Zachowaj określenia „minimum”, „około” i brak masy.
4. kcal, białko, tłuszcz i węglowodany z jawną podstawą: na 100 g, 100 ml lub porcję o znanej masie. Dla proszków określ, czy tabela dotyczy produktu suchego czy przygotowanego.
5. Dla proszków instrukcję: ilość proszku, ilość i temperatura wody, sposób mieszania oraz czas, jeśli podane. Woda nie dodaje energii. Dodana objętość wody nie oznacza końcowej objętości napoju; bez źródła nie przeliczaj g na ml.
6. Źródło każdego zestawu faktów: bezpośredni URL, tytuł dokumentu, strona PDF lub sekcja karty, data faktycznego odczytu, dostępna data publikacji i wersja. Dla pobranych PDF-ów zachowaj oryginał i SHA-256; nie wymyślaj metadanych dla samych wyników wyszukiwania.

Preferuj źródła producenta, kompletora i instytucji wojskowych. Oferty sklepów/aukcji zapisuj osobno jako źródła wtórne, szczególnie gdy mylą smaki lub masy. Używaj ich do wskazania brakującej etykiety, nie do automatycznego zatwierdzenia produktu. Zdjęcia uzupełniają jedynie dane niedostępne w wiarygodnych dokumentach; nie przypisuj producenta na podstawie nieczytelnego lub poglądowego opakowania.

Wykryte rozbieżności zachowaj i opisz. Brak to null, nie zero. Nierówność np. B<0,4 g nie jest dokładną wartością. Nie poprawiaj samodzielnie błędnej pary kJ/kcal, nie wyliczaj brakujących makr z kalorii i nie rozdzielaj energii całej racji na składniki. Różnych smaków, wersji receptury i alternatyw menu nie sumuj.

Zapisz wynik w istniejącym Random Data/ lub osobnym podfolderze zbioru. Dostarcz czytelny README z tabelami, JSON do późniejszego mapowania, źródła/PDF-y, dziennik poszukiwań oraz listę konkretnych braków. Zachowaj wcześniejsze zbiory bez nadpisania. Oddziel karty produktów od potwierdzonych powiązań z racją. Nie ogłaszaj kompletnego katalogu official, jeśli nadal brakuje etykiet, producentów, wariantów, mas lub makr.

Sprawdź JSON, referencje, jednostki, liczbę pozycji, lokalne linki i hashe PDF-ów oraz porównaj wartości ze źródłami. Opublikuj zgodnie z repozytoryjnym workflow i przekaż rezultat w jednym wspólnym dzienniku. W odpowiedzi podaj folder, zakres nowych danych, pozostałe braki, gałąź i stan PR.
