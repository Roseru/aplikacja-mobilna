# Ograniczony inventory i ocena źródeł - osoba 2

**Historia pozyskania:** poniżej zachowano kolejne wcześniejsze próby i oceny źródeł. **Aktualny stan:** istnieje30 wybranych kandydatów w [candidate_index.json](candidate_index.json), qualified=0. Przyjmujemy konkretne istniejące obrazy; odrzucone zastępujemy przed zamrożeniem. Dawne instrukcje dostarczenia P01 i początkowego braku zdjęć są historią przygotowania, a nie bieżącym brakiem wszystkich plików. [README](README.md) i [galeria](GALLERY.md) podają aktualny zakres.

Data: 2026-10-13. Punkt odniesienia dokumentów: main `2fc70f7ae612c031f63d53c04d3c81b4402b72c5`.

## Zakres i wynik

Wyłącznie repo/projekt: lista `rg --files Random Data` oraz wyszukiwanie rozszerzeń jpg/jpeg/png/webp/heic przez `rg --files`, z wyłączeniem build/.venv. Sprawdzono wskazany checkout main oraz pierwotny katalog projektu; nie skanowano Downloads, prywatnych załączników, innych chatów ani storage. Nie wyciągano rastrów z PDF jako fotografii produktu.

| Miejsce | Znalezione materiały | Zdjęcia gotowe do E7-R |
|---|---|---:|
| Main: Random Data/MRE | JSON, transkrypcje, tabele, HPRC COMRAD PDF; alternatywy i braki opisane w README | 0 |
| Main: Random Data/ARPOL_WZ_2026-10-11 | karty/JSON/README, dwa PDF-y specyfikacji; niepewne powiązania z racją | 0 |
| Main: Random Data/E5_2026-10-11 | USDA wybrane rekordy, źródło CocaCola_PL, karty/kandydaci ARPOL | 0 |
| Main: propozycje-ui | 15 PNG z projektami ekranów; nie są fotografiami jedzenia | 0 |
| Pierwotny katalog projektu: Random Data i wyszukiwanie powyższych rozszerzeń | MRE/ARPOL dokumenty; brak plików fotograficznych w wynikach wyszukiwania | 0 |

Wniosek ograniczony do tego zakresu: `actual_ready=0`. Nie oznacza to braku zdjęć w prywatnych zasobach właściciela; te nie były przeszukiwane ani autoryzowane jako corpus. Materiały Random Data zachowano bez zmian. Missing pozostaje missing, nie zero; alternatywnych wariantów nie sumujemy.

## Krótka próba źródeł publicznych

