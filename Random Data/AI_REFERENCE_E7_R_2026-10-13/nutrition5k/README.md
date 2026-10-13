# Nutrition5k: 16 kandydatów referencyjnych - osoba 2

Status **CANDIDATE / PENDING_REVIEW**. Wybrano 16 niezmienionych RGB PNG, łącznie 6 469 068 bajtów: osiem pojedynczych składników i osiem różnych dań mieszanych. Wszystkie obejrzano i sprawdzono: 640×480, poniżej 5 MiB na plik, unikalne SHA-256. Qualified i actual_ready pozostają 0.

## Źródło i atrybucja

[Nutrition5k — repozytorium autorów](https://github.com/google-research-datasets/Nutrition5k). Twórcy: Quin Thames, Arjun Karpur, Wade Norris, Fangting Xia, Liviu Panait, Tobias Weyand i Jack Sim. *Nutrition5k: Towards Automatic Nutritional Understanding of Generic Food*, CVPR 2021. Licencja: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), odczyt 13.10.2026. Przy kopiach zachowaj twórców, tytuł, źródło i licencję. Obrazy nie były kadrowane ani przeliczane lokalnie.

[images.json](images.json) podaje dokładne ID/URL, LastModified 2021-06-16, bajty, wymiary i hashe. [annotations.json](annotations.json) zachowuje oryginalne linie CSV, ich SHA-256 i parsowane wartości. [source_metadata.json](source_metadata.json) wskazuje dwa cafe CSV odczytane do wyboru danych (~2,31 MB); [selected16_source_records.json](selected16_source_records.json) zawiera tylko wybrane rekordy i dowody HEAD. [ingredients_metadata.csv](ingredients_metadata.csv) przypisuje ID do nazw. Zapis UTF-8 tego pliku może różnić się kodowaniem od transportu. Źródłowe jednostki: masa oraz B/T/W w gramach, energia w polu calories — bez zmiany jednostki lub domyślania braków.

## Dobór i granice referencji

Dla mieszanek wybrano po 3–6 źródłowych etykiet i odrzucono pary o Jaccard >0,4. Jest to heurystyka różnorodności, nie pomiar trafności. Brakujące RGB i ograniczone próby zapisano w [selection_notes.txt](selection_notes.txt). Single labels: apple, almonds, scrambled eggs, white rice, broccoli, carrot, cauliflower, cherry tomatoes. Są to składniki, bez potwierdzonego markowego produktu.

Oil/salt mogą być niewidoczne; yam/sweet potato niejednoznaczne; berries/caesar salad to zbiorcze nazwy. Niezależny człowiek wybiera widoczne główne składniki i aliasy z fotografii oraz źródła przed wynikiem modelu. Nie zgadujemy receptur. Human reference, reviewer/date, nonsensitive approval i provider consent pozostają niezatwierdzone. Obserwacja agenta nie zastępuje przyjęcia.

[Galeria](../GALLERY.md) ułatwia ocenę. [Proces przyjęcia](../README.md) wskazuje następny krok. Nie wykonano Gemini/uploadu, nie utworzono runnable manifestu lub konfiguracji O3. Poprzedni podobny pilot pozostaje osobnym dowodem, bez doliczania jego zdjęć do tego zestawu.
