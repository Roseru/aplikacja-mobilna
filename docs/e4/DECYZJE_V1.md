# Decyzje protokołu E4 v1 - osoba 2

Wersja decyzji: 1, 10 października 2026. Obowiązuje sześć typów i DTO
z generowanego [OpenAPI](../../backend/openapi.json) oraz
[schematu v1](../../contracts/schemas/sync.schema.json).

Pełny preflight obejmuje rzeczywiste bajty ASGI, ścisły UTF-8/JSON, strukturę
całej paczki, rolę, active/bootstrap, epoki i podpisany checkpoint. Jego odmowa
nie zapisuje encji, receipts ani zmian. Payload liczymy jako oryginalny fragment
JSON wraz z odstępami i escape, przed normalizacją; limit 262144 B daje 413
całej paczki. Limit żądania wynosi 1048576 B. Kod historyczny entity_too_large
nie jest już aktywnym wynikiem operacji; odmowa schematu daje 422 invalid_request.
Content-Encoding inne niż identity jest jawnie odrzucane.

Każda operacja ma osobną transakcję: konto → licznik → encje, ponowna kontrola
kontekstu i zegar DB po oczekiwaniu, receipt przed rewizją, savepoint mutacji,
deferred constraints, zmiany i receipt, commit, ACK. Odmowa domenowa cofa
cały savepoint, także automatyczny dzień i oś celu. Deadlock/serialization mają
najwyżej trzy próby bez zmiany ID; awaria DB daje 503 i nie staje się
utrwalonym invalid_payload. Brak miejsca licznika jest sync_counter_exhausted;
wyczerpanie rewizji encji/osi jest trwałym rejected/revision_exhausted.

Późny błąd po commit operacji kończy HTTP bez nowych ACK. Prefix pozostaje
zatwierdzony; klient zachowuje całą kolejkę. Na active koncie z bieżącą epoką
po pull/uzgodnieniu identyczne ID rozpoznają prefix. Zmiana epoki wymaga
nowych świadomych operacji recovery; deleting pozostaje blokadą dostępu.
SyncError nadal ma dokładnie code/message/details/request_id; details jest
obiektem, odrębnym od listy błędów E3. Nie ma completed_results.

Podpisy HMAC-SHA256 używają trwałego CATALOG_PAGE_TOKEN_SECRET z oddzielnym
prefiksem sync1. Wiążą owner, generation, protocol=1, epokę instalacji i rodzaj
tokenu. Losowa trwała epoka E3 identyfikuje kontekst instalacji; zmiana instalacji
lub restore wymaga nowej epoki i kontroli konfiguracji sekretu. Checkpoint jest
ważny dokładnie 30×24 h; sesja materializacji wygasa w chwili 60 min. Tylko
końcowa strona wydaje checkpoint, a jej wynik i pierwszy czas wystawienia
pozostają trwałe. Page/snapshot tokens nie uprawniają do push.

Snapshot i incremental materializują kopię w repeatable read z H i rewizją osi
jednego odczytu. Limity: cztery sesje na owner, 100000 elementów i 64 MiB
na sesję, 1 MiB odpowiedzi i wspólne 1–500 elementów trzech tablic. Zasoby
przekroczone dają sync_resources_exhausted bez checkpointu. Prune jest
ograniczone i respektuje aktywne kopie; minimalne dowody nie wygasają.
Rodzice/tombstones pozostają konserwatywnie do usunięcia konta, także gdy
szczegóły receipts/ChangeLog zostały po 60 dniach zminimalizowane. To świadomy
wybór chroniący FK i historię, nie obietnica usunięcia wszystkich szczegółów
w chwili osiągnięcia 60 dni.

Usunięcie konta inicjuje operatorowy CLI begin/resume/status z UUID operacji
i oczekiwaną generacją. Nie dodajemy DELETE /me. Subject pochodzi z DB;
adapter używa exact issuer → realm/admin URL z konfiguracji. Potwierdzenie
autoryzowanego braku tożsamości ma osobny commit przed wąskim purge grafu.
Minimalna blokada subject jest trwała; wyliczony block_until obejmuje minimum
420 s i późniejszy max exp+skew. Szczegóły [procedury](USUNIECIE_KONTA.md).
