# Aktualny odbiór po poprawce — frozen605

**Aktualny source: `605f6df7c596f4731c9c119a12e7e3d2476ebc76`, base `a6a77fc45fb72a0de2a41a71de4f7f1e33900309`. Ocena 9,3/10, zero nierozwiązanych zidentyfikowanych P1/P2 sprawdzonego zakresu.** Recenzent nadal jest nieautorem. Historyczny odbiór4c poniżej zachowuje własne19oracles; właściwy zmieniony zakres605 otrzymał **4 nowe własne node IDs PASS**, bez zbędnego powtarzania19. Nie sumuję ich jako pełnej regresji lub wszystkich prób na605.

Jedyny runtime diff względem4c to8linii ORM `Index("ix_nemesis_finalization_due",deadline_at,id,postgresql_where=status IN(active,finished) AND result_status=provisional)`. Fizyczny indeks już powstał w0021; brak reprezentacji ORM powodował wykryty przezroot rzeczywisty RED `remove_index`. Poprawka nie zmienia DDL, danych, SQLresources, sourcehooks, locks, routerów lub packaging. Gitdiff exactheads potwierdził wyłącznie models.py na powierzchni runtime. Każdy wcześniejszy oracle dotyczący niezmienionych tychmechanizmów pozostaje przypisanydo4c.

Przejrzano pełny diff sześciu plików testowych: foundation/e5 dodają dokładnie4nowe tabele; e6head używa actualEXPECTED_REVISION21; e6unicode zachowuje stare byte/hash/history/readiness assertions; parentregression używa własnej bazy/randomminimalLOGIN przez rzeczywisty hardenedCLI i rzeczywistego counter/change source context, zachowując dotychczasowe assertions; privacy zachowuje zakaz surowych pól/bindingów i porównuje kompletne scalarvalues zamiast cyfr znalezionych w publicUUID. Nie dodano skip/retry lub obniżonych oczekiwań produktu.

Własny zmieniony zakres na ponownie uruchomionym własnym PostgreSQL17.11/SCRAM55524:

- **InstalledPython−I actualmigrations** z wheel605 poza checkout: freshupgrade→alembiccheck→downgrade20→reupgrade21→alembiccheck PASS, dwie rzeczywiste kontrole zero drift. Script_location wskazywało installed package resources. Sprawdzono właściwe index columns `[deadline_at,id]`, fizyczny partialpredicate active/finished+provisional,4nowe tabele po upgrade i ich brak po downgrade, runtime_ready true/gateclosed. Dowód `corrected-installed-migration.log`.
- **Actualappend_source_context** dostarczonyproducer wywołany we własnym scenariuszu z productiondomainwriter. Własne assertions potwierdziły faktyczny counterposition+1/changeentity/revision, jedną właściwą qualification i projekcję masy; rollback cofnął source/change/projection, commit zachował NUMERIC83/UUID/revision1.
- **Deterministyczna publicUUIDcollision** `25020000-5000-4000-8000-000000000001`: realHTTPpartnerstatistics ma tecyfry w publicznym id i pozostaje poprawne. Prywatne całe wartości2502/5000/2001.6/bindingUUID nie wystąpiły jako scalar; aggregate20 zachowany. Własna kontrola wykryła syntetyczną injekcję pełnej prywatnej wartości.
- **Randomoperatorproducer** przez rzeczywisty hardenedprovision/minimalSCRAM bound do własnejDB, actualbegin/resume/purgeCOMMIT, powtórzenie bez provider re-call, brakrawMealprivileges i zachowanie kontapartnera PASS.

Pierwszy corrected-boundary miał3PASS/1RED w16,28s. RED dotyczył wyłącznie własnej błędnej asercji tekstu storageNUMERIC: `str(83.000000)=="83"`. Kanoniczna postać jest kontraktem wire, a nie zapisu PostgreSQL. Wymieniono ją na strictDecimal83 (bez zmiany runtime lub oczekiwania masy); tylko ten node otrzymał ponowne wykonanie1PASS/5,58s. REDXML/log zachowane. Import producer module powodował PytestUnknownMarkWarning, ponieważ prywatnytest działał poza konfiguracjąbackend; wszystkie cztery przypadki faktycznie wykonano, bezskip. Ostrzeżenie nie zastępuje testu ani nie obniża asercji.

