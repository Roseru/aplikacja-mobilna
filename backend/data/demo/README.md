# Dane demo E2 i pochodzenie - osoba 2

`seed.json` jest kontrolowanym wejściem do PostgreSQL: dokładną kopią
[znormalizowanego przykładu E0](../../../contracts/examples/valid/catalog-demo.json).
Nie jest eksportem ani oficjalną etykietą. Jego SHA-256:
`e0b70e1c0b1f24d2a3d3e098c4bb3838b63f0a948567d601cb00ea199124d928`.
Test kontraktowy sprawdza identyczność bajtów; oba pliki zachowują je w Git.

Materiał źródłowy [S-RG-1](../../../docs/materialy/racja_wojskowa_S-RG-1.source.json)
pozostaje niezmieniony (SHA-256
`e79a1781e40af020e7affe9cac60fb6eb65b5d5b8c72bb568d62bb7edbaa55e2`).
[Rejestr źródeł](../../../docs/e0/ZRODLA_KATALOGU.md) opisuje normalizację,
niepotwierdzoną podstawę wartości i braki etykiet. 18 policzalnych pozycji,
4 bez danych oraz wyposażenie i sól/pieprz są zachowane. Baton jest opcjonalny,
proszek pozostaje w g. Deklaracje 3466/3468/3600 kcal są osobnymi informacjami.
Nie podstawiamy S-RG-1 pod ARPOL WZ 1/WZ 4 WEGE.

`export/` zawiera **rzeczywisty eksport E2 z PostgreSQL 17**:
[gzip](export/base-pl.1.json.gz) i [manifest](export/manifest.json).
Kolejność rekordów UUID/revision oraz kanoniczne, zwarte UTF-8 są ustalone przez
eksporter. Dlatego bajty różnią się od dawnego gzip fixture'a E0.

| Właściwość eksportu | Wartość |
|---|---|
| package_id / kind / release | `47bdff67-e58b-5437-919b-ec00159afbc5` / `demo` / `1` |
| schema_version / min_reader_version | `1` / `1` |
| Gzip / JSON | 3099 B / 15691 B |
| SHA-256 gzip | `65f4aae8002fd5522d0edb4689e05682103b80fbe3e6dbc68f4bf02c645b2bef` |
| Liczności | 18 produktów, 1 racja, 18 składników, 1 źródło |
| published_at | `2026-10-09T12:00:00Z`, ustalone wydanie E0 |

Pole `published_at` opisuje ustalone wydanie danych, nie czas kolejnego eksportu
ani weryfikację żywieniową. Demo ma `unverified`, racja `complete=false`.
Odtworzenie: komendy operatora import/export w [backend README](../../README.md).
Importer referencyjny i [adaptacja O1](../../../docs/e2/INTEGRACJA_O1.md) używają
tych plików lokalnie; publiczny kanał official ich nie udostępnia.
