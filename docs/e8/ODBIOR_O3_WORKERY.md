# Lokalny odbiór workerów E8 — Agent 3

13 października2026. Gałąź `codex/devops-e8-workers`, baza
`8f0716593a276f8df2515024dc4dd10d0f19ef52` (scalone PR42/43).
Zakres: osobne procesy motywacji, lifecycle i projection-only finalizera,
minimalne role, minutowe wywołania, zagregowany status i restart.
Wymagania:11.7/KO-29, przekazania O3 E8.1–E8.4.

Publikacja: [PR44](https://github.com/Roseru/aplikacja-mobilna/pull/44).
Pierwszy head `1ba26dc` / [CI38344602419](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38344602419)
wykonał1658 unit i32 infra PASS4,11s, installed wheel-I PASS; późniejszy Docker build
otrzymał rzeczywiste429/data-limit z publicznego registry ECR. Cały job quality
pozostaje failure, bez nazywania go zielonym. Próba ponowienia tego jednego joba
przez dostępne API dostała403. Niniejsze doprecyzowanie publikacji i granic
odbioru uruchamia nowy wymagany zestaw CI; wcześniejsze wyniki pozostają historią.

## Wynik i dostawa

Opcjonalny overlay Compose uruchamia trzy zainstalowane CLI z wheel przez
Python `-I`, UID10001, read-only/no-new-privileges/cap_dropALL, z oddzielnymi
LOGINami i prywatnymi wolumenami statusu. Wykorzystuje istniejące provisionery,
funkcje i ograniczone partie O2; nie zmienia reguł obliczeń, migracji0001–0021,
API lub istniejącego konta retencji. Start nie otwiera capability.
Zamknięty finalizer ma stan disabled i unhealthy, bez fałszywego last_success.
Świadoma aktywacja jest osobną owner-only czynnością.

Runner uruchamia pierwszy cykl natychmiast, dalsze co60s bez nakładania procesów.
Timeout, sygnał zatrzymania i nieprawidłowy wynik nie są sukcesem. Status
allowlistuje liczby i daty; nie zapisuje stdout/stderr, credentiali, UUID,
payloadów lub prywatnych wierszy. Zachowany last_success oznacza ostatni
udany bounded przebieg, nie pustą kolejkę. Szczegóły i polecenia są w
[instrukcji](../../infra/integration/README.md#opcjonalne-workery-e8).

## Wykonane lokalne dowody

Własny nowy Compose project, wolumeny, port HTTPS i CA; cudzy istniejący zestaw
integracyjny nietknięty. PostgreSQL17 z przypiętego obrazu, aktualna0021,
zbudowany backend bez editable i `/app/src`, rzeczywisty Keycloak oraz HTTPS/PKCE.
Sekrety/logi/receipts pozostają poza Git.

- Istniejący pełny lokalny odbiór infrastruktury PASS: TLS/exactissuer/odmowa
  nieznanegoCA, Android callbacks/PKCE/nonce, A/B, idempotencja i checkpoint,
  role/UID/read-only katalog oraz down/up obu baz i danych bez zmiany epoki.
- Własna nowa próba używa realnego HTTPS/OIDC do profili, źródłowych operacji
  synchronizacji i accepted7d Nemesis. Dzień obu kont pozostaje pending z0
  materialized points; lokalny minutowy scheduler po maturity nalicza4 punkty,
  lifecycle zapisuje finished, finalizer utrwala dokładnie dwa wyniki.
  Do przekroczenia maturity/deadline właściciel wyłącznie testowej bazy podmienił
  dwa zegary na przyszły czas. To syntetyczne granice czasu, nie produkcyjne
  odczekanie37dni. Źródła/projekcje/manifest i worker entrypoints nie były
  fałszowane; zegary przywrócono w finally, bramkę zamknięto.
- Stop/start trzech usług natychmiast nadrabia cykl, zachowuje4 punkty,
  byte-identyczne dwa końcowe wiersze i sync_epoch. Nie uruchamia nowego klienta
  i nie duplikuje nagród/wyników.
- Faktyczne trzy SCRAM LOGINy: brak SUPER, CREATEapp, CONNECTKeycloak,
  raw source SELECT i SET ROLE. Wszystkie usługi UID10001 i installedCLI-I.
- Błędy własnego harnessu zachowane jawnie: publiczna odpowiedź nie zawierała
  użytego pola deadline_at; poprawiono prywatny SELECT. Późniejszy ACL probe
  wskazał nieistniejącą diary_meals zamiast meals; poprawiono sam probe i wykonano
  tylko dotknięte ACL/UID. Wcześniejsze due/restart PASS nie są liczone ponownie.

Wersjonowane testy runnera obejmują faktyczne procesy dziecka, timeout/stop,
nieudany spawn, redakcję nieprawidłowego wyjścia, zamkniętą bramkę, pending,
stare/przyszłe timestampy oraz zachowanie istniejących haseł. CI dodatkowo
wykonuje realne startup/minutowy cykl/LOGIN/restart na własnej instalacji.
Lokalny PASS nie zastępuje zdalnych kontroli finalnego PR/main.

## Dodatkowy niezależny odbiór E8.4

Na bezpośrednią zgodę właściciela odrębny nieautor sprawdził dokładną średnią
na freeze8f07165 (backend identyczny22d6bc9). Ocena9,4/10, brak wykrytych
otwartychP1/P2 w zakresie. Własne18 przypadków Python:7/30/90, sign±,
poniżej/remis/powyżej HALF_UP, różne mianowniki, trzy konteksty Decimal ztraps.
Własne6 HTTP/PG PASS25,29s: trzy historyczne E, kasowanie, exacttie, brakE,
provisional/final/retry i404C. Osobny noneditable wheel Python-I smoke90d PASS.
Pierwotny6F dotyczył wyłącznie nazwy deadline zamiast deadline_at w prywatnym
teście; autorów źródeł nie zmieniono. Recenzent usunął własny oznakowany PG.
Prywatny raport SHA256 `0dcfec183eadc4815969a8dec249263f93202256afdfdbb52ce63e887354ae2e`.
Te dowody nie zastępują pełnej regresji, TLS, APK lub odbioru zespołowego E8.

## Otwarte granice

Lokalne procesy i dostępność ich poleceń są odebrane w opisanym zakresie.
Produkcyjny rollout, public origin/API/issuer/CA dla O1 oraz spójny
backup/restore/fencing/RPO/RTO pozostają osobnym zadaniem O3. Ten PR nie
zamienia pełnego E8 w PASS i nie dotyka E9, Google, billing lub harmonogramów
Codex PAUSED. Następny własny zakres to spójna kopia i próbne odtworzenie
lokalnej aplikacji/Keycloak z fencing przed otwarciem ruchu.
