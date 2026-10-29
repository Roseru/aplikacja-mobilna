# Natywna kopia i odtworzenie offline

Adapter `restore.py` korzysta z istniejącego formatu pary w `infra/integration/backup.py`:
globals, `calorie_app.dump`, `keycloak.dump`, katalog i manifest SHA-256.
Nie zmienia interfejsów Compose/Room23. Wymaga Windows, PG17 i istniejącego,
zgodnego z `backend/uv.lock` środowiska Python. Zależność źródłowa:
Native `ee7d2da2db6fc5bca1d9dacd5b1bbca4281030d7`, jeszcze niescalony.
Nie używa `native up` jako procedury odtworzenia.

## Powtarzalna próba B/C

Z katalogu głównego własnego checkoutu, istniejącym Pythonem backendu:

```powershell
$env:PYTHONPATH = "$PWD;$PWD/backend/src"
& $Python -m infra.local.integration.rehearse_restore `
  --state "$PWD/.tools/restore-NOWY-ID" `
  --pg-bin $Pg17Bin --keycloak-home $KeycloakHome --java-home $JavaHome
```

Każde uruchomienie wymaga nowego katalogu. Na Windows narzędzie musi mieć
dostęp do lokalnego TCP i tożsamości własnych procesów; izolacja sandboxa może
uniemożliwić te operacje. Nie obchodź tego zmianą firewalla lub cudzych usług.
Kopia instalacji Keycloak jest własna, import działa **offline**, z ograniczeniem
heap 512 MiB i kontrolą wolnej pamięci. Nie uruchamia się drugi serwer Keycloak,
issuer, API, gateway, worker, emulator ani Gradle. Nie ma wywołań Google.

Próba tworzy dwa osobne fizyczne klastry na loopback i nowych wolnych portach.
Źródło dostaje istniejące role/migracje, import i eksport DEMO E2 oraz prawdziwy
offline import realmu Keycloak z dwoma syntetycznymi kontami. Następnie zapisuje
baseline, zamyka dostęp ról aplikacyjnych i kopiuje sparowany zestaw. Późniejszy
posiłek i intencja usunięcia powstają przez rzeczywiste usługi backendu/SQL.
Ledger i niezależny witness są poza cofanym zestawem. Odtworzenie do nowego
celu sprawdza pierwotną epokę, schemat i fingerprints tożsamości, a potem trwale
zmienia epokę, kasuje sesje i zamyka AI/Nemesis oraz wykonuje istniejący cleanup.
Źródło i cel pozostają zachowane po zatrzymaniu.

Oracle serwerowy sprawdza odmowy starej epoki/checkpointu/bootstrapu bez zmiany
danych, utratę późniejszego potwierdzonego posiłku, świadome `recreate_missing`
i jedną idempotentną mapę także dla drugiego żądania. Weryfikuje odmowy
brakującego/zmienionego/nieciągłego prefixu i błędnego fence przed zastosowaniem
poprawnego kontraktu ledger. Poprawne uzgodnienie zamraża źródło i blokuje
odtworzone konto z intencją usunięcia; nie potwierdza usunięcia u providera.

To **backend-only**: bez realnej walidacji JWT/refresh/PKCE i Room27.
Nie jest pełnym KO-32, produkcyjnym backupem ani pomiarem RPO/RTO. Retencję
niepewnej puli mocka sprawdza odrębny odebrany eksperyment A; ta próba go nie
powtarza i nie deklaruje dodatkowej próby quota. Otwarcie issuer/API po restore
wymaga osobnej procedury, odebranego guardu Native i rzeczywistego fence ≥421 s;
ten adapter nigdy nie otwiera ruchu ani nie skraca tego czasu.

## Mały interfejs

