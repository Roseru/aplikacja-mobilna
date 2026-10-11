# Recenzja motywacji E8.1 + E8.2 - osoba 2

12 października 2026. **Niezależny nieautor: 9,3/10, zero otwartych P1/P2.** Werdykt: backend E8.1+E8.2 gotowy do odbioru koordynatora po ośmiu kontrolach finalnego head/base. Autor nie scala [PR35](https://github.com/Roseru/aplikacja-mobilna/pull/35). Odbiór O1 APK/Room i wdrożenie O3 pozostają osobne.

Nieautor nie implementował tej dostawy ani testów autora. Wykonał własny managed checkout, własne zamrożone źródło, PG17, SCRAM LOGIN i procesy CLI; nie edytował runtime/testów autora ani nie publikował commitów/PR. Autor zapisał przekazany wynik w tym dokumencie. [Recenzja mastera](RECENZJA_MASTER_MOTYWACJA.md) i odbiór seam nie są tym odbiorem runtime.

## Źródło i tożsamość dowodów

- Exact tested source: `44986a5986c778d0dd3f7529db155197940bb73b`.
- Nieautor potwierdził pusty executable diff backend/contracts/infra/tools/.github do head `3080de5a7e0d1c0c6a09cb56b36db2a811f2b2d2`, base `e93e38e02fed9663217b9036e5831cbc934e1baf`. Następny końcowy commit zmienia wyłącznie raport/recenzję, dziennik i literówkę polecenia O3; jego exact-head CI będzie odczytane osobno.
- Manifest źródła: 695 plików, normalized SHA-256 `b1f8d21b40bfea575fc65d05305d6760555cf1039084f732b4addad3db1fe697`.
- Manifest własnych probes: 7 plików, SHA-256 `6b879990ffd40697a9d5eddf10504c15c3ce21a60468289e973ed965e0277ccd`.
- Prywatny wynik `INDEPENDENT_REVIEW_RESULT.json`: SHA-256 `d6b26c5eae9f22e5cc04e722cf91ab4c2af7ca150488bd4a12c12477bb7b9f57`. Harness, syntetyczne dumpy, credentials, logi i prywatne ścieżki nie trafiają do Git.

## Faktycznie wykonane kontrole

Własne **1370 unit PASS** (77,42 s), **1041 pełne PG PASS** (1126,44 s) oraz **44 unikalne własne oracles PASS**, bez skips. Nie sumujemy powtórek ani zachodzących testów autora. E0: 8 schematów/95 valid/35 invalid/18 scenariuszy/426 linków; Ruff z root i backend cwd, format 251 plików, diff check PASS. Wheel/sdist: 139 dokładnych plików pakietu, 7 dokładnych zasobów migracji, 38 locked runtime dependencies i installed `python -I` PASS.

Niezależne artefakty: wheel SHA-256 `6b9d2e9931d6664e57f2d1f1fdcdafecbcaa9994ac504128e8de47c1d4e5f6b6`; sdist `32ab16c160990993c4cfb7228bbd07aa159e8e8b4f1c24a5adf75d52886b3f49`. Hash artefaktu z oddzielnego builda może różnić się od autora; nieautor sprawdził zawartość względem zamrożonego source.

Własne probes obejmują niezależne granice Decimal, nowe strefy/civil dates, korekty branched heads, ponad 10037 celów, rollback po rzeczywistej projekcji, alternatywne witness i legacy racje, effective column/PUBLIC ACL, dwa procesy przez midnight, barierę lockowania, 2000 dat historii z zapisem za checkpointem, actual dump/restore, zgodność legacy hash, ranking 10137 z remisami/głęboką kontynuacją/quota/opt-out/epoch/purge oraz realne API-role E5 7/30/90 bez sztucznego DiaryDay.

## Zamknięte uwagi

1. P2: świeża afirmacja przyjęta przed restore backfill ginęła podczas resetu projekcji. Własny RED na 8d57178; własny API-role GREEN na 6606cf1, ten kod niezmieniony w 44986a5. Nowa operacja uzgadnia epokę przed markerem, rollback pozostaje atomowy. Legacy/replay/energy-only nie regrantują publikacji.
2. P2: puste minione daty E5 miały closed=false. Własny real API LOGIN/SCRAM RED na 6606cf1; GREEN na 44986a5 dla 7/30/90. No_data/null i źródłowe facts zachowane; odczyt nie tworzy pochodnych lub DiaryDay.
3. Naprawy jakości i pięciu historycznych fixtures zostały sprawdzone w nowym pełnym 1041 PG. Nie osłabiono source guards ani nonempty downgrade. Wcześniejsze porażki własnego harnessu (TEMP/SQL/env/keycloak/password) zostały naprawione wyłącznie w środowisku nieautora; nie są liczone jako PASS.

Własny główny PG oraz izolowane serwery testów E4 zatrzymane; CLI children zakończone i odebrane, tymczasowe restore DB usunięte, review checkout czysty. Nieautor nie wykonywał produkcji, Gemini, billing ani automatyzacji. [Raport](RAPORT_MOTYWACJA.md) podaje dowody autora, ograniczenia fixture i osobne CI.

## Identyfikatory 44 własnych przypadków

```text
test_independent.py::test_independent_inclusive_decimal_and_max2[180-True-2]
test_independent.py::test_independent_inclusive_decimal_and_max2[220-True-2]
test_independent.py::test_independent_inclusive_decimal_and_max2[179.999999-True-1]
test_independent.py::test_independent_inclusive_decimal_and_max2[220.000001-True-1]
test_independent.py::test_independent_inclusive_decimal_and_max2[0-True-0]
test_independent.py::test_independent_inclusive_decimal_and_max2[None-True-0]
test_independent.py::test_independent_inclusive_decimal_and_max2[200-False-0]
test_independent.py::test_independent_sql_decimal_reverse_density[7.999997-123.000001-0.019999]
test_independent.py::test_independent_sql_decimal_reverse_density[9999.999999-999999.999999-999999.999999]
test_independent.py::test_independent_sql_decimal_reverse_density[0.000001-0.000001-0.000001]
test_independent.py::test_independent_new_civil_time_oracles[1994-12-30-Pacific/Kiritimati-1994-12-31T10:00:00+00:00]
test_independent.py::test_independent_new_civil_time_oracles[1985-12-31-Asia/Kathmandu-1985-12-31T18:30:00+00:00]
test_independent.py::test_independent_new_civil_time_oracles[2024-04-06-Australia/Lord_Howe-2024-04-06T13:00:00+00:00]
test_independent.py::test_independent_new_civil_time_oracles[2024-10-06-Australia/Lord_Howe-2024-10-06T13:00:00+00:00]
test_independent.py::test_independent_new_civil_time_oracles[2010-03-13-America/Santiago-2010-03-14T03:00:00+00:00]
test_independent.py::test_independent_sql_contract_date_edges[UTC]
test_independent.py::test_independent_sql_contract_date_edges[Pacific/Kiritimati]
test_independent.py::test_independent_sql_contract_date_edges[America/Adak]
test_independent.py::test_independent_correction_branches_do_not_revive_original
test_independent.py::test_independent_goals_10037_accept_write_no_cap
test_independent.py::test_independent_hook_failure_after_real_projection_rolls_back
test_independent.py::test_independent_closed_weight_witness_alternative_and_distinct[False]
test_independent.py::test_independent_closed_weight_witness_alternative_and_distinct[True]
test_independent.py::test_independent_legacy_ration_no_provenance_still_ordinary_points[None]
test_independent.py::test_independent_legacy_ration_no_provenance_still_ordinary_points[1]
test_runtime.py::test_own_scram_cli_effective_column_public_denials
test_runtime.py::test_own_midnight_pending_two_scram_processes_no_new_sync
test_runtime.py::test_own_account_lock_barrier_worker_observes_committed_correction
test_runtime.py::test_own_large_history_bounded_resume_concurrent_behind_checkpoint
test_runtime.py::test_own_real_dump_restore_true_requires_new_affirmation
test_privacy.py::test_own_legacy_hash_exact_new_presence_and_replay_cannot_regrant
test_privacy.py::test_own_10137_ranking_mixed_ties_quota_anchor_epoch_live
test_privacy.py::test_own_cursor_context_invalidates_without_disclosure[generation]
test_privacy.py::test_own_cursor_context_invalidates_without_disclosure[epoch]
test_privacy.py::test_own_cursor_context_invalidates_without_disclosure[purge_anchor]
test_regression.py::test_fresh_affirm_before_worker_survives_rebuild_and_replay
test_regression.py::test_legacy_or_energy_only_before_worker_never_reaffirms[False]
test_regression.py::test_legacy_or_energy_only_before_worker_never_reaffirms[True]
test_regression.py::test_fresh_preparation_and_affirmation_rollback_atomically
test_lifecycle.py::test_own_purge_cuts_publication_then_deletes_e8_and_invalidates_foreign_cursor
test_lifecycle.py::test_own_upgrade_missing_projection_then_fresh_affirm_survives_worker
E5-empty-calendar-window-7-real-api-SCRAM-no-synthetic-source
E5-empty-calendar-window-30-real-api-SCRAM-no-synthetic-source
E5-empty-calendar-window-90-real-api-SCRAM-no-synthetic-source
```
