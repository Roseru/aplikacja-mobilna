# Importer referencyjny SQLite - osoba 2

Importer jest częścią instalowanego pakietu `calorie-backend`. Nie wymaga sieci,
`DATABASE_URL`, PostgreSQL ani uruchomienia API. Schematy walidacji są zasobami
pakietu; moduł działa również poza checkoutem. Wrapper `import_catalog.py` wywołuje
ten sam moduł i wymaga uprzedniej instalacji backendu.

Przykład PowerShell po instalacji backendu (`pip install ./backend` w środowisku
Python 3.13):

```powershell
python -m calorie_app.modules.catalog.offline_import `
  --database ./catalog.sqlite `
  --manifest ./backend/data/demo/export/manifest.json `
  --package ./backend/data/demo/export/base-pl.1.json.gz `
  --expected-package-id 47bdff67-e58b-5437-919b-ec00159afbc5 `
  --expected-kind demo
```

Ścieżki manifestu i gzip są lokalne; importer nie pobiera URL ze źródeł. Oczekiwany
UUID i kanał pochodzą z zaufanej konfiguracji aplikacji, nie z importowanego pliku.
Hash sprawdza zgodność bajtów; autentyczność wynika z zaufanej dostawy HTTPS lub
podpisanego APK. Demo nie jest zweryfikowanym katalogiem official.

Biblioteka udostępnia:

```python
from calorie_app.modules.catalog.offline_import import OfflineCatalog

catalog = OfflineCatalog("catalog.sqlite", trusted_package_id, "demo")
generation = catalog.stage("manifest.json", "base-pl.1.json.gz")
# generation jest trwałym UUID; można przechować go i uruchomić ponownie proces.
changed = catalog.activate(generation)
package = catalog.read_active_package()
# Skrót obu etapów: catalog.import_package(manifest_path, package_path) -> bool.
```

`stage` sprawdza manifest do 1 MiB, gzip do 10 MiB i JSON do 50 MiB podczas
odczytu/dekompresji, przed parsowaniem. Sprawdza pojedynczy kompletny strumień gzip,
CRC, rozmiary, SHA-256, tożsamość, nagłówki, liczności, źródła i wspólne reguły E0.
Niekanoniczne Decimal, duplikaty i niepoprawny graf są odrzucane.

Staging zapisuje całą nieaktywną generację w transakcji. Tabele mają prefiks
`catalog_`; wersje UUID+revision i snapshoty źródeł są niezmienne globalnie, także
między kanałami. Decimal trafia do kolumn `TEXT`, bez konwersji do float/REAL.
Relacyjne FK wskazują dokładne wersje, a członkostwo zachowuje kolejność pakietu.
Historia, outbox i przypięte starsze wersje pozostają na miejscu; E2 nie sprząta
wersji ani generacji.

`activate` w krótkiej transakcji `BEGIN IMMEDIATE` ponownie porównuje release.
Aktywuje tylko kompletną nowszą generację. Identyczne ponowienie i aktywacja
starszego release zwracają `False`; zmienione bajty tego samego release są błędem.
Odwrócona kolejność zakończenia importów nie cofa katalogu. WAL pozwala czytelnikom
korzystać z poprzedniej generacji podczas stagingu. Restart i błąd zapisu/commit
przed aktywacją pozostawiają poprzedni katalog. Prywatne haki
`_before_stage_commit(connection)` i `_before_activate_commit(connection)` służą
wyłącznie testom awarii; wyjątek wycofuje transakcję.

Błędy danych mają `OfflineImportError.code` lub `CatalogValidationError.code`.
Błędy SQLite i plików nie są maskowane w bibliotece. CLI zwraca kod 1 oraz opis
błędu; sukces zwraca kod 0 i JSON z aktywnym release i flagą `activated`.

To wzorzec SQLite, a nie importer Room ani dowód uruchomienia aplikacji Android.
O1 musi zaadaptować transakcje/wersje do Room i osobno sprawdzić APK bez sieci,
przypięte snapshoty historii oraz outbox.