1. [Nutrition5k — pierwotne repozytorium autorów](https://github.com/google-research-datasets/Nutrition5k), odczyt 2026-10-13: rzeczywiste talerze z kilku stołówek, RGB/RGB-D i nagrania oraz identyfikatory dań z listami składników. Repo odsyła do [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), odczyt tego samego dnia; wymaga atrybucji, linku licencji i oznaczania zmian. Możliwe pobieranie wybranych plików; pełne archiwum ma 181,4 GB. Materiał może być kandydatem dla grupy mixed, lecz nie potwierdza przekroju 10 racji i 4 rzeczywiście nieczytelnych zdjęć. Nie kwalifikowano żadnego konkretnego pliku, nie zamrożono referencji ani zgód. Nie pobierano danych.
2. [Food-101 — pierwotna strona ETH](https://data.vision.ee.ethz.ch/cvl/datasets_extra/food-101/), odczyt 2026-10-13: etykiety klas dań i zdjęcia testowe; celowo zaszumiony trening. Strona nie dostarcza list składników konkretnego dania ani jawnej licencji obrazu spełniającej ten proces przyjęcia. Nie kwalifikowano/pobierano plików.

Nie znaleziono w tej krótkiej próbie pewnego kompletnego zestawu 30 zdjęć spełniającego 8/8/10/4 i wymagającego jedynie proporcjonalnego przyjęcia. Ocena nie dowodzi, że taki zestaw nigdzie nie istnieje. Publiczna licencja nie tworzy automatycznie manifestowej zgody na konkretny test/dostawcę; decyzja o corpus i referencjach pozostaje jawna. Nie użyto ikon, zdjęć producenta bez uprawnień, syntezy ani rozmytych kopii dla pozornego wypełnienia przekroju.

Decyzja: konkretny plan wykonania przez fotografa i niezależną ocenę człowieka. Bez mas/kcal z modelu, bez zgadywania tożsamości wariantu. Istniejący runner i kod pozostają bez zmian.

## Pojedynczy eksperyment dostępności małego RGB

Pytanie: czy da się uzyskać konkretny ID pojedynczego RGB i dopasować jego annotations bez archiwum/video? Próba 2026-10-13: `Invoke-WebRequest` (timeout 20 s) na publiczny listing `https://storage.googleapis.com/nutrition5k_dataset?prefix=nutrition5k_dataset/imagery/realsense_overhead/&max-keys=3`. Wynik środowiska: `Nieznany host. (storage.googleapis.com:443)`. Niezależny `web.open` tego samego adresu: `not accessible via this tool`.

Nie uzyskano listingu, ID, JPEG ani dopasowanego rekordu annotations. To ograniczenie dostępu w tej próbie, nie twierdzenie o nieistnieniu danych lub niedostępności zbioru wszędzie. Zgodnie z ograniczeniem zadania zakończono próbę bez scrapingu, innych źródeł lub dużych downloadów. Publiczny partial subset: 0 plików. `actual_ready=0` pozostaje prawdziwe.

## Uzupełnienie: źródło dostępne po eskalacji sieciowej

Powyższy błąd DNS zachowano jako wynik pierwotnej próby sandboxowej. Koordynator wykonał autoryzowany publiczny odczyt require_escalated i uzyskał HTTP 200. Następnie wykonano ograniczony listing max-keys=24 (8 RGB plus wpisy depth; depth nie pobierano) i mały listing metadanych max-keys=10. Dokumentowana nazwa ingredient_metadata.csv zwróciła 404; publiczny listing wskazał rzeczywistą nazwę ingredients_metadata.csv.

Pobrano dokładnie 8 RGB PNG, łącznie 3 702 710 bajtów; dopasowano 8 oryginalnych rekordów z publicznych cafe CSV oraz ingredient IDs/nazwy. Obrazy obejrzano przez view_image. Wszystkie oryginalne source LastModified pochodzą z 16 czerwca 2021; datowane annotations są niezależne od modelu, którego nie wywołano. Obrazy, URL-e, hashe, atrybucja CC BY 4.0 i ograniczenia są w nutrition5k_subset8/README.md oraz sidecar JSON. Żadnego archiwum 181,4 GB, video, depth ani uploadu.

Aktualny wynik: `actual_downloaded=8`, `actual_ready=0`, `qualified=0`, CANDIDATE/PENDING_REVIEW. Pierwsze pięć zdjęć przedstawia pojedyncze składniki; kolejne trzy tę samą kombinację na różnych talerzach, więc nie są ośmioma zróżnicowanymi daniami mieszanymi. Nie przypisano ich do slotów planu i nie zaliczono do min30. Wymagane niezależne ludzkie zatwierdzenie widocznych składników/aliasów, nonsensitive review i konkretna zgoda na referencyjny Gemini test. Nieaktualne pozostaje tylko historyczne zero pobranych plików z pierwszej próby; zero kwalifikowanych przypadków pozostaje prawdziwe.

## Uzupełnienie po jawnym zleceniu poszukiwania w internecie

Właściciel odpowiedział, że nie ma własnych zdjęć i zlecił znalezienie ich w internecie. Przygotowano `nutrition5k_diverse16/`: 16 realnych niezmienionych RGB, 8 różnych pojedynczych etykiet/składników i 8 różnych kombinacji 3–6 składników, wybranych z oryginalnych publicznych metadanych. Pobrano 6 469 068 bajtów RGB, bez archiwów/video/depth. Obejrzano wszystkie obrazy i sprawdzono PNG/640×480/≤5 MiB/unikalne hashe, listing-derived wcześniejszy eksperyment pozostaje zachowany. Nowy dobór korzystał z bounded exact-object HEAD, 5 w nieudanej pierwszej selekcji i 34 w końcowej; źródłowe metadane około 2,31 MB w pamięci, zachowane tylko wybrane linie.

Docelowy podzbiór: `actual_downloaded=16`, `qualified=0`, `actual_ready=0`, CANDIDATE/PENDING_REVIEW. Wcześniejsze8 to osobny zachowany pilot; fizycznie 24 pobrane zdjęcia w obu podfolderach, ale nie wolno sumować ich jako 24 zakwalifikowane corpus cases. Źródła i licencja CC BY 4.0 są udokumentowane; source annotations 2021 nie są odpowiedzią modelu. Sól/oliwa i etykiety zbiorcze wymagają niezależnego ustalenia widocznych main components/aliasów. Nie wypełniano zgód/readable/reviewer/approved_at. Pełne 30 oraz 10 racji/4 naturalnie nieczytelne pozostają poza tym podzbiorem; E7-R nie zamknięto.
