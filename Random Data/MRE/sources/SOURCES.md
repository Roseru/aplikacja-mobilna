# Źródła — MRE XLVI 2026

Data dostępu: 2026-10-09.

## Zawartość menu — Defense Logistics Agency

- [DLA MRE 46 — menu](https://www.dla.mil/Portals/104/Documents/TroopSupport/Subsistence/Rations/qapubs/appa/mre46_menu.pdf).
- [DLA — wykaz dokumentów MRE](https://www.dla.mil/Troop-Support/Subsistence/QA-Publications/Appendix-A/tempmre/).
- Lokalna transkrypcja: [menu_2026_transcription.txt](menu_2026_transcription.txt).

Pobranie PDF DLA zwracało HTTP 403. Listę przepisano z tekstu oficjalnego dokumentu udostępnionego w indeksie wyszukiwania. Zachowano nazwy, numerację, przypisy wariantów i definicje pakietów. Nie przeprowadzono porównania wizualnego z oryginałem DLA. Literówkę w nazwie menu 19 poprawiono w polu użytkowym, zachowując oryginalne brzmienie w `name_source`.

## Wartości odżywcze — HPRC COMRAD

- [COMRAD — strona projektu](https://www.hprc-online.org/nutrition/comrad).
- [Tabela MRE 46 (2026) — oryginalny PDF](https://www.hprc-online.org/sites/default/files/2026-04/MRE_46_menus_COMRAD.pdf).
- [Pobrana kopia PDF](HPRC_COMRAD_MRE_46_2026.pdf) — 4 strony.
- [Tekst wyodrębniony z PDF](HPRC_COMRAD_MRE_46_2026_text.txt) — pomocniczy; sam tekst nie zachowuje niezawodnie pustych kolumn.
- [Wiersze z zachowaniem pustych komórek](comrad_2026_raw.json).
- [Jawna mapa dopasowania nazw](nutrition_name_mapping.json).

Liczby wyodrębniono według współrzędnych kolumn, aby puste pola nie przesuwały kolejnych wartości. `extract_comrad.py` odtwarza surowe wiersze z PDF, `enrich_nutrition.py` przypisuje profile do listy DLA, a `render_reference.py` tworzy czytelne tabele i sprawdza podstawowe zależności. Mapowanie nazw nie stanowi dowodu identycznego składu produktu w każdej partii produkcyjnej.

Zachowano jednostki i wartości źródłowe, w tym ich niespójności. Nie uzupełniano luk szacunkami ani ogólnymi tabelami żywności. Szczegóły ograniczeń i niepotwierdzonych dopasowań znajdują się w README, JSON i przy pozycjach tabel.