Osobny własny process−I correctedwheel dodatkowo PASS: sitepackages import, brak checkoutfallback,12SQLresources exactinstalledvswheel i pełna treść frozen605, strictsigned/hidden, productionroute, braktestów wwheel. SHA256currentwheel `2a80526949afea1be0d1ba41abf45fe770499bebf46b1d81acea505152e95abe`.

Dokładne argv/środowisko/nodeIDs/hashmanifest rozszerzono w prywatnym `independent-manifest.json`; nie publikujecredentiali. Nowe dowody:

| Artefakt | SHA256 |
|---|---|
| corrected-boundary.xml | `ac3103b6708e480e673342c4d6494e673f81362f306ce96f75d2e8d08d766fa8` |
| corrected-source-helper.xml | `46d0b8d9be28b410467117c5b252d4f3fbcbe441f7e870615b2c5cbefed0661e` |
| corrected-installed-migration.log | `4f1f31234d4745524a7ea3a5ad1ed09c8df53cf39f33d51373a8f4154f3475b8` |
| package-corrected.log | `d1b8a0977b4bf8d9603773c2e25ad737beb1a58a1111478f59484f2591f60dda` |
| test_corrected_boundary.py | `991f016994748d8d87119070a6d8a159e1d62ec47f5c6c06cbdadb81c2210d22` |

Aktualne własne node IDs:

- `test_corrected_installed_isolated_migration_roundtrip_check_and_index`
- `test_current_random_operator_producer_bound_db_minimal_scram_real_purge`
- `test_current_source_append_helper_actual_change_oracle_and_rollback`
- `test_public_uuid_collision_and_exact_private_scalar_oracle`

Root zachował niezależny pełny RED1241PASS/18failure/2error; reported targeted17 i parent6PASS nie są próbami recenzenta ani deklaracją pełnej regresji605. Ostateczne pełnePG/Docker/osieemCI aktualnegohead/base/main/O1/O3 nadal wymagają odrębnych rzeczywistych dowodów. Własny indexdrift jest zamknięty potwierdzonym installed−I fresh/roundtrip check; pozostałych bramek nie zaliczam za innych. Po odbiorze własnyPG55524 ponownie STOP,55534 nigdy nieuruchomiony. Checkoutdetached605 czysty, bez implementationedits/publikacji/merge.

---

# Niezależna recenzja E8.4 — wyniki Nemesis

12 października 2026 r. Recenzent: niezależny nieautor, Agent 2. Nie tworzyłem ani nie zmieniałem implementacji, migracji, kontraktów lub testów autora. Własne oracles, bazy i dowody powstały wyłącznie poza Git.

**Ocena sprawdzonego zakresu: 9,3/10; zero zidentyfikowanych P1/P2.** To odbiór nowego zakresu źródeł E8.4 na zamrożonym kodzie. Nie jest deklaracją zaliczenia pełnej regresji, CI, Docker, integracji O1/O3 ani całego E8. Merge wymaga osobnego zamknięcia tych właściwych bramek.

## Tożsamość źródła i niezależność

