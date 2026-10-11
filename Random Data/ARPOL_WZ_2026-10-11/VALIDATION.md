# Kontrola zbioru

Data: 11.10.2026, Agent 2 / O2.

- JSON poprawnie parsuje się jako UTF-8; wartości są tekstami dziesiętnymi, a granice B/T kisielu pozostają nierównościami.
- `validate_sources.py`: PASS — 2 racje, 30 wystąpień żywności i przypraw, 20 kart wariantów, 21 źródeł/prób; unikalne ID i wszystkie referencje istnieją.
- 13 kart HTML + 2 PDF-y pobrano z HTTP 200; 4 inne adresy zwróciły 404. Dwie karty wtórne odczytano narzędziem web i oznaczono osobno.
- SHA-256 obu lokalnych PDF-ów jest zgodne z manifestem; obejrzano obie strony po renderowaniu Popplerem. Ostrzeżenia o opcjonalnych fontach nie uniemożliwiły czytelnego renderowania.
- Porównano ręcznie tabele kart, gramatury i instrukcje: nowe smoothie 50 g, trzy napoje 5 g oraz herbata PDF 15 g; sześć wariantów batonu i istniejące karty E5 pozostają zgodne z odczytem.
- Producent komponentu i dokładne przypisanie do racji nie zostały automatycznie zatwierdzone. Wszystkie komponenty mają `nutrition_for_ration_component=null`, a karty nie są gotowe do importu jako official.
- Sprawdzono istnienie lokalnych celów linków, kotwic w README i `git diff --check` przed publikacją.

Ponowienie kontroli: `python validate_sources.py` z tego folderu. Skrypt korzysta wyłącznie z biblioteki standardowej. Kontrola techniczna nie potwierdza brakujących etykiet ani zgodności konkretnej partii racji.

Istniejący walidator E0 wykonano w tej gałęzi: PASS — 69 valid / 26 invalid / 18 scenarios, 16 Decimal, 5 kompletności, 72 normalizacje i 284 lokalne linki. Osobna kontrola nowego folderu: 42 lokalne linki/kotwice PASS. To kontrola dokumentacji i danych, bez nowych testów runtime/DB/Androida.
