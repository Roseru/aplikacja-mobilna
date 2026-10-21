# Master wykonawczy O2 — O2_LEDGER_20261017_V1

Wykonaj zlecenie O3-066: autoryzowany producent ciągłego rejestru usunięć,
transakcyjny outbox i egzekwowane begin → provider → confirm → purge.
Autoryzacja właściciela: implementacja, własny zarządzany worktree, commit/push/PR.
Koordynator:01a12156-2312-7c43-aedc-1858e782e5fb. Nie scalaj i nie wdrażaj.

Repo Roseru/aplikacja-mobilna; agent2/O2. Własna gałąź
codex/backend-ciagly-rejestr-usuniec z aktualnego main615fb6b3. Wspólny checkout
E4 i cudze pliki zachowaj. Nie uruchamiaj kolejnego wykonawcy ani automatyzacji.
PR123/dd39050b to zależność dokumentacyjna do odczytu, bez merge gałęzi O3.
Przeczytaj AGENTS, wymagania11.3/KO32, workflow, dziennik, kod deletion/model/service,
aktualny łańcuch migracji/ACL E4/E6/E7/E8/E9, provisioner i recovery_o2.

L0: krótki eksperyment PG17 + trwały testowy odbiorca, kontrakt v1 i schematy.
Wykaż intencja commit → niezależny trwały zapis/ACK → efekt; brak ACK blokuje.
Provider DELETE po utracie odpowiedzi/commitu pozostawia odtwarzalną niepewność.
Nie wywołuj Keycloak wewnątrz transakcji. Nie obiecuj exactly-once.

L1: nowa migracja po0024, zachowane stare migracje i pełny graf. Atomowy outbox
wszystkich etapów i wyników, egzekwowane bariery. Stabilna instalacja niezależna
od epoki, exact issuer i cel z trwałego joba, obie generacje, operation/event UUID,
sekwencja/hash. Append-only, minimalne role, stały search_path, minimalne EXECUTE.
Operator nie może fałszować ACK/watermark ani wołać wewnętrznych rodziców.
Sprawdź LOGIN/CONNECT/membership/tabele/kolumny. Ograniczone porcje/retry/timeout,
idempotencja, crash/restart i fencing starych lease. Prefiks musi przetrwać rollback,
odwrócone commity i konkurencję. Jawny cutover/anchor; stare jobs legacy/unknown,
bez fabrykowania pokrycia. Zachowaj30dni kontraktu mobilnego. Stare resume wywołuje
provider przed confirm: odetnij jego wejście DB, sprawdź service.begin_deleting i
surowe state/generation. O3 odcina stare procesy i credentials providera; posiadacz
starego sekretu pozostaje granicą zaufania. Dostosuj provisioner bez osłabiania ACL.
Downgrade nie usuwa ledgeru, ochrony ani dowodów.

L2: adapter oddzielony od domeny, ACK uwierzytelniony na skonfigurowanej kotwicy,
wiążący dokładny strumień/prefiks/hash/odbiorcę. Standardowe prymitywy kryptografii.
Test trwałego odbiorcy z restartem to test kontraktowy. O3 zapewnia magazyn poza
hostem/credentials/retencję/transport. Bez nowych usług/kont/Dropbox I/O/produkcji.
Walidator i wejście restore odmawiają braku/luki/zmiany treści/złego celu/issuer/
generacji/cofnięcia/starego lub sprzecznego ACK/anchor/braku wiarygodnego cutoff.
Nie ignoruj pending/failed/unknown. Reconcile zachowuje generacje i subject fence;
nie ufa samej nieobecności rekordu w kopii. O3 dostarcza fencing i ostatni zapis.
Bez tego WAITING_EXTERNAL; nie zaliczaj pełnego KO32 ani produkcyjnego strumienia.

L3: PG17 pusty upgrade, zapełniony0024, grafy E4/E6/E7/E8/E9, downgrade/re-upgrade;
rzeczywiste LOGIN i negatywne ACL/stare CLI; crash/retry każdego etapu i rollback
grafu purge; konkurencja/lease; sekwencje/rollback/luka/replay/obce kotwice;
backup przed usunięciem → późniejsze usunięcie → niezależny sink → restart/restore
własnej PG kopii i reconcile. Małe odwracalne mutacje kilku barier muszą oblać test.
Ruff/format/E0/OpenAPI/kontrakty/regresje/packaging według backend.yml; jeden pełny
zestaw przed odbiorem. Brak PG nie daje PASS/SQLite zastępstwa. Testy w CI bez
pozornych skip. Kontenery/porty/dane własne, cleanup tylko po dowodzie własności.

Raport RAPORT_REJESTR_USUNIEC_O2: stan/head/migracja/komendy/wyniki/macierz awarii/
kompatybilność/zakres odbioru/działania O3/O1/blokady. Bez danych realnych/sekretów.
Krótki lokalny checkpoint, jedyny wspólny dziennik KOMUNIKACJA_AGENTOW.
Jeden świeży subagent: krytyczny kontrakt i finalny diff bezpieczeństwa, co najmniej
9/10, brak P0/P1/P2, konkretne dowody. Poprawiaj zmieniony zakres. Braki zewnętrzne
WAITING_EXTERNAL z właścicielem/artefaktem/warunkiem wznowienia.

Commity agent2 z lokalną tożsamością; jeden spójny PR do main. Przed pushem fetch
komunikacji, zachowaj O1/O3/historię, zmień tylko wiersz O2 i dopisz następny wolny
O2-ID (041 jeśli wolny), potwierdź O3-066. PR attach_artifact. Odbierz rzeczywiste
osiem kontroli aktualnego head/base: contracts, quality, postgres, keycloak-pkce,
android-build, android-device, local-integration, ci-required. Bez samodzielnego
merge/wdrożenia/AI/Nemesis/zmian instalacji, kont/issuer/CA/epoki/kopii/zadań O3.
Final: PR, head, dowody, blokady do osobnego odbioru koordynatora.
