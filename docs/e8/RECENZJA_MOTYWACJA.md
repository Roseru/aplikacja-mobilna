# Recenzja motywacji E8.1 + E8.2 - osoba 2

12 października 2026. **Nowy niezależny odbiór: 9,3/10, zero otwartych P1/P2.** Własny realny SCRAM LOGIN i actual COMMIT potwierdzają zamknięcie P2 purge. Werdykt: backend E8.1+E8.2 gotowy do odbioru koordynatora po ośmiu kontrolach końcowego head/base. [PR35](https://github.com/Roseru/aplikacja-mobilna/pull/35) pozostaje niescalony; autor nie scala. O1 APK/Room i wdrożenie O3 są osobne.

Nieautor nie implementował runtime/testów/migracji autora. Wykonał nowy własny managed checkout, locked environment, PG17/SCRAM/process oraz nowe prywatne oracles. Nie edytował dokumentów autora, nie publikował commitów/PR/commentów. Autor przeniósł przekazany wynik do tego dokumentu. Poprzedni odbiór 9,3/44 probes/1041 PG na 44986a5–5c36c9e był historyczny; nie zamykał nowego [P2](https://github.com/Roseru/aplikacja-mobilna/pull/35#issuecomment-6115507635).

## Exact source i manifesty

- Tested source: `b2c6709e95796ab2c10a63493b78635664ea4f9e`, base `e93e38e02fed9663217b9036e5831cbc934e1baf`, branch `codex/backend-e8-motywacja-ranking`.
- Manifest po właściwym pełnym PG: 699 plików, SHA-256 `ac0f956c8ed0f236150d6db023ff4d3814bd8f39d22304bf6895f4a0f260fc6e`, clean checkout.
- Manifest 3 nowych probes: SHA-256 `41e94c38d3881c93820d8c52fef7e66b6c5cd7e33eb0f22714c7f3cde04f532d`.
- Prywatny `INDEPENDENT_PURGE_COMMIT_RESULT.json`: SHA-256 `1c0b1ea35272341e3e251e667b9f5d8b5a8f31a6fab103d57a3aa2b94e136873`. Basename i hash identyfikują dowód; prywatne ścieżki, harness, dumpy, credentials i logi nie trafiają do Git.
- 28 opublikowanych plików migracji 0001–0016 porównano byte-for-byte do 5c36c9e: identyczne. Nowa 0017 jest zamrożona; końcowe raporty zmieniają wyłącznie dokumentację, bez ponownej zmiany code/interface.

## Faktycznie wykonane nowe kontrole

**1370 unit PASS**, 74,63 s; **1059 pełne PG17 PASS**, 1139,16 s, zero failures/errors/skips. **18 nowych unikalnych własnych oracles PASS**; osobno 18 dostarczonych scenariuszy PASS/53,22 s, które są również w pełnym 1059. Nie sumujemy zakresów i powtórek ani nie dodajemy historycznych 44.

Mandatory Ruff/format 281/diff PASS. E0: 8 schematów/95 valid/35 invalid/18 scenariuszy/435 linków. Wheel/sdist: 139 dokładnych plików pakietu, 8 dokładnych zasobów E8, 37 locked runtime dependencies plus project (38), czyste installed `python -I` i head 0017 PASS. Niezależny wheel SHA-256 `a4378ea5925a2173c5d739e9f946169e086c035327cfe8d88c5721ec2cb28bef`; sdist `23a57f3e4ef30d8c245c1a154341f6aa44562c5bbed8533b830ab0e0a613490d`. Oddzielny build ma własny hash; zawartość sprawdzono względem exact source.

## Zamknięcie P2 i nowe adversarial oracles

Na fresh 0015 i 0016 minimalny realny LOGIN SCRAM wywoływał canonical purge, który wracał, lecz actual COMMIT dawał 42501 diary_aggregate_count i cofał wszystkie app rows. Upgrade 0017 zachował raw checker metadata poza prosecdef; actual COMMIT i fresh 0017 przeszły. Nie dodano SELECT źródeł albo EXECUTE checkera operatorowi. Powtórny resume/status/CLI był idempotentny, fence i partner/cursor privacy zachowane.

Nowe własne przypadki sprawdzają żywy confirmed job i pełny graf przed downgrade 16, oraz legalny legacy/E7 graf przed downgrade 15: naprawa i realny CLI retry pozostają. Pełne E8 evidence nadal blokuje głębszy downgrade 15 atomowo, bez discard. Mixed unrelated TEMP constraints zachowują caller modes i moment odmowy; explicit diary IMMEDIATE odmawia 23514 i cofa graf, a świeży default retry przechodzi. 0 i diagnostyczne 102 elements odmawiają przy actual COMMIT; 100 przechodzi. Zewnętrzny position CHECK nadal odmawia standardowej 101/102 przed COMMIT; transactional diagnostic izoluje checker i odtwarza CHECK po rollback.

Extra proconfig, brak item trigger, nie-INITIALLY-DEFERRED trigger, EXECUTE dla nieznanej roli oraz invoker przed downgrade odmawiają 23514 atomowo. Hardened LOGIN ma INHERIT i tylko base membership bez ADMIN, nie ma raw source access. Poprawki własnego harnessu (ancestor config, keyword-only call, błędne oczekiwanie NOINHERIT LOGIN, packaging cwd/yaml environment) nie są PASS i nie zmieniały źródeł autora.

Wszystkie własne usługi zatrzymane: PG15683 i izolowane postmastery nie pozostają, CLI children odebrane, zero pozostałych case DB/loginów. Autor również zatrzymał swoje środowisko. Nieautor nie korzystał z produkcji/usług autora, Google/billing lub automatyzacji. [Raport](RAPORT_MOTYWACJA.md) rozdziela dowody autora, ograniczenia danych i CI. Dwa osobne [odbiory granicy koordynatora](https://github.com/Roseru/aplikacja-mobilna/pull/35#issuecomment-6115913896) 9,3/9,4 zwalniają zależny etap E8.3, bez zastępowania niniejszego pełnego odbioru.

## Identyfikatory 18 nowych własnych przypadków

```text
test_independent_purge.py::test_own_real_minimal_login_parent_red_and_repair_green_at_actual_commit[0015_e7_ai]
test_independent_purge.py::test_own_real_minimal_login_parent_red_and_repair_green_at_actual_commit[0016_e8_motivation]
test_independent_purge.py::test_own_real_minimal_login_parent_red_and_repair_green_at_actual_commit[0017_e8_purge_commit]
test_independent_purge.py::test_own_filled_downgrade_keeps_security_and_resumable_live_job_before_purge[0016_e8_motivation]
test_independent_purge.py::test_own_filled_downgrade_keeps_security_and_resumable_live_job_before_purge[0015_e7_ai]
test_independent_purge.py::test_own_constraint_modes_return_stage_and_whole_rollback[queued_invalid_deferred]
test_independent_purge.py::test_own_constraint_modes_return_stage_and_whole_rollback[immediate_probe]
test_independent_purge.py::test_own_constraint_modes_return_stage_and_whole_rollback[explicit_diary_immediate]
test_independent_purge.py::test_own_cardinality_commit_oracle_and_no_acl_expansion[0]
test_independent_purge.py::test_own_cardinality_commit_oracle_and_no_acl_expansion[100]
test_independent_purge.py::test_own_cardinality_commit_oracle_and_no_acl_expansion[102]
test_independent_purge.py::test_own_new_adversarial_metadata_fail_closed_preserves_job_and_rows[extra_config]
test_independent_purge.py::test_own_new_adversarial_metadata_fail_closed_preserves_job_and_rows[missing_items_trigger]
test_independent_purge.py::test_own_new_adversarial_metadata_fail_closed_preserves_job_and_rows[not_initially_deferred]
test_independent_purge.py::test_own_new_adversarial_metadata_fail_closed_preserves_job_and_rows[unknown_role_execute]
test_independent_purge.py::test_own_new_adversarial_metadata_fail_closed_preserves_job_and_rows[downgrade_invoker]
test_independent_purge.py::test_own_full_e8_evidence_blocks_deeper_downgrade_without_discard
test_independent_purge.py::test_own_actual_cli_begin_status_resume_repeat_with_scram
```
