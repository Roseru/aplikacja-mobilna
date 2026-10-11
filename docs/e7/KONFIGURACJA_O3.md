# Konfiguracja, storage i odbiór operacyjny E7 - osoba 2

Backend E7-O2 jest przeznaczony do osobnego odbioru. Readiness dziennika,
photo capabilities, lokalny mock, E7-R i produkcyjne wydanie są oddzielnymi bramkami.
Nie uruchomiono Google, produkcji, billing ani harmonogramu Codex.

## Migracja i role

Head `0015_e7_ai`, po niezmiennych `0001–0014`. Nowe funkcje mają stały
`search_path`, cofnięty PUBLIC EXECUTE i ograniczone granty. API nie ma DML do
nowych tabel; stary `calorie_app_worker` zachowuje wcześniejsze prawa, bez dispatch E7.
Osobny `calorie_app_ai_worker` jest NOLOGIN/NOINHERIT, bez rodziców, SUPERUSER,
CREATEDB, CREATEROLE, REPLICATION i BYPASSRLS. Utwórz tę bazową rolę jako administrator
przed migracją istniejącej bazy; bootstrap pustego Compose tworzy ją automatycznie.
Upgrade odmawia wcześniejszych efektywnych DML/CREATE oraz zbędnych prywatnych SELECT
tej roli, zanim wykona DDL. Nie odbiera praw innym rolom.

Migrację wykonuje dotychczasowy migrator. LOGIN AI dziedziczy wyłącznie minimalną
bazową rolę; nie może SET ROLE do migratora/API/starego workera/operatora usuwania.
Zestaw grantów obejmuje E7, wersję Alembic i installation_state, bez dziennika,
ProductDraft lub mutacji katalogu. SELECT jobów obejmuje tylko kolumny kandydatów,
bez fence. Ledger przechowuje SHA-256 jednorazowego tokenu transportu, nie token.
Provisioning LOGIN opisuje [narzędzie lokalne](../../infra/local/provision_ai_worker.py).
Na współdzielonym klastrze O3 musi utrzymać globalne ACL baz: PUBLIC CONNECT do
technicznych baz PostgreSQL jest decyzją klastra; prywatna baza Keycloak nie może
być dostępna workerowi. Nie zmieniaj cudzych haseł ani globalnej tożsamości Git.

Downgrade pustego E7 jest wspierany. Jakikolwiek durable consent, analysis, job,
decision, receipt, admission, reservation lub cleanup intent powoduje atomową odmowę.
Zachowaj dane i przygotuj osobny plan zamiast usuwać dowody, aby wymusić downgrade.

## Prywatny mount i worker

`AI_PROVIDER=mock` jest domyślny. `AI_PHOTO_ROOT` musi wskazywać preprovisioned,
absolutny, prywatny katalog na jednym trwałym filesystem, współdzielony API/AI worker.
To osobny writable mount, poza katalogiem official, static serverem, backupem i Temp.
Brak root lub poprawnych praw zamyka photo capabilities; nie odbiera dziennikowi readiness.
API oraz worker wymagają uprawnień create/read/unlink/fsync na tym mount.

POSIX: root 0700, pliki 0600, ten sam dedykowany UID lub uzgodniony bezpieczny model
wdrożenia. Windows: chroniony DACL root; tylko konto procesu, SYSTEM i Administrators,
bez inherited/untrusted ACE. Runtime weryfikuje ACL, reparse/symlink/hardlink i ścieżki,
nie naprawia ACL ani nie tworzy root sam. Provisioning wykonuje O3 dla własnego mount.
Nie kieruj mount do katalogu mającego zawierać publiczne artefakty.

`DATABASE_URL` API używa API LOGIN; worker używa AI LOGIN. Ustaw ten sam
`AI_PROJECT_ID`, `AI_ENVIRONMENT_ID`, `AI_MODEL`, provider i private root. Mock:
projekt/środowisko `local`, model `mock-food-v1`, `AI_MOCK_SCENARIO=valid`.
Po bootstrapie pobierz aktualny `sync_epoch` i skonfiguruj pulę migratorem:

```text
python -m calorie_app.modules.ai.cli configure-pool --epoch CURRENT_UUID
python -m calorie_app.worker --once
python -m calorie_app.worker
python -m calorie_app.worker --sweep-only
```

Worker wykonuje startup sweep i osobny cleanup thread co 60 s, także podczas IO.
`--sweep-only` działa przy starcie i co 60 s; `--batch` 1–1000, domyślnie 100.
Godzinna retencja O3 z PR #21 nie zastępuje minutowego photo cleanup. O3 musi zapewnić
restart/nadzór i monitorowanie backlogu oraz osobny minutowy nadzór, gdy worker stoi.
Przy awarii całego hosta nie deklarujemy fizycznego unlink w 24 h. API/worker po TTL
nigdy nie odczytuje ani nie wysyła zdjęcia. Succeeded proposal może pozostawać
potwierdzalna po usunięciu obrazu.

