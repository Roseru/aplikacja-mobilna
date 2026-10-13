# E9-O2 — finalny niezależny odbiór kodu

Poniżej zapis nieautora w chwili odbioru dfaad1b. Późniejszy pełny PG i CI
są rozliczone w [raporcie wykonania](RAPORT_E9.md); wcześniejsze ograniczenia
nie są nadpisywane.

Finalny niezależny odbiór E9-O2 / ten sam PR54

Oceniany finalny SHA: dfaad1b15b3d0d768f3edb3475da2240875b7762
Baza: 2fc70f7ae612c031f63d53c04d3c81b4402b72c5
Gałąź: codex/backend-e9-korekta-zapotrzebowania
PR: https://github.com/Roseru/aplikacja-mobilna/pull/54
Ocena całego rezultatu backendu E9-O2: 9,2/10. Odbiór kodu PASS.
Zero zidentyfikowanych nierozwiązanych P1/P2 w tym zakresie.
Nie jest to PASS pełnego backend PG, wymaganych zdalnych CI, main, Androida,
produkcji, E9/R lub E10; te bramki pozostają osobnymi wymaganiami.

Zakres przeglądu całego E9: wykonawczy master i zachowane przygotowanie O3,
wymagania, historia/resolver/backfill, dokładne reguły, API/notice/idempotencja,
typed jobs/shared dispatch/attempts/permits/limiter, baseline/zgoda/epoka,
bounded producent, wspólny E4 sync/signed capability scope i legacy snapshot,
E8 źródło/kwalifikacja/projekcje/frozen wyniki, purge/retencja, migracje/ACL,
prowizja i head/readiness, DTO oraz przekazania O1/O3. Własnych produkcyjnych
zmian nie wprowadzano. Źródła ocenione z prywatnych git archive dokładnych SHA.

Własne dowody — bez sumowania nakładających się zakresów:
1. Bbae bbaed6ab23f60e3d1e82897f088a31106b21ca05: szeroki wybrany zestaw
   wszystkich plików E9 i własnych krytycznych prób,156PASS/0failure/0error/0skip,
   832,51s.56unit (45rules+1schema+10provider),95PG
   (36energy+16worker+4sync+6actualprocess+22rulesPG+6migration+5E8)
   oraz5własnych critical tests.250 niezależnych Fraction/Decimal oracles to
   jeden test, nie250 dodatkowych testów.
2. Dfaad: zmieniony końcowy zakres i związane ryzyka,16PASS/0failure/0error/0skip,
   170,42s. Sześć własnych oracles, dwa publiczne final_edges, dwa source/planned
   oraz wszystkie sześć migration tests. Static diff bbae→dfaad obejmuje tylko
   scoped drugi54000 w004, conditional003 ACL, nowe testy i dokumentację.
3. Dfaad:33E4 SCRAM/server-log/secret/upgrade tests PASS/0skip,41,34s,
   w nowym prywatnym klastrze. Realny fresh/minimal E3→head bez opcjonalnych ról
   potwierdza conditional003 ACL. Wspólne role i bazy autora nie były zmieniane.
4. Niezależny odczyt autorskiej e9_installed_proof_test/head0024: istniejący
   minimalny actual LOGIN ma SCRAM verifier, brak uprzywilejowanych flag,
   jedną membership AI z INHERITtrue/SETfalse/ADMINfalse, ścisły produkcyjny
   VERIFY_ACL_SQL przechodzi; PUBLIC helper oraz internal apply/mutate/raw reserve
   są niedostępne. Własne rzeczywiste połączenie SCRAM tym LOGINem PASS;
   błędne hasło odrzucone, trzy SET ROLE (AI/API/migrator) odrzucone42501,
   raw diary read/write denied. Bez zmiany ról lub danych.
5. Diff-check PASS. Migracje0001–0021 i wypchnięta0022 są niezmienione.
   Conditional REVOKE statement003 został jawnie poprawiony w pending PR,
   ponieważ brak opcjonalnych ról uniemożliwiał dotarcie do forward004;
   funkcje003 nie zostały przepisane. Nowe definicje SQL są w004.

Zamknięte ustalenia i własne oracles:
- Clone celu z identycznym estimate zachowuje zatwierdzone E2700 i ID E9,
  również po upgrade istniejących duplicate0022. Raw immutable history pozostaje.
  Nowy pełny artefakt estimate ma nowąE; jawna history_correction zachowuje graf
  i przesunięte daty, a brak wymaganej historii blokuje analizę liczbową.
- Puste przecięcie kwantów wire12 daje jawny conflict, bez liczby poza clamp.
  Dokładna granica i250 niezależnych losowych arytmetycznych oracles PASS.
- Realne100001 syntetycznych źródeł daje scoped odmowę i pozostawia wspólny
  runner dostępny. Fault injection drugiego contextu po wzroście axis metadata
  również jest scoped; brak energy admission/job, photo innego konta działa.
- Literalny pristine manifest004 odmawia actual drift niezmienionego guarda,
  nawet gdy wcześniejsze003 przehashowało stored digest. Nie autoryzuje driftu.
- Internal helper PUBLIC/runtime EXECUTE zamknięte; minimalny worker otrzymuje
  jedynie dwie niezbędne funkcje producenta, bez raw diary/APPLY/reserve.
- Ranking-only public PUT zachowuje requested=true, ale resetuje effective/
  baseline/notice. Stara afirmacja odrzucona, świeża osobna afirmacja działa,
  żaden taki odczyt/PUT/retry nie wywołuje modelu.

Ograniczenia dowodów:
- Pierwszy source limit badano realnym100001 fixture; bulk setup użył lokalnego
  session_replication_role=replica, normalne triggers wróciły po commit.
  Drugą ścieżkę54000 badano kontrolowaną prywatną PG fault injection;
  nie skonstruowano fizycznego źródła dokładnie przy8MiB.
- Własne konta i część JWT/principal są syntetyczne. To realne PG/LOGIN/procesy,
  nie odbiór rzeczywistego APK, publicznego Keycloak/TLS ani klientów końcowych.
- Własnego AI CLI/network dispatch na installed wheel nie powtarzano.
  Installed-I wheel/migration/CLI proof autora jest odrębnym dowodem;
  mój installed proof to realne SCRAM/read-only ACL/SET ROLE denials.
- Odrzucona automatycznie dodatkowa mutacyjna próba ACL nie została wykonana
  ani zaliczona; zastąpił ją zatwierdzony odczyt istniejącego LOGIN z auth/denials.
- Pełna regresja backendu i osiem required jobs aktualnego PR nadal wymagają
  osobnego rzeczywistego GREEN. Historyczne RED pozostają RED swoich SHA.
- Brak Google IO, billing, rollout, merge, nowego watchera lub E10.
  Live pozostaje zamknięte; automat wymaga obecnej online zgody/notice/baseline.

Evidence prywatne: final-bbae.xml, final-dfaa.xml, secret-dfaa.xml oraz
read_installed_acl.py w folderze tego raportu. Raw logs/credential artifacts
nie nadają się do publikacji. Własne efemeryczne bazy/klaster posprzątane przez
fixture finally; klastrów autora/użytkownika nie zatrzymywano.

Rekomendacja: zachować jeden PR, odczytać finalny pełny PG i wymagane CI dla
aktualnego head/base; dopiero po ich sukcesie właściciel może wykonać merge.
