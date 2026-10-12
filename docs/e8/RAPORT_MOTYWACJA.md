# Raport motywacji E8.1 + E8.2 - osoba 2

12 października 2026. Branch `codex/backend-e8-motywacja-ranking`, [PR35](https://github.com/Roseru/aplikacja-mobilna/pull/35), baza `e93e38e02fed9663217b9036e5831cbc934e1baf`. Aktualny frozen kod: `b2c6709e95796ab2c10a63493b78635664ea4f9e`. Autor nie scala PR. Własny pełny odbiór, nowy niezależny nieautor 9,3/10 bez P1/P2 i osiem CI tego kodu przeszły. Końcowy commit dokumentacji i jego osobne exact-head CI będą w opisie PR.

## Wynik i zgodność

Backend dostarcza regularity_v1, rangi, cztery odznaki z reaktywacją, trwałe prywatne projekcje i dobrowolny ranking ze świeżą afirmacją epoki oraz opaque live keyset. Projekcja działa atomowo w savepoincie źródłowej mutacji przed receipt. Ograniczony porcjami worker odbudowuje całą historię, zamyka daty w zachowanej strefie i obsługuje korekty, replay, purge oraz nową epokę po restore. Brak danych pozostaje null, alternatywnych wariantów nie sumujemy.

[Decyzje](DECYZJE_MOTYWACJA.md), [interfejs](INTERFEJS_PROJEKCJI.md), [O1](INTEGRACJA_O1_MOTYWACJA.md) i [O3](KONFIGURACJA_O3_MOTYWACJA.md) opisują integrację. Migracja `0016_e8_motivation` po `0015_e7_ai` dostarcza E8; forward repair `0017_e8_purge_commit` naprawia COMMIT operatora. Opublikowane 0001–0016 pozostały identyczne, opublikowana 0017 jest zamrożona. Readiness i worker wymagają head 0017.

ConsentInput/Consent/ProfileRead, receipts, sześć encji wire v1, ACK i snapshoty zachowują zgodność. Opcjonalny nagłówek istniejącego PUT zgód nie zmienia hasha dawnych żądań. Read, replay, energy-only i rebuild nie afirmują publikacji. E5 używa tych samych źródłowych faktów SQL i zachowuje kalendarzową klasyfikację pustych dat/no_data/null. API oraz worker nie zapisują dowolnych punktów, odznak lub markerów.

## Naprawa COMMIT purge

P2 odziedziczony z 0015: canonical purge SECURITY DEFINER poprawnie wracał, ale odroczony `app.diary_aggregate_count()` działał przy COMMIT jako minimalny operator bez SELECT meals. Wynik 42501 cofał cały purge. Autor i dwaj nieautorzy koordynatora odtworzyli go na fresh 0015 i 0016 z rzeczywistym LOGIN SCRAM i żywym Meal/MealItems. [Zapis blockera](https://github.com/Roseru/aplikacja-mobilna/pull/35#issuecomment-6115507635).

Zaakceptowana 0017 zmienia tylko SECURITY DEFINER istniejącego checkera. Frozen body SHA-256 `a07b30c41bda409d6aaa734486170d0141939eae729007269d3b46f2da5e473d`, owner calorie_app_migrator bez SUPER, closed search_path, ACL oraz dwa właściwe deferred triggers są weryfikowane fail-closed. Body nadal wyłącznie sprawdza 1..100 źródłowych elementów i zwraca NULL. Nie zmienia się chain E8→E7→E6→E4, lock order, dane lub uprawnienia LOGIN; nie ma nowych GRANT albo flush ALL.

Downgrade metadata zawsze zachowuje tę wstecznie zgodną poprawkę z jawnym warning. Nie usuwa danych/jobs/fences ani nie przywraca znanego 42501. Re-upgrade sprawdza tożsamość body/path/owner/ACL i jest idempotentny. Starsze data-protection guards nadal obowiązują.

Normalny operator CLI używa świeżych oddzielnych transakcji begin commit → provider → confirm commit → purge commit, z INITIALLY DEFERRED. Ręczne diary IMMEDIATE nadal odmawia 23514 podczas przejściowego children→parent delete i cofa cały graf; świeży default retry przechodzi. Naprawa nie przestawia caller modes ani nie sprawdza wcześniej innej pending queue. [SET CONSTRAINTS](https://www.postgresql.org/docs/17/sql-set-constraints.html) i [SECURITY DEFINER](https://www.postgresql.org/docs/17/sql-createfunction.html) zweryfikowano w dokumentacji PG17.

## Aktualne dowody autora

- **1370 pełne unit PASS**, 72,94 s; **1059 pełne PG17.11 PASS**, 1129,84 s. JUnit: zero failures/errors/skips. Nie sumujemy zakresów lub powtórek.
- **18 nowych real PG scenariuszy PASS**, 51,73 s: hardened provision CLI/SCRAM, parent canonical RED→filled upgrade GREEN i fresh GREEN, pełny żywy graf E4/E7/E8 z photo/job/aktywną odznaką/markerem/cursorem partnera, rollback po purge przed COMMIT, resume/retry, partner/fence/410, realny CLI begin/resume/status/retry, mixed modes, cardinality, osiem metadata tamperów i empty/filled downgrade/re-upgrade.
- 0 items odmawia przy COMMIT; poprawne 100 przechodzi. 101 zwykle odmawia natychmiast przez istniejący position CHECK. Osobny transactional diagnostic tymczasowo usuwa tylko ten zewnętrzny CHECK, aby potwierdzić również górną granicę samego checkera przy COMMIT; rollback przywraca CHECK i cały graf. Nie osłabiono wydanych constraints.
- Actual archive restore, source history 10001 dat wag/batch 97/104 cykle/zapis za checkpointem oraz 10001 wersji celu i zwykły przyjęty zapis 10002 przeszły także w nowym pełnym PG. Brak limitu historii i fikcyjnych DiaryDay/punktów. Ranking 10103 uczestników/102 strony, remisy, deep continuation, quota/TTL/ownership/epoch/generation i konkurencja również w nowym zestawie PASS.
- E0: 8 schematów, 95 valid, 35 invalid, 18 scenariuszy, 435 linków, Decimal/kompletność/normalizacje PASS. Ruff/format 281/diff oraz fresh 0017 ORM/Alembic check PASS.
- Wheel/sdist exact source b2c: 139 plików pakietu, 8 zamrożonych zasobów migracji E8, 38 zależności zgodnych z lock; czysta instalacja `python -I` i head 0017 PASS. SHA-256 wheel `9ecfed874be7a7ff49c396d77fa11be0ceb4ab0b88bc0778aec99ff940c44db1`, sdist `aa5f0cae7e224eedc102533dccb6b18433f49a2591c2a1e758ce06e427938413`.

## Nowy niezależny odbiór i CI

Własny nowy nieautor: **9,3/10, zero otwartych P1/P2**. Oddzielny managed checkout source b2c, PG17/SCRAM/process: **1370 unit i 1059 pełne PG PASS**, bez skips, oraz **18 nowych unikalnych własnych oracles PASS**. Osobne delivered 18 zachodzą na pełny zestaw i nie są sumowane. [Recenzja](RECENZJA_MOTYWACJA.md) podaje dokładne case IDs, manifesty i nowe red→green; wszystkie własne usługi nieautora zatrzymane. Poprzednie 44 probes/9,3 oraz CI5c są historyczne i nie zastępują tego odbioru.

Koordynator osobno odebrał rzeczywistą 0017 ocenami 9,3/10 i 9,4/10 na własnych nowych PG/HTTP/metadata przypadkach. [Decyzja granicy](https://github.com/Roseru/aplikacja-mobilna/pull/35#issuecomment-6115913896) zwalnia zależny etap E8.3, bez merge PR35 lub zastąpienia pełnego odbioru wykonawcy.

[CI38189258108](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38189258108), exact head b2c/base e93: **osiem success** — quality, contracts, local-integration, postgres, keycloak-pkce, android-build, android-device, ci-required. Odczytane aktualne logi: **1370 unit/1059 PG/28 Keycloak/21 infra/87 JVM/86 device**, zero failures/skips JVM/device, wheel i Docker installed-I smoke PASS. Końcowy commit dokumentacji wymaga własnych ośmiu kontroli.

## Pozostałe poprawki i granice

Dwa wcześniejsze P2 również mają nowe właściwe regresje: świeża afirmacja po restore, przyjęta przed backfill, jest ustanawiana po atomowym uzgodnieniu starej epoki; puste minione daty E5 zachowują calendar closed bez zmiany source completeness/in_goal/null. Pełny nowy zestaw obejmuje obie poprawki.

Wcześniejsze niepełne próby/CI6606 z pięcioma historycznymi fixture failures i zewnętrznym ECR429 nie były PASS. Poprawiono strict untouched placeholders, jawne head/table set i bootstrap bez osłabiania nonempty downgrade/source guards. Błędy nowych prywatnych fixture (pending backfill, kopiowany item_id, brak importu json, format) zostały naprawione przed właściwymi przebiegami; nie są dodatkowym PASS.

Duże historie są syntetyczne. Bulkseed znanych UTC i osi celu pomija wyłącznie opisane dawne powtarzane per-row guards po walidacji całej osi/dat, przywracając je przed normalnym przyjętym zapisem. E8/FK/CHECK/owner/revision pozostają. Rankingowy seed punktów jest oracle query/paginacji, a nie naliczaniem z 10103 dzienników. Pełnohistoryczne agregacje mogą korzystać z work_mem/spill; porcje nie są limitem historii.

O1 osobno odbiera APK/Room/UI/cache/świadomy nagłówek. O3 osobno odbiera provision/deployment/monitoring/backup/restore/RPO/RTO. E8.3 rezerwuje 0018 po 0017 i jeden zbiorczy właściciel challenge locks UUID ASC; runtime Nemesis nie jest podłączony w tej dostawie. E8.3/4/E9, Google/billing/produkcja i automatyzacje poza zakresem. Historyczny checkout E4 i Random Data zachowane. Własny autorowy PG, natywne helpery i CLI zatrzymano po nowym pełnym odbiorze; nie zatrzymywano usług innych etapów. Artefakty/harness/credentials/logi pozostają poza Git.