Sanitized JPEG jest fsync/atomic-rename przed acceptance. Durable compensation intent
powstaje przed staging; acceptance usuwa go atomowo z jobem/consent/receipt.
Session advisory locks per operation i storage key nie utrzymują transakcji przez IO.
Cleaner rechecks aktualną kwalifikację po storage lock; unlink poprzedza ACK.
Lost COMMIT ACK nie usuwa zaakceptowanego pliku. Missing file jest skutecznym retry cleanup.
Grace orphanów 300 s; aktywna blokada chroni plik nawet po grace. Purge zostawia wyłącznie
losowy key intent i anonimowe limity, usuwa prywatne propozycje/zgody/decyzje/bindings.

Pełne odpowiedzi receipts: minimum 1440 h; potem bounded sweep usuwa response_payload,
zachowując minimalny hash/status/ID do purge. Anonymous zakończony ledger: minimum 336 h;
żywe/osierocone permits nie są prunowane. Retencja DB działa także bez dostępnego mount.

## Gemini dev: wymagane datowane wejścia

Live wymaga `ENVIRONMENT=development`, `AI_PROVIDER=gemini`, modelu
`gemini-3.5-flash-lite`, niepustego `GEMINI_API_KEY` w secret managerze i
`AI_LIVE_CONFIRMATION` poza Git. Model i rzeczywiste project RPM/TPM/RPD musi
potwierdzić O3. Nie kopiuj limitów mock jako Free Tier. Manifest UTF-8 do 16 KiB,
bez duplikatów, ma dokładnie pola:

```json
{
  "provider": "gemini", "project_id": "O3_PROJECT", "environment_id": "O3_DEV",
  "model": "gemini-3.5-flash-lite", "confirmed_at": "DATED_UTC_TIMESTAMP",
  "free_only": true, "billing_disabled": true, "development_only": true,
  "model_verified": true, "rpm": 1, "tpm": 10240, "rpd": 1,
  "quota_windows": {}
}
```

Powyższe liczby to format demonstracyjny, nie potwierdzone limity projektu.
`quota_windows` zawiera wyłącznie jednoznaczne quotaId → minute/daily z potwierdzenia
O3. Pusta mapa nie dopuszcza retry 429: unknown/daily jest terminalne. Configure-pool
zapisuje datowane limity bez resetu ledger; capabilities/worker odmawiają, gdy limity
z manifestu i bazy różnią się. Po zmianie konfiguracji zatrzymaj ruch i ponów configure.
Wyłączenie starej pool nie otwiera nowej przestrzeni środowiska tego samego projektu.
Relokacja projektu/środowiska wymaga odrębnego odbioru, nie zwykłej rotacji klucza.

Standard REST v1beta, inline prepared JPEG, jeden generation request; countTokens
używa identycznego requestu. Każdy call rezerwuje 1 request i 10240 tokens; input≤8192,
output+thinking≤2048. RPM/TPM rolling 60 s, RPD America/Los_Angeles/DST, photos 10/UTCday,
receipts 1000/UTCday; interface energy 336 h nie implementuje E9. Pool jest wspólna
dla obu purpose, niezależna od secret key. Nie ma Files API, batch, grounding, URL fetch,
SDK ani automatycznego fallbacku na inny model. [Źródła](REFERENCJE_GEMINI.md).

Transport subprocess ma jeden hard deadline, maks. 45 s; child watchdog używa tego
samego absolute deadline i kończy osierocone IO. Processing≤120 s, queue≤5 min,
generate≤2. Permit fizycznego IO nie wygasa z lease/cancel/purge. Crash po markerze:
unknown, bez resend. Utrzymuj exact PID/process evidence przed ręcznym zwolnieniem.

## Osierocone IO i restore

Odczytaj własny attempt ID z chronionej bazy; ustal, że jego subprocess/socket już
fizycznie zakończył się. Operator przechowuje poza Git datowany JSON z
`previous_io_fenced=true`, `observed_at` UTC i szczegółami własnej weryfikacji.
Samo oświadczenie ani wygasły lease nie są dowodem. CLI zapisuje SHA-256 dokumentu.

```text
python -m calorie_app.modules.ai.cli fence-permit --epoch CURRENT_UUID --attempt EXACT_UUID --evidence PRIVATE_JSON
```

Po restore stary backup może nie zawierać nowszych wywołań Google. Zatrzymaj ruch,
odetnij poprzednie workery i zmień installation sync_epoch dotychczasową procedurą
restore. Trigger zamyka AI gate. Bez zmiany epoki procedura restore jest niepoprawna.
Stare joby nie są ponawiane. Konserwatywny v1 nie otwiera gate przez co najmniej
336 rzeczywistych godzin od zamknięcia — aż wszystkie niepewne okna wygasną.
Nie cofnij zegara ani closed_at w środowisku rzeczywistym. Dopiero potem:

```text
python -m calorie_app.modules.ai.cli resume-after-restore --epoch CURRENT_UUID --evidence PRIVATE_JSON
```

Dokładna nowa epoka i fizyczny fencing są obowiązkowe. Ledger/admissions/receipts
nie są resetowane. Dowód operacyjny production restore oraz nadzór usług pozostają
zadaniem O3; lokalne testy dump/restore nie zastępują tego odbioru.

E7-R pozostaje WAITING_EXTERNAL do otrzymania kompletnego manifestu O3, zatwierdzonego
niewrażliwego corpus i ręcznego fallbacku O1. [Manifest odbioru](E7_R_MANIFEST.md)
i [runner](../../tools/ai_reference/README.md) określają wejścia; mock nie zalicza R.