```powershell
& $Python -m infra.local.integration.restore init --state "$PWD/.tools/source-NOWY" --pg-bin $Pg17Bin --port 55432
# Provisionowanie tylko własnego nowego klastra; nie wskazuj aktywnego Native.
& $Python -m infra.local.integration.restore capture --state "$PWD/.tools/source-NOWY" --archive "$PWD/.tools/archive-NOWY"
& $Python -m infra.local.integration.restore restore --archive "$PWD/.tools/archive-NOWY" --state "$PWD/.tools/target-NOWY" --pg-bin $Pg17Bin --port 55433 --checkpoint $TrustedCheckpoint --checkpoint-sha256 $TrustedCheckpointSha
& $Python -m infra.local.integration.restore stop --state "$PWD/.tools/target-NOWY"
```

`capture` wymaga zatrzymanych własnych klientów i zamyka HBA dla ról
aplikacyjnych; nie zabija sesji. Właściciel administracyjnych credentials
odpowiada za wyłączny dostęp w trakcie capture. Nie wolno traktować samej
deklaracji manifestu jako produkcyjnego dowodu zatrzymania wszystkich writerów.
Odmowy obejmują zastany cel, obcy marker, PID/birth/exe/datadir/port,
niepełną parę, hash, niebezpieczne nazwy tar/Windows, linki i nakładające się
ścieżki. Blokada operacji odmawia współbieżnego lifecycle w jednym stanie.

Cały stan, dumpy, SCRAM, hasła, realm, checkpointy i surowe dowody są
ACL-private pod ignorowanym `.tools`. **Nie publikuj tego katalogu.** Receipt
nie zawiera haseł, kluczy ani surowych checkpointów. Natywne binaria/PID są
oznaczone osobno; adapter nie wymyśla kontenerowego image digest. Zdjęcia są
wykluczone: archiwizowany jest wyłącznie jawny katalog `catalog/`.

Publiczny `restore` wymaga **zewnętrznego checkpointu i niezależnego SHA-256**.
Hashe zapisane w samym archiwum nie są dowodem jego autentyczności. Zaufany
kontroler zachowuje zwrócony podczas capture `trusted_manifest_sha256` poza
cofanym zestawem (CLI zwraca `captured_pin`; nie wyliczaj go ponownie przy restore).
Po fizycznym odcięciu własnych producentów kontroler wywołuje
`restore_trust.write_checkpoint(path, captured, ledger_state)`, a zwrócony SHA
przekazuje osobno do restore. Oba harnessy wykonują te kroki automatycznie.
Checkpoint zawiera prywatne klucze kontraktowego ledgeru: pozostaje ACL-private,
poza archiwum; nie publikuj go ani `ledger_state`. SHA można przekazać neutralnie.
Przed utworzeniem celu czysty verifier sprawdza zewnętrzny SHA, pełny
uwierzytelniony prefix, backup-point/cutoff/FencePin, powiązanie strumienia,
sekwencji i head z rzeczywistą kopią oraz niezależny pin manifestu. Brak lub
zmiana któregokolwiek wejścia odmawia przed `initdb`, SQL i `pg_restore`.
Checkpoint, świadki i manifest są odczytywane raz; hash i parser używają tych
samych bajtów. Przed utworzeniem PG cztery payloady trafiają do nowego własnego
katalogu ACL-private; sprawdzane są bajty faktycznie skopiowane. Sealed input
jest tylko do odczytu. SQL, dumpy i katalog są następnie używane wyłącznie z tej
kopii, bez ponownych odczytów nieufnych oryginałów. Podmiana podczas kopiowania
odmawia; późniejsza zmiana oryginału nie zmienia wykonywanych wejść.

## Weryfikacja granic

```powershell
& $Python -m pytest infra/integration/tests/test_native_restore.py -q
& $Python -m pytest infra/integration/tests/test_backup.py infra/integration/tests/test_recovery_o2.py -q
& $Python -m ruff check infra/local/integration/restore.py infra/local/integration/rehearse_restore.py infra/local/integration/restore_oracle.py infra/integration/tests/test_native_restore.py
git diff --check
```

