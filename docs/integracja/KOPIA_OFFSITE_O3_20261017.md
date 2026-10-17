# Szyfrowana kopia poza komputerem — O3

17 października 2026, agent3/O3. Gałąź `codex/devops-szyfrowana-kopia`,
baza main0e878bf. Dotyczy istniejącej lokalnej instalacji; nie uruchamia VPS.

## Wykonany odbiór Dropbox

Właściciel wskazał i zatwierdził dokładny zapis pliku
`/Calorie O3 backups/2026-10-17T141200Z.enc`. Po potwierdzeniu połączenia konta
utworzono folder i zapisano plik, bez publikowania linku udostępnienia.
Plik ma921645B; zmiana na serwerze17.10,18:30:54CEST.

Kopia pochodzi ze spójnego capture17.10,16:12CEST: aplikacja, Keycloak,
globals/SCRAM, konfiguracja/TLS i katalog. Przed pakowaniem istniejący
`backup.py verify` sprawdził21plików i manifest. Dane użytkowników i klucze
TLS znajdują się wyłącznie wewnątrz szyfrowanej zawartości.

SHA-256 szyfrogramu:
`229896270896baaf61832aa7960cf6fee4de6729c80be2ba581729ee03828d99`.
Identyfikator manifestu kopii:
`8b989906e0ca3b902d90a144940ef53cd82ac3ad0645a71c953783890ac3e8cd`.

Wykonano rzeczywisty niezależny GET z Dropbox przez jednorazowy link,
porównano cały SHA-256 i liczbę bajtów, uwierzytelniono i odszyfrowano zawartość
oraz odtworzono ją istniejącym `backup.py rehearse` w osobnym PG17 bez sieci.
**PASS,11,83s:** obie bazy, globals,12kont/13tożsamości i fingerprints,
schema24, nowa epoka/fence w odtworzonej kopii, katalog oraz SCRAM finalizera.
Źródło pozostało uruchomione i nie zmieniło epoki. Receipt18:31:56CEST
ma rzeczywiste `offsite_verified=true` dla tej jednej dostawy.

To dostawa jednorazowa. Nie zainstalowano automatycznego nadawcy Dropbox
i nie zaliczono przyszłych terminów kopii. Lokalne kopie03/15 i ich monitoring
działają nadal. Nie ustawiono monitora offsite na zielony status stałej usługi
na podstawie jednego uploadu. Klucz zapisano w prywatnym magazynie O3 poza
checkoutem z ograniczonym ACL; nie trafił do Dropbox ani Git. Odtworzenie
po utracie całego komputera wymaga jeszcze niezależnego, chronionego
przechowania tego klucza. `independent_key_recovery_copy=false`.

Na polecenie właściciela można usunąć dokładny plik i pusty folder w Dropbox;
do tego czasu pozostają jako odebrana kopia. Usunięcie klucza przed zapewnieniem
innej kopii uniemożliwia odszyfrowanie.

## Powtarzalne narzędzie

[offsite_package.py](../../infra/integration/offsite_package.py) używa
AES-256-GCM z losowym12-bajtowym nonce dla każdego pakietu i uwierzytelnionym
identyfikatorem formatu. Pakuje wyłącznie pliki wymienione w sprawdzonym
manifeście i sam manifest, nie logi lub przypadkowe pliki źródła. Nowy klucz
powstaje w nowym prywatnym katalogu. Klucz musi być poza pakowaną kopią.

Wersja1 mieści się w pamięci: limit256MiB archiwum i4096plików; większa kopia
jest odrzucana. TAR jest nieskompresowany, bez extractall, linków lub przejść
poza katalog. Odszyfrowanie sprawdza autentyczność, nazwy, duplikaty, rozmiary,
komplet plików i ich SHA przed utworzeniem nowego prywatnego katalogu docelowego.
Pliki wejściowe, pakiet wyjściowy i zastany katalog restore nie są nadpisywane.

```text
python infra/integration/offsite_package.py key --key <nowy-prywatny-katalog>/recovery.key
python infra/integration/offsite_package.py pack --backup <odebrana-kopia> --key <prywatny-key> --output <nowy-plik.enc>
python infra/integration/offsite_package.py verify --package <pobrany-plik.enc> --key <prywatny-key>
python infra/integration/offsite_package.py unpack --package <pobrany-plik.enc> --key <prywatny-key> --output <nowy-prywatny-katalog>
python infra/integration/backup.py rehearse --backup <nowy-prywatny-katalog>
```

