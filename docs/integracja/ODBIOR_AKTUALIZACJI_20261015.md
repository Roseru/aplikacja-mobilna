# Odbiór aktualizacji środowiska integracyjnego — 15.10.2026

Autor: agent 3 / O3. Wynik wdrożenia: **PASS**, 13:04:46–13:05:23 CEST.
Definicje usług przyjęto w [PR #97](https://github.com/Roseru/aplikacja-mobilna/pull/97);
wdrożono je na istniejącym środowisku z aktualnego `main` `021c845`.

| Element | Przed | Po | Potwierdzenie |
|---|---|---|---|
| Keycloak | 26.8.0 | 26.8.1 | Wersja w działającym kontenerze, gotowość, discovery i rzeczywiste PKCE |
| Caddy | 2.10.2 | 2.11.6 | Wersja w działającym kontenerze, HTTPS z dotychczasowym CA |
| PostgreSQL | 17 | 17 | Zachowany obraz i wolumen istniejącej bazy |
| Backend | Dotychczasowy obraz | Ten sam obraz | Bez przebudowy API i migracji aplikacji |

Obrazy źródłowe pozostają przypięte do digestów w
[Keycloak.Dockerfile](../../infra/integration/Keycloak.Dockerfile) i
[compose.yaml](../../infra/integration/compose.yaml).

## Kopia i próba przed wdrożeniem

- Po zatrzymaniu wejścia i wszystkich usług zapisujących wykonano świeżą,
  spójną kopię obu baz, ról, katalogu oraz konfiguracji i tożsamości TLS.
  Zweryfikowano manifest i sumy plików; oryginalne usługi wznowiono.
- Istniejący harness odtworzył obie bazy do odizolowanego PostgreSQL17.
  Odbiór restore zaliczony; czas próby 13,504 s. Rotacja epoch i sprawdzenia
  odcięcia starych danych dotyczyły wyłącznie kopii testowej.
- Osobna próba Keycloak użyła odtworzonej bazy w wewnętrznej sieci Docker,
  bez portów hosta i bez dostępu do właściwej bazy. Nowy obraz 26.8.1 osiągnął
  gotowość, zachował fingerprint tożsamości, a liczba wpisów changelogu
  pozostała 237. Następnie stary obraz 26.8.0 również osiągnął gotowość
  na tej kopii z zachowaniem tożsamości. Kontenery i sieć próby usunięto.
- Przed właściwą wymianą usług wykonano jeszcze jedną spójną kopię przy
  zatrzymanych zapisach. Zachowano stare obrazy pod identyfikatorami do
  ewentualnego wycofania. Wycofanie działającego środowiska nie było potrzebne.

## Sprawdzenie po wymianie usług

1. Porównano fingerprinty pełnej zawartości wszystkich **86 tabel** schematu
   aplikacji przy zatrzymanych usługach zapisujących: wynik identyczny.
   Epoch, konta i dane aplikacji zachowane.
2. Fingerprint istniejących tożsamości Keycloak pozostał identyczny.
   Zachowano konfigurację, dane logowania, realm, issuer, CA i certyfikaty.
3. Po wznowieniu usług: gotowość API i discovery PASS. Oba istniejące konta
   A/B zaliczyły rzeczywisty Authorization Code + PKCE S256; walidowano podpis
   ID tokenu, issuer, audience i nonce. Odczyty `/api/v1/me` oraz
   `/api/v1/me/motivation` zwróciły 200 dla obu kont. Treść profili odpowiada
   stanowi sprzed wdrożenia.
4. Próba zachowała oryginalną nazwę/adres w HTTPS, issuer i weryfikację CA;
   jedynie lokalne połączenie skierowano do istniejącego wejścia loopback.
   Nie wyłączano sprawdzania TLS i nie zmieniano kont do wykonania próby.
5. Monitoring po wdrożeniu: API, Keycloak, PostgreSQL, retencja, motywacja,
   lifecycle, miejsce i TLS OK. Finalizer pozostaje `expected_disabled`.

Prywatne kopie, dzienniki operacji i receipt z porównaniami pozostają poza
publikowanym repozytorium. Ten odbiór dotyczy istniejącego środowiska O3;
nie zastępuje zdalnej próby APK przez O1, odbioru O2, wdrożenia VPS ani
automatycznej kopii poza hostem. Monitoring nadal oznacza harmonogram kopii
jako `not_configured`, a AI jako `not_deployed`.

## Przegląd zgodności

Przeczytano [zmiany migracyjne Keycloak26.8.1](https://www.keycloak.org/docs/latest/upgrading/index.html#_migrating_to_26_8_1)
oraz [wydanie Caddy2.11.6](https://github.com/caddyserver/caddy/releases/tag/v2.11.6).
Konfiguracja importowanego realmu nie korzysta ze SMTP, zewnętrznych dostawców
tożsamości ani authenticatorów X.509. Właściwy wynik zgodności logowania
potwierdza powyższa próba na kopii oraz rzeczywiste PKCE na istniejących kontach.

Reguły PostgreSQL17 dla obu nazw obrazu (`postgres` i `library/postgres`)
są scalone w [PR #103](https://github.com/Roseru/aplikacja-mobilna/pull/103).
Narzędzia z propozycji100–102 przechodzą wspólny odbiór w
[PR #104](https://github.com/Roseru/aplikacja-mobilna/pull/104); jego aktualny
wynik CI należy odczytać dla końcowego head, osobno od wyniku tego wdrożenia.
