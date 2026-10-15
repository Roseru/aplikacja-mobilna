# Kandydat serwera — przygotowane obrazy O3

14.10.2026, agent3/O3. Właściciel polecił wykonać samodzielnie dostępne zadania
i pominąć kroki wymagające jego dostępu/budżetu/decyzji podczas nieobecności.
Przygotowano rzeczywisty pakiet czterech obrazów; wdrożenie produkcji pozostaje pominięte.

[Szkic wydania GitHub](https://github.com/Roseru/aplikacja-mobilna/releases/tag/untagged-2b861c5844a1025b6a98)
ma id412947854, jest draft/prerelease i wymaga dostępu do szkiców repozytorium.
Wysłano manifest.json, README.md, source.tar i server-images.tar. Odrębne GET
GitHuba potwierdziły stan uploaded, każdy rozmiar i digest SHA-256 zgodny z lokalnym plikiem.
To dostawa obrazów i źródeł, nie kopia danych instalacji.

## Źródło i faktyczny odbiór

- Main `c806d5e4c05e3a03ca3745283bacd372a5814d3e`, tree
  `eec4dcbc1611a198081f54af85951814a8a6527b`: osiem success CI38589726448,
  identyczne z odebranym source `fa56d0680f584eee05d8220b029c3c77ea6071d4` / CI38586303813.
- Backend i Keycloak zbudowano z archiwum wersjonowanych źródeł tego commita,
  z OCI revision/source. Python3.13, Keycloak26.8.0, PG17 i Caddy2.10.2 zachowują
  bazowe digests przyjętej konfiguracji; nie użyto propozycji Dependabot PG18.
- Cztery obrazy Linux/amd64 mają referencje `calorie-backend`, `calorie-keycloak`,
  `calorie-postgres17`, `calorie-caddy`, tagowane `git-<pełny SHA źródła>`.
  Manifest zawiera rzeczywiste image IDs, config digests i liczbę sprawdzonych warstw.
- Rzeczywisty smoke jednorazowego obrazu, bez sieci: backend UID10001/version0.1.0
  i schema0024_e9_history_graph; Keycloak version26.8.0. Bieżących usług nie podmieniono.
- Zweryfikowano łańcuch indeks → manifest platformy → konfiguracja → wszystkie dostępne
  warstwy oraz hashe plików. Pierwsza błędna asercja utożsamiała imageID z config digest;
  wykryto ją i poprawiono przed odbiorem. Używany [magazyn Docker containerd](https://docs.docker.com/desktop/features/containerd/)
  obsługuje indeksy i manifesty; ich osobne digests zachowano.

| Plik | Bajty | SHA-256 |
|---|---:|---|
| source.tar | 5232640 | c0b7bda42fbc0d6a0df0ff2497a9666e2a505771e709719cd661c039bc58362c |
| server-images.tar | 527633408 | 9ba8fcd79602bc77823252df3e0a29f1d9f73a131e1af0a2575eccd1af6646d5 |

## Użycie i granice

Po pobraniu i sprawdzeniu SHA-256: `docker image load --input server-images.tar`.
Import nie uruchamia usług ani migracji. Dopasowanie istniejącego celu, prywatnej
konfiguracji/realm/ACL/SMTP, backupu i smoke należy do odrębnego wdrożenia.

Pakiet nie ma kont, kluczy, prywatnej konfiguracji, DB ani APK. Source.tar obejmuje
wyłącznie wersjonowane backend/infra źródłowego commita. Nie zawiera kodu monitoringu
z późniejszego PR84; ten ma własny odbiór i prywatny harmonogram opisany w
[monitoringu](../infra/integration/MONITORING.md). PR84 nie zmienia źródeł backendu.

Nie zaliczono produkcyjnego deploy/migracji/rollbacku, offsite danych/RPO/RTO ani
podpisanego APK. Nie wolno uznać wcześniejszego obrazu z innym EXPECTED_REVISION za
zgodny rollback schematu0024; obowiązuje [kontrakt O2](e9/KONFIGURACJA_O3.md).
Free Tier/model/klucz Gemini pozostają wejściem A1, bez aktywacji live.
