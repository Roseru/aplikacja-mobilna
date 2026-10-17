# Odbiornik ciągłego rejestru usunięć — O3

18.10.2026 (pierwszy checkpoint17.10). Kod przygotowany; zewnętrzny host, fizyczne odcięcie starego źródła
i produkcyjny cutover **WAITING_EXTERNAL**. Nie zmieniono używanej instalacji,
kont, CA, epoki, usług ani bramek AI/Nemesis. Próba APK/API pozostaje na poniedziałek.

## Zależność i rzeczywisty odbiór źródła

Ten etap wymaga kontraktu runtime z PR124, dokładny parent
`9b761561bc01cd90deb048499948541c0bfe1cfa`, branch
`codex/backend-ciagly-rejestr-usuniec`. Własna gałąź O3 to
`codex/devops-odbiornik-rejestru`; zależny PR porównuje się z rodzicem.
Najpierw A2/koordynator poprawia i odbiera PR124, potem zmieniamy bazę tego
PR na main i odbieramy własny pełny CI. Nie scalać dziecka do rodzica.

Odczyt O2-041 obejmuje źródło/MAC/ACK/cutoff, egzekwowane bariery oraz jawny
brak ponownego otwarcia po restore. CI39070253209 źródła nie jest PASS:
job PostgreSQL117506191202 zakończył się **61 FAIL,1317 PASS,16 ERROR**.
Nowa blokada downgrade poniżej0024 koliduje z zastanymi fixture migracji,
raw state/generation nie przechodzi nowych barier, a stary CLI resume jest
odrzucany zgodnie z nowym protokołem. Przykłady: `test_e8_migration`,
`test_e8_purge_commit::test_hardened_operator_cli_begin_resume_retry`,
`test_e8_ranking_pg`, `test_e9_processes` i `test_foundation`.
O2 opublikował następnie poprawki fixture/izolacji/CLI na9b76156; źródło
dołączono zwykłym merge, kontrakt runtime i kod odbiornika nie zmieniły się.
Nowy pełny CI i odbiór koordynatora pozostają osobne. Historyczny RED jest
zachowany jako dowód wcześniejszego checkpointu. O2 powinien odebrać
przygotowanie historycznych baz i scenariusze protokołu;
nie usuwać nowych barier ani zamieniać tych testów w skip. Ten raport jest
odbiorem kontraktu i diagnozą, nie odbiorem całej migracji0025.

## Zachowanie odbiornika

[ledger_receiver.py](../../infra/integration/ledger_receiver.py) implementuje
uwierzytelniony POST `/v1/batches`. Używa normatywnych prymitywów A2, bez
kopiowania kluczy fixture i bez ponownej serializacji podpisanego `content`.
Stałe identyfikatory, issuer i dwa różne klucze32B pochodzą z prywatnej
konfiguracji administratora, nigdy z przychodzącego batcha. Osobny losowy
bearer ma minimum32znaki; wymagany jest bezpośredni HTTPS z przypiętym CA.

SQLite WAL/synchronous FULL jest magazynem odbiorcy, a PostgreSQL pozostaje
źródłem. Wszystkie eventy i uwierzytelniona koperta trafiają do jednej
transakcji BEGIN IMMEDIATE. ACK powstaje **po** zakończonym commit. Utracona
odpowiedź i identyczny replay nie tworzą drugiego eventu. Luka, fork, zmiana
tożsamości, kluczy, treści lub MAC są odrzucane. Restart uwierzytelnia cały
zapisany prefiks i sprawdza dokładne mapowanie kopert do eventów oraz pin.
Walidacja pracuje porcjami, bez słownika całej rosnącej historii. Każdy batch
musi być ciągły także przy replay. Restart czyta jeden snapshot transakcyjny;
równoległy poprawny zapis nie powoduje fałszywego alarmu uszkodzenia.
Brak bazy nie tworzy automatycznie nowego pustego strumienia.

HTTP ma limit8MiB+4096B na kopertę (wewnętrzny batch A2 nadal1MiB),10s
na odczyt body,16równoległych połączeń serwera i brak access logów. Odrzuca
zduplikowane pola JSON, kodowanie treści i błędną autoryzację przed zapisem.
Brak trwałego zapisu daje503 bez ACK. Endpoint nie udostępnia eksportu,
kluczy, danych kont, OpenAPI ani operacji administracyjnych.

Offline `freeze` wymaga niezależnego FencePin kontrolera, serializuje się
z dostawami i trwale zamraża odbiorcę. Wywołanie nie zatrzymuje źródła ani
issuera: administrator musi wcześniej wykonać i odebrać fizyczny fencing.
Nie ma HTTP cutoff/reopen ani automatycznego odblokowania. Lokalny test
używa scope `contract-test`; nie wystawia produkcyjnego dowodu zatrzymania.

