# Ciągły rejestr usunięć O2 — kontrakt v1

Zlecenie O2_LEDGER_20261017_V1; wejście O3-066 / PR123,
`dd39050b69711a91023e20d7b6cfb9dad53bef44`. Baza `615fb6b3` / schema0024.
Bieżący schemat: `0026_ledger_review` po niezmiennej `0025_deletion_ledger`.
Status odbioru i dokładne CI: [PR124](https://github.com/Roseru/aplikacja-mobilna/pull/124).

## Granice i kolejność

Intencja, skutek providera, trwałe zewnętrzne potwierdzenie wyniku i odpowiedź
operatorowi są osobnymi momentami. Nie obiecujemy dokładnie jednego DELETE.
Każda zmiana domenowa zapisuje zdarzenie w tej samej transakcji PostgreSQL.
Zdarzenie intencji begin powstaje wraz z deleting/generacją/job/blocklist;
przed providerem wymagany jest ACK tej intencji oraz intencji próby providera.
Wynik providera jest zapisywany oddzielnie; brak odpowiedzi/crash oznacza
niepewność do ponownego autoryzowanego odczytu tego samego celu. Confirm wymaga
ACK wyniku providera, purge wymaga ACK confirm i intencji purge, zakończenie
wymaga ACK wyniku purge. Błąd dostawy zatrzymuje następny efekt.
Sieć nigdy nie działa w otwartej transakcji PostgreSQL.

## Strumień i cutover

Installation UUID jest trwały i niezależny od sync_epoch. Stream UUID i losowa
kotwica identyfikują jeden nieprzerwany strumień. Jeden blokowany wiersz źródła
przydziela kolejną sekwencję i aktualizuje hash łańcucha w tej samej transakcji.
Nie używamy nextval/MAX(id) ani zegara jako dowodu prefiksu. Inne appendy czekają
na commit/rollback; eksport widzi wyłącznie zatwierdzony prefiks.

Nowa migracja nie fabrykuje historii. Źródło pozostaje nieaktywne do jawnego
cutover przez migratora. Anchor oznacza początek obserwacji, nie pokrycie
starszej kopii. Zastane jobs są legacy/unknown i wymagają jawnego uzgodnienia.
Downgrade do0024 zachowuje ledger, role, bariery i dowody; poprzedni operator
jest odrzucany. Dalszy downgrade jest blokowany. Starszy obraz API zachowuje
kontrakt mobilny30dni; operator i recovery wymagają aktualizacji.

## Format i uwierzytelnienie

Wersja1 przenosi dokładne UTF-8 `content` wygenerowane jako PostgreSQL jsonb::text;
nie wolno ponownie serializować przed SHA256. Event wiąże installation/stream/
anchor, event UUID, sequence, previous hash, operation/account, exact issuer,
subject, expected/deleting generation, etap, wynik i numer próby. Chain hash =
SHA256(32 bajty poprzedniego chain hash ||32 bajty SHA256(content)).

ACK podpisuje pełny prefiks od1 do sequence wraz z końcowym chain hash, receiver,
installation, stream i anchor. Ramka ASCII: `deletion-ledger-ack-v1` oraz kolejno
installation UUID, stream UUID, anchor UUID, receiver UUID, dziesiętna sequence,
chain hash — rozdzielone LF, bez końcowego LF. HMAC-SHA256 używa losowego klucza
32bajtowego z konfiguracji migratora/odbiorcy. Eksporter/operator nie znają klucza.
SQL weryfikuje MAC przez [pgcrypto.hmac](https://www.postgresql.org/docs/17/pgcrypto.html),
porównuje źródło, dokładny hash lokalnego prefiksu i monotoniczność. Hashe bez
MAC nie uwierzytelniają źródła. Migrator/superuser i odbiorca z kluczem pozostają
granicą zaufania. Klucze/backupi źródła są poufne i wymagają ochrony O3.

Adapter transportu dostarcza ograniczone porcje do odbiorcy przypiętego do
konfiguracji, bez dowolnego URL z joba. Retry dostawy jest idempotentny względem
stream/sequence/hash. Odbiorca testowy używa własnego trwałego SQLite z FULL
synchronous i potwierdza dopiero po commit; jest testem kontraktowym, nie usługą
produkcyjną ani dowodem niezależności hostów. Wielu nadawców nie zmienia prefiksu.
Lease providera wiąże token próby; spóźniony wynik nie może zatwierdzić nowej próby.
Wygaśnięcie próby jest niepewnością, wymaga nowej utrwalonej intencji i ACK.

## Restore i odpowiedzialność O3

Walidator wymaga przypiętej kotwicy i zaufanego podpisanego cutoff dla tego samego
strumienia; nie bierze cutoff/klucza z eksportowanego pliku. Luka, obca instalacja,
replay z inną treścią, cofnięcie lub sprzeczny ACK, niezgodny issuer/cel/generacja,
brak kotwicy lub historycznego pokrycia oznacza odmowę. Pending/failed/unknown
pozostają blokujące. Uzgodnienie nigdy nie ufa nieobecności konta w starej kopii.
Zachowuje generacje i blokadę subject; nie otwiera automatycznie ruchu.

O3 odcina stare procesy i administracyjne credentials providera PRZED cutover,
potwierdza ostatni dozwolony zapis/issuance oraz odbiera magazyn poza hostem,
transport, retencję, anchor/cutoff i niezależne odzyskanie klucza. SQL/preflight
nie odbierze sekretu posiadaczowi poza protokołem. Bez dowodu fencing O3 status
produkcyjny to WAITING_EXTERNAL. Fixture recovery pozostaje fixture. Pełne KO32,
telefon O1 i produkcyjne RPO/RTO wymagają osobnych odbiorów.

## Interfejs wykonywalny i odbiór

Migracje: niezmienna `0025_deletion_ledger`, poprawka `0026_ledger_review`. Kod runtime: `deletion.py`,
`ledger_contract.py`, `ledger_transport.py`, `ledger_export.py`,
`ledger_restore.py` w module identity. PostgreSQL jest jedynym źródłem intencji,
wszystkie tabele ledgeru są zarządzane wersjonowanym SQL i wyłączone wyłącznie
z automatycznego generowania migracji ORM. Kontrola istniejących modeli pozostaje.

Funkcje operatora: `begin_account_deletion`, `ledger_status`,
`ledger_prepare_provider`, `ledger_provider_target`, `ledger_provider_result`,
`confirm_account_deletion`, `ledger_prepare_purge`, `purge_deleted_account`.
Bezpośredni SELECT jobs jest odebrany, w tym granty kolumnowe roli bazowej.
Stare resume odmawia przed siecią przy zwykłym, prawidłowo provisionowanym LOGIN.
Zewnętrzny stary sekret/proces lub uprawnienia dodane przez administratora
pozostają obowiązkiem fencing O3. `service.begin_deleting` odmawia, a SQL odcina
surowy INSERT/UPDATE state/generation/identity. Nie używamy GUC jako capability.

Eksporter ma wyłącznie funkcje `ledger_export_position`, `ledger_batch`,
`ledger_ack`, USAGE app i CONNECT. Nie zna source_key/ack_key i nie ma praw tabel.
Operator i eksporter mają odrębne rzeczywiste loginy tworzone chronionym SCRAM
provisionerem. API/zwykły worker nie mają funkcji operatora/eksportera. Funkcje
triggerowe dostępne przez PUBLIC nie mogą być wywołane jako zwykłe funkcje;
provisioner eksportera weryfikuje wszystkie pozostałe efektywne EXECUTE.

`ledger_configure(issuer,receiver_uuid,source_key,ack_key)` jest funkcją wyłącznie
migratora. Wymaga dwóch różnych losowych32-bajtowych kluczy. Nie wolno wkładać
ich do CLI/PR/logów. Włączenie wymaga wcześniejszego zewnętrznego fencing O3;
O2 nie wykonał tego na używanej instalacji. Parametry przekaż przez chronione
połączenie z ustawieniami logów jak istniejący provisioner. Anchor i identyfikatory
instalacji/strumienia wygenerowane w migracji trzeba niezależnie przypiąć u O3.
Klucze HMAC i ich odtwarzanie są częścią zaufania migratora/odbiorcy.

Jeden strumień może obejmować kilka exact issuer zapisanych w autoryzowanych
jobach. Pole issuer anchor oznacza konfigurację cutover; issuer zdarzenia celu
jest zawsze z trwałego joba. Walidator sprawdza niezmienność całej tożsamości
operacji; reconcile dodatkowo porównuje exact issuer/sub/account i generacje
z odtworzoną bazą. Nie przyjmuje celu z żądania transportu.

Dostawa: maks128zdarzeń/batch i1MiB podpisanej treści, domyślnie64zdarzenia,
8porcji/run, maks16. Zbyt duża porcja daje odmowę i wymaga mniejszego limitu.
Trzy próby dla timeout/awarii transportu/5xx, timeoutHTTP10s, krótki backoff;
4xx, zły ACK/MAC lub sprzeczny prefiks kończą przebieg. Komenda jednorazowa:

```text
python -m calorie_app.modules.identity.ledger_export
```

Konfiguracja eksportera: `LEDGER_EXPORT_DATABASE_URL`, `LEDGER_RECEIVER_URL`
(HTTPS), `LEDGER_RECEIVER_CA`, `LEDGER_RECEIVER_TOKEN`, chronione poza Git.
O3 dostarcza implementację HTTP magazynu zgodną z tym kontraktem; O2 nie tworzy
produkcyjnego odbiorcy ani harmonogramu. ACK podpisuje zakres1..sequence
konkretnego strumienia. Receipty każdego zaakceptowanego zakresu są osobne;
nie łączymy prefiksów odbiorców/instalacji. Source MAC ma osobną domenę i klucz,
a SQL podpisuje wyłącznie odczytane, zatwierdzone eventy.

`validate_restore` wymaga całego prefiksu od anchor, backup_point (ACK),
osobnego podpisanego cutoff i niezależnego argumentu `fence_pin` z otoczenia O3.
Zwykły ACK, nawet z prawidłowym MAC, nigdy nie jest cutoff. Cutoff ma domenę
`deletion-ledger-cutoff-v1`, te same pola strumienia/sequence/chain_hash co ACK
oraz `fence_id` UUID, `fence_sha256` (64 małe znaki hex) i `scope` (`production`
lub jawne `contract-test`). MAC używa ack_key i ramki ACK z nową domeną,
po której następują LF + fence_id + LF + fence_sha256 + LF + scope.
`fence_pin` zawiera cztery identyfikatory strumienia i trzy pola fence; musi
pochodzić niezależnie od eksportu, a wszystkie pola muszą zgadzać się dokładnie.
O3 przypina identyfikator i hash dowodu fizycznego zatrzymania zapisów/issuance,
a zaufany odbiorca dopiero wtedy wystawia cutoff. Hash i podpis nie dowodzą
samego zatrzymania procesów. Testowy obserwator ma scope `contract-test`;
jego dowód nie zastępuje odbioru O3. Klucza/pin nie odczytuje się z backupu. Backup sprzed anchor
lub bez przypiętego punktu nie ma ścieżki PASS. Cutoff nie wynika z zegara ani
samego najwyższego numeru. `reconcile_restore` jest zaufanym wejściem migratora:
**najpierw O3 zatrzymuje/fencuje stare procesy/issuance i rotuje sync_epoch**;
to warunek również wtedy, gdy walidator odmówi przed rozpoczęciem transakcji.
Kod porównuje lokalny snapshot head z backup_point, blokuje konto/subject,
zachowuje graf i oddzielny receipt, zamraża źródło. Identyczny replay nie tworzy
nowego pokrycia; pending/failed/unknown pozostają blokujące.

Ten etap nie dostarcza ponownej aktywacji niepustego strumienia po restore ani
odtworzenia provider DELETE/purge na nowo odtworzonym KC. Nie wolno ponownie
wywołać providera poza nową, odebraną procedurą cutover/reconciliation. To jawne
WAITING_EXTERNAL i osobny etap O2/O3 po dostarczeniu niezależnego magazynu,
fencing i cutoff; nie twierdzenie o kompletnym recovery/KO32. Istniejący runner
recovery zachowuje fixture i osobny wynik: authenticated contract block target,
source frozen, świeży token B odrzucony przez API; owned meal recovery A jest
odrębnym zakresem. Nie otwiera to instalacji produkcyjnej.

Downgrade do0024 zachowuje tabele, receipt, role i bariery. Zejście poniżej0024
jest atomowo odrzucane. Stare obrazy/operator wymagają własnej kwalifikacji;
nie deklarujemy kompatybilnego rollbacku całej instalacji. Nemesis zachowuje
sprawdzony release projekcji0024 i aktywny stan; nowa migracja aktualizuje tylko
wymagany marker Alembic aktywacji na0026, zachowując wszystkie preconditions/ACL.

Schemat i jawnie syntetyczne przykłady:
[JSON Schema v1](../../contracts/schemas/deletion-ledger-v1.schema.json),
[batch](../../contracts/examples/valid/deletion-ledger-v1-batch.json),
[ACK](../../contracts/examples/valid/deletion-ledger-v1-ack.json),
[cutoff](../../contracts/examples/valid/deletion-ledger-v1-cutoff.json).
Klucze fixture s×32/a×32 są wyłącznie testowe i nie są kotwicą produkcyjną.

Powtarzalna próba (dedykowana baza PG17 po istniejącym init-db, nie SQLite):

```text
uv sync --project backend --locked
uv run --project backend --locked python infra/integration/rehearse_deletion_ledger.py --state <nowy-prywatny-katalog>
```

Wymagane `TEST_DATABASE_URL` wskazuje własną bazę `*_test`; runner/testy odmawiają
innej bazy lub wersji PG. Dla hostowego PG17 ustaw katalog klienta przez
`E8_3_POSTGRES_BIN`; bez niego Linux używa istniejącego przypiętego obrazu klienta.
Wyniki/pełne prywatne logi pozostają w nowym katalogu, neutralny receipt podaje
head, dirty_source, liczność, brak skipów i granicę odbioru. Te same testy PG/unit
są automatycznie zbierane przez nieosłabiony backend.yml.


## Poprawki odbioru PR124 — schema0026

Odbiór `O2_PR124_REVIEW_483dcfa9_V1` wykazał dwie P2 mimo zielonego CI.
Nowa0026 zmienia funkcję guardu przed aktualizacją markera;0025 pozostaje
niezmienna. Zamiast zamkniętej listy dozwolonych24/25 guard odrzuca dokładny
zamrożony zbiór niebezpiecznych przodków0024 z liniowego grafu Alembic.
Nie porównuje nazw rewizji. Test sprawdza zgodność zbioru z rzeczywistym grafem,
neutralnego następcę o nienumerycznej nazwie oraz atomową odmowę23/niżej.
Downgrade26→25→24 zachowuje poprawiony guard, dane, role i bariery; dalszy
rollback jest odrzucany. Bezpośrednie stamp/DELETE markera i treść przyszłych
migracji wymagają osobnego review zaufanego migratora, nie są ścieżką rollbacku.

Provisioning operatora wymaga dokładnie ośmiu wywoływalnych funkcji kontraktu
oraz odmawia każdego innego efektywnego EXECUTE w schema app. Kontrola obejmuje
bezpośrednie, dziedziczone i PUBLIC granty, w tym ledger_configure, ACK, eksport
i wewnętrznych rodziców. Funkcje zwracające trigger/event_trigger nie są callable
z SQL; operator nie ma CREATE/TRIGGER pozwalającego je instalować. Odmowa
wycofuje transakcję provisionera, zachowuje zastany grant i konfigurację źródła;
ACL poprawia się jawnie przez administratora, potem ponawia provisioning.

Upgrade z zapełnionego0025 nie tworzy nowej kotwicy/strumienia ani nie zmienia
kluczy, eventów, ACK, generacji lub jobs. Aktywacja i readiness wymagają dokładnie
0026; provisionery zachowują też jawne wcześniejsze markery. Natomiast release projekcji/algorytm0024 i stare C2/receipty nie są
przemianowane. Protokół źródło/ACK/cutoff pozostaje v1. Granice O3/O1 oraz brak
wdrożenia i zakaz automatycznego otwarcia po restore pozostają w mocy.