- Zamrożony source/head: `4c2816f7ad84a3d034d0819f79846c83ce855bde`; runtime: `5a692f862ef44b1565470e61e1cb35c6503da380` (dołączony merge zmienił Android/docs).
- Original start: `76546405d2c549278a9826c0223204e98698015c`; master blob: `3bb0ac4e366aa8983585a25d77da416aea43cfde`; current base: `a6a77fc45fb72a0de2a41a71de4f7f1e33900309`. Gałąź produktu: `codex/backend-e8-nemesis-wyniki`. Recenzent pracował w osobnym managed checkout frozen head, bez własnego PR/publikacji.
- Odczytano cały master E8.4, wymagania WF10–12/11.3/11.7/KO22/26/27/29, AGENTS, workflow, plan/architekturę, aktualną komunikację, mastery koordynacji/E8.1–2/E8.3 oraz końcowe decyzje i przekazania O1/O3.
- Własny świeży PostgreSQL **17.11**, loopback **55524**, własny pgdata/storage i losowe prywatne SCRAM credentials; fresh migracja0021. Niesuperuser API/migrator i minimalny rzeczywisty finalizer LOGIN. Nie dotykano PG55521/22/23, cudzych usług lub checkoutów. HTTP wykonywał rzeczywistą production app factory przez TestClient i podpisane syntetyczne JWT/JWKS; listener55534 nie był uruchamiany.
- Reużyto wyłącznie dostarczonych producer helpers do przygotowania danych/połączeń oraz odczytanego środowiska zależności Python3.13.9. Oczekiwania, scenariusze, rawSQL, polecenia i nowe asercje napisał i wykonał recenzent. Nie uruchamiano testów autora jako własnych oracles.

## Własne wykonane dowody

**19 unikalnych własnych node IDs PASS**, bez failure/skip w końcowym sprawdzonym zakresie. Powtórzenia/rozszerzenie restore i naprawionego oracle nie zwiększają tej liczby.

| Dowód | Rzeczywisty zakres | Wynik |
|---|---|---|
| independent.xml | Pierwsze12: neutralprivacy/hidden/cancel-final;3corruptseed variants; raw currenttransaction positive rollback-probe+5forgeries;2earlyq latecommit/rollback ze stats/finalizer; physicalsource+account blocks; fullchallenge discovery; minimalCLI/rawACL; scopedpurge; actualarchive/restore | 12PASS/59,34s |
| supplement.xml | Signed metrics i populated migration; pierwotny błędny DSToracle | 2PASS/3RED, zachowane |
| calendar-corrected.xml | Raw API accept7/30/90, obie strony i wszystkieNdat, DST25h, pending bez self/opponent/outcome, profileWarsaw→NewYork poend_at bez przesunięcia acceptedinstants | 3PASS/13,91s |
| provision.xml | Produkcyjny hardened finalizer provision, SCRAMverifier, inherittrue/adminfalse/setfalse, rzeczywiste SETROLE odmówione42501, CLI COMMIT | 1PASS/6,76s |
| restore-snapshot.xml | Rozszerzony faktyczny pg_dump/pg_restore/newEpoch z nowym HTTP journal/ranking; własny pg_blocking_pids dowód readwait na kwalifikowanej korekcie i spójnychcounts/outcome | 2PASS/13,00s, restore już liczony w12 |

Szczegóły własnych oczekiwań:

- Raw orchestrator poprawnie przyjął rzeczywisty bieżący source/counter/change xmin w savepoincie, a caller-qualified_at, niepełne IDs, złą pozycję, revision i epoch odrzucił23514. Wycofanie pozytywnej próby pozostawiło wyłącznie późniejszy właściwy zapis.
- Usunięty seed, brak daty jednej strony i przesunięta granica dały participant503/nonparticipant404. Source nie dostał ACK/receipt i nie pozostał Meal; finalizer odmówił zamiast utrwalać fikcyjne zero.
- Jedno q=deadline−1µs zachowano przy commit po deadline; rollback nie naliczył zmiany. Final result i późniejszy odczyt odpowiadały właściwej wersji punktów/kompletności. Dodatkowy rzeczywisty readwait został potwierdzony pg_blocking_pids, nie samym thread timing.
- Finalizer przez minimalny LOGIN zakończył się przy utrzymanych ACCESS EXCLUSIVE na Meal/DiaryDay/Weight/Goal/Profile/MotivationDay/MotivationAccount i FORUPDATE wszystkich account rows. Statementtimeout3s nie zadziałał; wynik1pkt zachowany. FinalResult nie ma accountFK.
- Własny wektor dwóch różnych historycznychE daje20% i−50%, mean−15/eligible2, bez bonusu celu9999. Trzy pomiary na dwóchdatach dały representative80→88,10%,observed2. Hidden to dokładnie state, bez counts. Wire nie ujawnił surowych pól/bindingów. Strict signed codec odrzucił float/NaN/Infinity/exponent/trailingzero/negativezero; przyjął ogromną część całkowitą i12miejsc.
- Begin deletion po final natychmiast odciął partner read. Crash po confirmationCOMMIT zachował dane przedpurge; resume/purge/retry bez powtórnej identityconfirmation usunęły projections/results/seeds/peerreceipt snapshots, zachowując posiłek partnera i deletedsubjectfence. Hardened deletion CLI status użył tego samego minimalnego SCRAMLOGIN. Provider był syntetyczny; nie twierdzę rzeczywistego Keycloak admin deletion.
- Rzeczywisty archive/restore przedcleanup odciął stare statistics/finalizer natychmiast po zmianie installationepoch. Boundedcleanup anulował starychallenge. Nowy journal pushHTTP został accepted, a motivationepoch odpowiadała nowejepoce.
- Fresh oraz populated upgrade0020→0021 zachowały istniejącekonto, capabilitydefaultclosed i rzeczywisty runtime manifest. Nienaruszona historia migracji0001–0020; niepusty downgrade odmówił23514 i headpozostał0021.