## Uruchomienie na niezależnym hoście

Przygotuj nowy prywatny katalog z bazą, osobny katalog konfiguracji/kluczy,
odrębny certyfikat TLS i losowy bearer. Nie używaj NFS/SMB dla plików SQLite
WAL. Katalog data i jego pliki muszą należeć do UID10001 i być dostępne tylko
temu użytkownikowi; klucze/config tylko do odczytu. Zapis na dysk/UPS,
polityka retencji i monitoring wolnego miejsca należą do odbioru hosta.

Prywatny settings.json zawiera:

```json
{
  "database": "/var/lib/ledger/receiver.sqlite",
  "identity": {
    "installation_id": "UUID z odebranej konfiguracji źródła",
    "stream_id": "UUID z odebranej konfiguracji źródła",
    "anchor_id": "UUID z odebranej konfiguracji źródła",
    "receiver_id": "UUID niezależnego odbiorcy",
    "issuer": "dokładny issuer cutover"
  },
  "source_key_file": "/run/ledger/source.key",
  "ack_key_file": "/run/ledger/ack.key",
  "bearer_file": "/run/ledger/bearer.txt",
  "tls_cert": "/run/ledger/tls.crt",
  "tls_key": "/run/ledger/tls.key",
  "bind": "0.0.0.0",
  "port": 18445
}
```

To opis pól, nie wykonawcza konfiguracja ani prawdziwe UUID/sekrety.
Najpierw jawne `init --settings <private>`, następnie `serve`. `export`
i `freeze` zapisują wyłącznie nowy wskazany plik; istniejących nie nadpisują.
[Dockerfile](../../infra/integration/ledger/Dockerfile) budujemy z kontekstem
infra/integration na dokładnym odebranym obrazie backendu zawierającym PR124.
[Compose](../../infra/integration/ledger/compose.yaml) domyślnie publikuje
wyłącznie loopback. Wystawienie poza host wymaga wybranego endpointu,
ograniczenia źródeł zapory, rzeczywistej kontroli TLS i osobnego odbioru O3.

Nie przycinamy prefiksu. Rotacja strumienia/retencja wymagają odrębnego
cutover i zachowania pełnego pokrycia wszystkich możliwych kopii. Cofnięcia
całego hosta lub jego dysku nie da się wykryć samą cofniętą bazą: potrzebne
są niezależne checkpointy/cutoff, inwentarz hostów i odtwarzanie kluczy.
Snapshot plików bazy musi uwzględniać WAL albo używać SQLite backup API.

## Dowody lokalne i pozostałe wejścia

30testów PASS: prawdziwy TLS i transport HTTPS A2, restart, replay,
wielu nadawców,7zmian pin/kluczy,4uszkodzenia batcha,6uszkodzeń trwałego
stanu, odmowa brakującej bazy, awaria commit bez ACK oraz rzeczywisty proces
przerwany po commit/przed ACK. Cutoff/freeze zachowane po restarcie,
autoryzacja i błędy HTTP bez ujawnienia treści. Cztery nowe regresje pokrywają
nakładające się batchy, brak uwierzytelnionego pokrycia, nieciągły replay i
rzeczywisty równoległy commit podczas restartu. Izolowana mutacja usuwająca
BEGIN snapshotu daje1FAIL; pliki źródeł nie były zmieniane przez mutację.

Testy wykonano na lokalnym Windows i dokładnym kontrakcie rodzica.
Obraz backendu i pochodny obraz odbiornika zbudowano lokalnie; rzeczywisty
Linux UID10001/read-only/no-network przeszedł init→ACK→restart→replay→freeze.
SHA256 źródła wykonawczego6fc3824b4ec4c9292002557058ce926aea3185e8f604649dbe3858117d77dd10. Nie są
dowodem niezależności hostów, pełnego PG→HTTPS→ACK źródła ani produkcyjnego
KO32/RPO/RTO. Test SQLite nie zastępuje testów źródłowego PostgreSQL.

Pozostałe: zielony PR124/odbiór koordynatora; drugi host/adres/dostęp;
klucze poza źródłem i ich niezależne odzyskanie; rzeczywisty eksport PG,
przerwa sieci/restart odbiorcy/odmowa efektu bez ACK; fizyczny fencing
API/workerów/provider credentials/issuance/replik i podpisany cutoff;
ponowny cutover/reconciliation O2 oraz telefon O1 w poniedziałek.

Źródła trwałości i TLS: [SQLite synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous),
[SQLite WAL](https://www.sqlite.org/wal.html),
[Uvicorn settings](https://www.uvicorn.org/settings/).
