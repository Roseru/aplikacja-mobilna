# Kandydaci zdjęć do E7-R - osoba 2

## Aktualny wynik kwalifikacji offline (13.10.2026)

[Propozycje referencji](reference_proposals.json) rozliczają wszystkie35 plików (30 pierwotnych +5 nowych):
30 PROPOSED (8/8/10/4),4 REJECTED (commons-03/07/08/20),1 UNRESOLVED (n5-16).
To propozycje LLM do człowieka, human_qualified/consents/uploads=0.
NOT-RUNNABLE; HUMAN_REVIEW_PENDING; O3_CONFIGURATION_PENDING.
Przekrój30 propozycji jest kompletny. Wszystkie oryginały pozostają zachowane; candidate_index
z opisem8/8/10/4 jest historycznym wyborem kandydatów, nie przyjętym corpus.
[Raport](../../docs/e7/RAPORT_PRZYGOTOWANIA_ZDJEC.md) podaje wyjątki, ograniczoną
próbę zamienników i domknięcie trzech slotów i przejście do istniejącego runnera.
[Audyt](technical_audit.json) ponownie potwierdza bajty/codec/hash/wymiary/GPS.

Stan 13 października 2026 r.: pobrano i wybrano **30 rzeczywistych zdjęć** z publicznych źródeł. Proponowany przekrój: 8 produktów/składników, 8 dań mieszanych, 10 racji/składników i 4 naturalnie zasłonięte ujęcia. **Zatwierdzonych przypadków: 0; zgód dla providera: 0; uploadów/wywołań Gemini: 0.** To przygotowanie materiałów, nie wynik trafności lub E7-R PASS.

Właściciel podał, że nie ma własnych zdjęć, i zlecił poszukiwanie w internecie. [Galeria](GALLERY.md) pokazuje konkretne kandydatury. [candidate_index.json](candidate_index.json) podaje źródła, grupy, dokładne pliki i SHA-256; celowo nie jest runnable manifestem. Wszystkie 30 plików obejrzano i sprawdzono ich format/rozmiar/hash; żaden nie przekracza 5 MiB. Nie zmieniano lokalnie obrazów. Warianty thumbnail Commons mają opisaną drogę do oryginału; historyczne kadrowanie przez autora jest jawne w źródle commons-01.

## Materiały i ich ograniczenia

- [Nutrition5k](nutrition5k/README.md): 16 różnych RGB 640×480 i dokładne źródłowe rekordy składników. Osiem pojedynczych składników oraz osiem różnych mieszanek; niewidoczne dodatki i zbiorcze nazwy pozostają kwestią oceny, nie oczekiwaniem wizualnego rozpoznania wszystkich anotacji.
- [Commons](commons/README.md): 14 wybranych zdjęć z metadanymi praw i [atrybucją](commons/ATTRIBUTION.md). Racje są historyczne/awaryjne i mają jawne niepewności. commons-08 pokazuje etykietę zestawu, a commons-10 alternatywne próbki owoców; nie tworzą zweryfikowanego katalogu ani jednego posiłku. Cztery ujęcia z ukrytym jedzeniem mają tę samą technikę zasłonięcia liśćmi, co ogranicza różnorodność trudnych przypadków.
- [capture_plan.json](capture_plan.json) zachowuje pierwotny 30-slot plan; jego planowane obiekty nie są automatycznym przypisaniem tych zdjęć. [CHECKLIST.md](CHECKLIST.md) określa przyjęcie i zamrożenie, [INVENTORY.md](INVENTORY.md) zakres pozyskania i wcześniejsze niepowodzenia.

Osiem podobnych zdjęć z początkowego pilota Nutrition5k i cztery odrzucone zdjęcia Commons pozostają w prywatnym dowodzie przygotowania; nie liczymy ich jako dodatkowych zatwierdzonych przypadków. Publiczny audit-index Commons dokumentuje 18 pierwotnych źródeł, ale pakiet zawiera tylko 14 wybranych obrazów. Ad-hoc skrypty pobierania nie są nowym narzędziem projektu ani poleceniem live.

## Następny konkretny krok

Niezależny człowiek ocenia widoczność, główne składniki/aliasy i niesensytywność dla każdego dokładnego pliku. Rozstrzyga lub zastępuje wątpliwe zdjęcia przed zamrożeniem. Nie wymagamy potwierdzenia producentów dla demo, lecz nie zmieniamy braków w zero ani zdjęć w official. Racje/alternatywne składniki nie są sumowane. Licencje i atrybucje zachowujemy; publiczna licencja nie wypełnia samodzielnie aplikacyjnej zgody na konkretny referencyjny test Gemini.

Po tej ocenie i konkretnych zgodach O2 może utworzyć ścisły manifest. O3 oddzielnie dostarcza rzeczywistą konfigurację/profile/notice/limity i gotowe API/worker. Używamy [istniejącego runnera](../../tools/ai_reference/README.md) oraz [bramki E7-R](../../docs/e7/E7_R_MANIFEST.md), bez bezpośredniego API Google lub nowej puli. Pierwsza próba obejmuje jeden zatwierdzony przypadek. Materiały są niezależne od kodu E9; bieżące przekazanie pozostaje w [jedynym dzienniku](../../docs/KOMUNIKACJA_AGENTOW.md).