## Audyt kodu i pakiet

Przejrzano rzeczywistą ścieżkę source_mutated→NemesisSourceProjection→SQLorchestrator i constraints/ACL. Jeden extension posiada pełny uporządkowany allchallenge lockset; account/counter poprzedzają challenge. Apply sprawdza sesję, transakcję/savepoint, exactplan/provenance/q i nie wykonuje ponownego SQLrefresh. SQL ponownie sprawdza rewizję/pozycję/inprogressxmin, a e8_refresh zwraca jeden DBq. Replay/savepoint pozostają we wspólnym sync; brak ticket registry lub drugiej ścieżki dziennika.

Seed przechowuje pełny kalendarz obu ról, immutable acceptedzone boundaries, trwałe NUMERIC/sourceprovenance. Finalizer czyta projections/terms/privacyfences, bez source joins albo e8_refresh/accountcounterlocks. Oba role results oraz status final są atomowe; final→provisional zabronione, cancel/purge nadal legalne. Statistics blokuje obaaccounts wUUIDorder przedchallenge i odbiera własną readrevision, zgodę/status/generation/epoch. Scope nie dostarcza bocznych counts. Nowe SecurityDefiner mają zamknięty path/nonsuper owner, rawtables/internalexecute zamknięte, finalizer graph niezależny i noSETROLE w rzeczywistym provisionerze. Capability wykorzystuje hashmanifest funkcji i trusted activation; API ani worker jej nieotwierają. Przejrzano scopeddeletionparentchain/0017repair i restorefences.

**Osobny własny proces Python−I na świeżo zainstalowanym frozen wheel PASS.** Import pochodzi z site-packages, sys.path nie zawiera checkoutu, wszystkie12 SQLresources installed==wheel byteexact, cały modules/nemesis i schematy obecne, tests nie spakowane, signed/hidden strictness i production route działają. SHA256wheel: `f8c4597723d7b097387d9d79244c3c24b45626755514b43c1d18da466d7e3e82`.

Dwa wyjaśnione RED własnego harnessu zachowano: DST odejmował dwa datetime z tym samym ZoneInfo (Python walltime24h); normalizacja obu doUTC potwierdziła niezmienione oczekiwanie25h. Pierwotny bytecomparison checkoutvswheel wykrył wyłącznie CRLF/LF w finalizer.sql/statistics.sql; installedvswheel pozostaje byteexact, pełna treść frozencheckout porównana po zwykłej normalizacjiGitlineendings. Nie zmieniono runtime, oczekiwań domeny lub timeoutów i nie dodano skip/retry dla green.

Dockerfile faktycznie uv sync --locked --no-dev --no-editable usuwa /app/src; actualCI uruchamia builtimage Python−I. Tę konfigurację odczytano, lecz lokalny Docker jest niedostępny i rzeczywistego DockerPASS nie przypisuję sobie.

## Polecenia, node IDs, hashe i granice