Ostatnia komenda używa istniejącego narzędzia odtworzenia. Samo pack/verify/unpack zawsze
zwraca `offsite_verified=false`. Dowodem zewnętrznej dostawy jest oddzielny
receipt po rzeczywistym upload/download/restore z danego magazynu.

**11testów PASS:** zgodny pełny roundtrip i wykluczenie dodatkowego pliku,
odmowy uszkodzonego ciphertext/nonce/header/truncation/błędnego klucza,
zmienionego źródła, nadpisania, traversal, linku i duplikatu TAR. Ponadto
rzeczywista lokalna próba zaszyfrowanej kopii przeszła restore12,435s, a próba
pliku pobranego z Dropbox11,83s. Wspólny zestaw z osobną zmianą checkera
PR120:187PASS; lint/format PASS. Zdalny CI własnego PR jest osobny.

Źródła API: [AESGCM cryptography](https://cryptography.io/en/latest/hazmat/primitives/aead/),
[bezpieczna obsługa TAR](https://docs.python.org/3/library/tarfile.html#extraction-filters).

## Ciągły rejestr usunięć i odtworzenie produkcyjne

**Ciągły, autorytatywny rejestr nie jest wdrożony.** Dropbox daje miejsce na
zaszyfrowane pliki, ale samo konto chmurowe i zrzut DB nie tworzą niezależnego
strumienia zdarzeń. Nie podmieniono fixture `verify_fixture_ledger` z runnera
O2 na importer produkcyjny. Nie przyznajemy pełnego KO32.

Odczyt rzeczywistej instalacji17.10 wykazał0account_deletion_jobs,0pending,
0połączeń pg_stat_replication i główny PG poza recovery. To punktowy pomiar,
nie dowód braku zdarzeń poza zakresem obserwacji lub pełnego fencing replik.
Próba [PR120](https://github.com/Roseru/aplikacja-mobilna/pull/120) sprawdziła
odtworzenie danych rzeczywistego źródła i kompatybilny powrót obrazu w izolacji;
próba O2 potwierdza odrzucanie starych tokenów w swoim własnym środowisku.

**Do O2 — konkretne wejście do wykonania i wspólnego odbioru:**

1. Jedyny autoryzowany producent wszystkich begin/provider/confirm/purge,
   także pending/failed, musi trwale zapisać zdarzenie przed potwierdzeniem
   skutku na zewnątrz. Sam okresowy odczyt DB po operacji nie daje gwarancji
   przywrócenia po utracie całego hosta między usunięciem a eksportem.
2. O2 określa transakcyjny outbox/egzekwowany protokół i uprawnienia operatora.
   Zdarzenie wiąże installation/issuer, operation_id, subject/account,
   expected_generation/deleting_generation i wynik provider/confirm/purge.
   Role/operacje omijające producenta muszą być odcięte lub objęte tym samym
   protokołem; zachowujemy reguły O2 i wersjonowane migracje.
3. O3 zapewnia oddzielny trwały magazyn, uwierzytelnianie producenta, retencję,
   kolejność i integralność segmentów. O2/O3 odbierają watermark i nieprzerwany
   zakres od kopii do ostatniego dozwolonego issuance/zapisu, w tym brak luk,
   spóźnione zdarzenia, awarię dostawy i restart producenta.
4. Przed rzeczywistym restore/reopen O3 fizycznie odcina wszystkie stare
   API/workery/issuers/repliki według inwentarza celu; O2 sprawdza generacje,
   blocklist i wyniki deletion. Brak/nieświeży/sprzeczny segment pozostawia
   ruch zamknięty. Później wymagane realne stareJWT/refresh denied,
   świeżePKCE i recovery telefonu O1, a funkcje AI/Nemesis mają osobne bramki.

O2-040/PR120/head9f32a2d odczytany: dodatkowe trzy testy zabezpieczają hashe
blobów manifest/config i odmowę zduplikowanego TAR; kod wykonawczy checkera
i receipty są zachowane. Ich końcowy odbiór jest częścią osobnego PR120.

Następny krok wymaga wykonawczego źródła O2 i odbioru transportu magazynu;
nie wymaga tworzenia fikcyjnego pustego ledger lub ustawiania PASS.
Produkcyjne RPO/RTO należy ustalić i zmierzyć na wybranym celu wdrożenia.
Pomiary restore11,83s i rollback5,623s są lokalnymi wynikami tych prób.
