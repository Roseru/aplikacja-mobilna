# Natywny lokalny Mailpit dla Keycloak

`mail_sink.py` jest osobnym, opcjonalnym helperem Windows amd64. Nie zmienia
domyślnego realm, adaptera `native.py` ani istniejących instalacji. Obsługuje
wyłącznie własny stan pod `.tools` bieżącego checkoutu. Native integrator
podłącza go jawnie do swojego realm podczas próby rejestracji/resetu.

Mailpit **1.32.0** jest przypięty do [oficjalnego wydania](https://github.com/axllent/mailpit/releases/tag/v1.32.0).
[Oficjalne metadane assetu 667222096](https://api.github.com/repos/axllent/mailpit/releases/assets/667222096)
publikują `digest` SHA256 dla `mailpit-windows-amd64.zip`; wydanie nie zawiera
osobnego `checksums.txt`. Helper sprawdza archiwum oraz rozpakowany plik przed
uruchomieniem. Przy zmianie wydania oba piny wymagają jawnego przeglądu.

| Plik | SHA256 |
|---|---|
| ZIP | `16915767a6c95dca569336e8f561f91cf355e9a33c57b91deedcc10a4bba7fd4` |
| mailpit.exe | `9276bbcd182565f2acd594ca1178da667c6b5b716a75e8da979c103c38fc1280` |

## Przygotowanie i lifecycle

Wybierz nowy katalog i istniejące oficjalne archiwum. `init` kopiuje wyłącznie
przypięty EXE i LICENSE do własnego stanu. Alternatywnie jawne `--download`
zamiast `--archive` pobiera dokładnie wskazany ZIP z GitHuba. `up`, `status`
i `down` nie pobierają plików ani nie sprawdzają najnowszej wersji.

```powershell
$MailState = Join-Path (Get-Location) '.tools/native-mail'
& $Python infra/local/integration/mail_sink.py init --state $MailState --archive $MailpitZip
& $Python infra/local/integration/mail_sink.py up --state $MailState
& $Python infra/local/integration/mail_sink.py status --state $MailState
& $Python infra/local/integration/mail_sink.py down --state $MailState
```

`init` odmawia istniejącego katalogu. Nie kasuj go po błędzie; zachowaj materiał
do diagnozy. `up` istniejącego, poprawnego procesu jest idempotentne. `down/up`
zachowuje bazę SQLite, WAL, poświadczenia i historię lifecycle. Limit Mailpit
utrzymuje ostatnie **100 wiadomości**, okresowo usuwając starsze; limit jednej
wiadomości wynosi **1 MiB**, a odbiorców jednej wiadomości **10**. Dane do
dłuższego odbioru należy przechowywać osobno prywatnie przed przekroczeniem limitu.

Porty są stałe: SMTP **127.0.0.1:26525**, HTTP UI/API **127.0.0.1:28025**.
Helper sprawdza konflikt, dokładny PID, czas utworzenia, EXE, SHA256, pełną
komendę, własny stan i oba adresy/porty. Obcy PID, wildcard lub zmiana komendy
powodują odmowę; nie ma zatrzymywania po nazwie ani drzewa procesów. Zatrzymanie
używa uchwytu Windows do konkretnego procesu i ponownie sprawdza czas utworzenia.
Blokada OS serializuje `up/down`. Nie ma usługi Windows, firewall rule ani relay.

## Jawne podłączenie własnego realm

| Pole Keycloak Email | Wartość |
|---|---|
| Host | `127.0.0.1` |
| Port | `26525` |
| From | `noreply@calorie-demo.test` |
| Authentication, SSL, StartTLS | wyłączone wyłącznie dla tego loopback SMTP |

SMTP odrzuca odbiorców spoza `invalid.example`, `example.test`, `calorie-demo.test`.
Nie ma przekazywania poczty. Środowisko procesu ma allowlistę podstawowych zmiennych
Windows, bez odziedziczonych `MP_*`, proxy, relay, forward, webhook czy POP3 auth.
Sprawdzanie wersji i reverse DNS są wyłączone. Nie uruchamiaj narzędzi Link Check,
HTML Check, Screenshot ani zewnętrznych linków ze skrzynki podczas odbioru.
Mailpit przechwytuje SMTP; sam helper nie wykonuje połączeń do dostawców SSO.

UI/API wymaga Basic Auth; losowe dane są tylko w prywatnym `auth.txt`.
Katalog stanu otrzymuje chroniony ACL wyłącznie bieżącego SID i SYSTEM,
dziedziczony przez bazę, WAL i prywatny log. Lifecycle odmawia szerszego ACL.
Loopback jest dostępny procesom tego komputera; nie stanowi izolacji od
administratora lub innych procesów działających jako ten sam użytkownik.
Pełne wiadomości i aktywne linki odzyskania pozostają prywatne. Nie publikuj
widoku UI, plików bazy, auth, logów ani treści API w repozytorium lub raportach.

## Interfejs do verifera i testy

Python: `initialize(state, archive=Path(...))`, `up(state)`, `status(state)`,
`down(state)`. Status zwraca neutralne `running`, `host`, `smtp_port`, `http_port`,
`version`, `zip_sha256`, `exe_sha256` oraz `messages` przy działającej skrzynce.
Dokładny marker procesu pozostaje w prywatnym `process.json`.

`mailbox_json(state)` zwraca w pamięci prywatną listę; `mailbox_json(state,
"/api/v1/message/<ID>")` odczytuje wiadomość (22 znaki ID Mailpit). Weryfikuje własny proces,
porty i ACL. Nie drukuj zwróconej struktury. Odbiór rejestracji/resetu powinien
zapisywać wyłącznie bool/liczności/hashe i używać linku w pamięci. Helper
odmawia innych endpointów, omija proxy środowiska i nie podąża za redirectami.

```powershell
& $Python -m pytest infra/integration/tests/test_native_mail_sink.py --basetemp $NewPrivateTemp
# Osobny jawny odbiór realnego Windows SMTP; archiwum pozostaje tylko lokalne:
$env:NATIVE_MAIL_SINK_ARCHIVE = $MailpitZip
& $Python -m pytest infra/integration/tests/test_native_mail_sink.py --basetemp $AnotherNewPrivateTemp
Remove-Item Env:NATIVE_MAIL_SINK_ARCHIVE
```

Realny test tworzy własny stan `.tools/mail-acceptance-<uuid>`, wysyła jedną
wiadomość syntetyczną i odczytuje ją przez HTTP, sprawdza odmowę domeny/rozmiaru,
UI Auth, Host allowlist, restart oraz odmowę zatrzymania osobnego procesu
zajmującego port. Kończy własny sink i zachowuje bazę, FAIL oraz neutralny
`acceptance.json`. Nie potwierdza formularza Keycloak, PKCE, Androida lub wysyłki
na prawdziwy adres. Te próby prowadzi integrator na własnym realm.

Źródła flag: [runtime options](https://mailpit.axllent.org/docs/configuration/runtime-options/),
[hasła](https://mailpit.axllent.org/docs/configuration/passwords/),
[trwała skrzynka i pruning](https://mailpit.axllent.org/docs/configuration/email-storage/).