Własne polecenia: `python -m pytest test_independent_e8_4.py -q --junitxml=<wskazany XML> --basetemp=<własny katalog>`; selekcje kolejno pełny pierwszyzestaw, `-k "raw_accept_atomic or independent_signed or populated_upgrade"`, `-k raw_accept_atomic`, `-k hardened_finalizer`, `-k "actual_archive_restore or observed_pg_lock"`. Osobno `installed-python -I package_independent.py`. Dokładne argv, odczytane środowisko bez credentiali, node IDs i wszystkiehashes znajdują się w prywatnym `independent-manifest.json`; root posiada ścieżkę tego dowodu. Prywatne DSN/hasła/logi nie nadają się do publikacji.

| Artefakt | SHA256 |
|---|---|
| independent.xml | `894bede2f6e628f919ed2011710327d030a02a92cd87526a40f01693926adde4` |
| supplement.xml | `1cd37eee204944fa5b56adf6d162e3710c6cfca6e51783dbd87140b50916ea2a` |
| calendar-corrected.xml | `d9e286b9c4c9078742aae8b4edf08aeac0e52284ba7300ad22700770885d849d` |
| provision.xml | `0a0fe557fdae710fee3851c901c37e5f227136caa7b2d55ab8011ea9d5b101e1` |
| restore-snapshot.xml | `d07c26fa54449ede7a0b85e1a21aa6341465a98feea2f393143a30a40b953260` |
| package-independent.log | `9775d2b89bd5d835fb469c5e9a2f3201909abac6fb7ed97523356653d1128dc1` |
| test_independent_e8_4.py | `c391dfa2850c94e7295050b6ff4a97c1e0cd925d9dc019fc84d4a4044e17a1fa` |

Własne finalne node IDs:

- `test_actual_archive_restore_immediate_epoch_fences_then_cleanup`
- `test_actual_scoped_purge_confirmation_commit_retry_and_peer_cleanup`
- `test_all_challenges_full_discovery_not_source_date_filtered`
- `test_corrupt_seed_never_masquerades_as_zero_or_source_ack[missing_date]`
- `test_corrupt_seed_never_masquerades_as_zero_or_source_ack[seed_removed]`
- `test_corrupt_seed_never_masquerades_as_zero_or_source_ack[shifted_boundary]`
- `test_early_qualification_late_commit_or_rollback_and_snapshot[False]`
- `test_early_qualification_late_commit_or_rollback_and_snapshot[True]`
- `test_finalizer_physical_source_tables_and_account_rows_do_not_block`
- `test_hardened_finalizer_provision_no_set_role_scram_cli`
- `test_independent_signed_deficit_weight_representative_oracle`
- `test_minimal_finalizer_login_graph_raw_acl_and_real_cli`
- `test_neutral_privacy_hidden_counts_and_final_cancel`
- `test_observed_pg_lock_wait_proves_reader_serializes_qualified_update`
- `test_populated_upgrade_default_closed_and_nonempty_downgrade_guard`
- `test_raw_accept_atomic_complete_calendar_and_preserved_instants[30]`
- `test_raw_accept_atomic_complete_calendar_and_preserved_instants[7]`
- `test_raw_accept_atomic_complete_calendar_and_preserved_instants[90]`
- `test_raw_current_transaction_and_adversarial_source_plan`

Nie sumuję historycznych60PG/41legacy/1675unit autora ani pełnej regresji root. W czasie odbioru root nadal diagnozuje niezaliczone przypadki pełnegoPG; bez końcowego wyjaśnienia i poprawnego wykonania tej bramki raport nie stanowi zgody na publikację/merge. Rzeczywisty Docker i osiem CI aktualnegohead/base oraz pushmain/integracja wymagają odrębnych dowodów. RealKeycloak/TLS, APK/UI/cache O1 i rollout/minutowyworker/RPO/RTO O3 pozostają osobnymi odbiorami. Zmieniony runtime wymaga nowego właściwego odbioru; testonly/metadane bez wpływu naruntime podlegają węższemu sprawdzeniu.

Po próbach własny PostgreSQL55524 zatrzymany fast/wait, listener55534 nigdy nie uruchomiony. Frozencheckout bez zmian implementacyjnych; nic niepublikowano ani niescalono.