`execution.json` oraz prywatne snapshoty witness zapisują wynik i zakres.
FAIL pozostaje zachowany; nowe wykonanie dostaje nowe ID. Zmiana wyłącznie
etykiet/metadanych po próbie nie uprawnia do przepisywania starego wyniku.

## Oddzielny eksperyment C z własnym HTTPS/OIDC i mockiem

`live_restore.py` jest harnesssem operatora, osobnym od adaptera offline.
Wymaga odebranego guardu Native `8638dbce`, nowego własnego stanu i zasobów:

```powershell
& $Python -m infra.local.integration.live_restore `
  --state "$PWD/.tools/live-C-NOWY-ID" --host $OwnPrivateIPv4 `
  --pg-bin $Pg17Bin --keycloak-home $KeycloakHome --java-home $JavaHome
```

Źródło powstaje przez Native wyłącznie przed kopią; target zawsze przez
uwierzytelniony transport restore, bez `native up`/provisionowania/migracji.
Przed PKCE mierzone są własny TLS i rzeczywisty odmówiony peer127.0.0.2.
Po T0 rzeczywisty minimalny worker używa istniejącego FakeProvider; oddzielny
fsync witness zachowuje hashe dokładnych bajtów IO i odpowiedzi. Fixture zapisuje
syntetyczną decyzję i ACK. Nigdy nie jest to ludzka zgoda lub wywołanie Google.

Reużywany checkpoint pochodzi z wcześniejszego PULL tego samego właściciela;
walidacja obejmuje podpis, generację/epokę, protokół i zakres zwykłego sync
(`calorie-app`, bez opt-in E9). Token nie jest przepisywany/podpisywany ponownie.
After-ACK PULL pozostaje oddzielny; limit czterech snapshotów nie jest zwiększany.

Po restore nowa epoka zamyka AI. Próby starych i nowych zadań/rezerwacji muszą
odmówić bez nowego IO, nawet gdy późniejsze użycie nie istnieje w starej bazie.
Zewnętrzny counter nie podlega rollbackowi. `e7_reconcile` ma odmówić przy
rzeczywistym wieku blokady; nie zmieniamy czasu ani `closed_at` dla jej skrócenia.
Maintenance pozostawia tylko dokładne metody/kanoniczne ścieżki operatora
(master token, logout-all, JWKS i odczyt własnych sesji). Peer gate działa przed
proxy także dla tych ścieżek. Issuance użytkowników i API pozostają503.
Rzeczywiste logout-all i puste sesje providera poprzedzają pełny fence≥421s.
Dopiero potem testowane są stare JWT/refresh, nowy Code+S256 oraz HTTP recovery
z jedną mapą i osobnym pełnym PULL. SQL systemowych bramek i stop-exit mają
osobne neutralne receipts. Kod wykonanej próby i surowe dane pozostają prywatne.

To nadal przypadek serwerowy/syntetyczny, bez Room27, realnego Gemini,
produkcyjnego RPO/RTO i zgody na wydanie. Wynik określa receipt konkretnego ID;
sam opis harnessu nie stanowi PASS. AVD/Gradle/aktywne Native pozostają poza nim.

Raport rozróżnia `old_bootstrap_key_refused`, `old_checkpoint_refused` oraz
`old_operation_epoch_refused`. Ostatni probe wysyła zachowaną operację bez zmian
(UUID, payload, stara epoka) ze świeżą autoryzacją i poprawnym bieżącym
checkpointem. Fingerprint musi odpowiadać zaakceptowanemu receipt źródła;
walidator produkcyjny sprawdza checkpoint dla PUSH. Pełny graf wszystkich tabel
`app`, także liczników/rezerwacji/sesji, jest mierzony po setup/auth/PULL i przed
oraz po tym jednym żądaniu. Exact body nowej próby i graf pozostają prywatne.
Historyczny łączny boolean z wersji `5eac426` nie izolował odmowy operacji;
oryginalny C02 zachowuje tę granicę, a oddzielny supplement02 dostarcza dowód.
Zmiana harnessu nie oznacza, że historyczna próba wykonała nową wersję kodu.
