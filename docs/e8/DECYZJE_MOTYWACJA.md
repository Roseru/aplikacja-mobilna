# Decyzje motywacji E8.1 + E8.2 - osoba 2

11 października 2026. Źródło: af8df9af9bfd32aa8145eac6114fdfc7261a8477; migracja zarezerwowana 0016_e8_motivation po0015_e7_ai. Dokument zapisano przed implementacją runtime. To decyzje wykonawcze, nie dowód ukończenia.

## Źródła i granica transakcji

Źródła pozostają w sześciu encjach sync-v1. SourceMutationContext niesie owner, kind, entity, stare/nowe daty i rewizje, pozycję wejściową/wyjściową oraz zmianę osi celu. Hook działa po flush i pełnej walidacji agregatu, w savepoincie istniejącej operacji, przed receipt i ACK. Konto i sync_counter są już zablokowane. Przyjmowana korekta aktualizuje projekcje atomowo; wyjątek cofa także źródło. Replay nie wykonuje hooka. Commit pozostaje własnością caller.

Przyszłe projekcje otrzymują jawny punkt rozszerzenia: fazę blokowania przed odczytem jednego clock_timestamp() i fazę aktualizacji z tym samym qualified_at. Kolejność: konto, counter, przyszłe challenges UUID ASC, projekcje. Nie implementujemy Nemesis w tej dostawie. Zmianę osi analizujemy przez istniejący resolve_goal_dates przed/po; Meal.goal_id nie wybiera historycznego celu punktowania.

## Baza, uprawnienia i odbudowa

API i odrębny calorie_app_motivation_worker nie otrzymują surowego UPDATE/INSERT/DELETE punktów, dni lub odznak. Wąskie SECURITY DEFINER funkcje obliczają wyniki ze źródeł; nie przyjmują punktów lub odznak. Funkcje mają zamknięty search_path i REVOKE PUBLIC EXECUTE. Osobna baza roli NOLOGIN plus odrębny LOGIN umożliwia O3 odcięcie workera motywacji bez zmiany AI lub retencji. Worker nie ma surowego odczytu dziennika.

Prywatny dzień przechowuje historyczną strefę, pierwszy rzeczywisty moment po końcu daty, fingerprint/rewizje, kompletność, in_goal, candidate/materialized0..2. Źródła wagi i racji zachowują własne strefy; waga nie tworzy DiaryDay. Konto przechowuje sumę, revision, source_position, epokę i keyset checkpoint backfill. Worker wybiera kandydatów bez blokady projekcji, potem blokuje konto/counter i ponownie sprawdza stan oraz zegar bazy. Przetwarza ograniczone porcje dat, a sumy i witnesses obejmują pełną historię. Obliczenia SQL muszą być zgodne z nutrition_v1/Decimal i wspólnymi faktami używanymi przez E5; Pythonowe czyste reduktory są oracle testów.

Upgrade zakłada pending, nie publikuje historycznego zera. Backfill jest restartowalny; współbieżny zapis serializuje konto i uaktualnia dotknięte daty. Zmiana epoki ponownie zamyka publikację pochodnych do odbudowy i nie odnawia zgody. Purge E8 deleguje do całego wrappera E7, zachowując cleanup intents i anonimową pulę. Niepusty downgrade odmawia przed DDL.

## Punkty, witnesses i czas

regularity_v1:1 za efektywnie kompletną zamkniętą datę, drugi za dodatni historyczny cel w domkniętym paśmie0,9..1,1. Brak celu daje in_goal=null i najwyżej1. Maksymalnie2; odznaki nie punktują. Rangi Rekrut0..19, Szeregowy20..59, Kapral60..119, Sierżant120+.

Kody: complete_streak_10, in_goal_streak_10, weight_days_4_14, ration_days_5. Minimalny historyczny witness ma10/10/4/5 dat; alternatywny witness podtrzymuje odznakę. Reaktywacja zachowuje jedną tożsamość i first_awarded_at. Waga wymaga4 distinct dates w rozpiętości≤13; racja wymaga snapshotu oraz dodatniej spożytej pozycji z ration_component_position. Legacy null pozostaje null i nie kwalifikuje odznaki, ale nie odbiera zwykłych punktów.

Zamknięcie wynika z historycznej IANA strefy, nigdy późniejszego profilu lub UTC+24h. Resolver waliduje roundtrip, rozstrzyga ambiwalentną lub pominiętą północ i datę pominiętą przez zmianę offsetu. Skrajna wspierana data bez reprezentowalnego następnego instant pozostaje wstępna, nie daje fikcyjnego potwierdzenia. Testy używają niezależnego oracle UTC.

## Zgoda i ranking

Jedyna zgoda to UserConsent.ranking. Bez X-Ranking-Consent-Epoch hash pozostaje dokładnie strukturą body/if_match; obecny nagłówek dodaje kwalifikowaną semantykę. Wyłącznie nowa zaakceptowana ranking=true z poprawną bieżącą epoką potwierdza provenance ranking_affirmations. Replay, read, energy-only, legacy true i restore nie ustanawiają świeżości. Opt-out ją unieważnia. Stare DTO i receipts pozostają niezmienione. GET motivation pokazuje requested/effective/pending_consent_refresh.

Ranking live obejmuje active+żywy profil+ranking true+aktualny marker+ready backfill. Publiczny payload zawiera pseudonim, punkty, rangę, liczbę odznak i konkursową pozycję RANK wyłącznie po punktach. UUID stabilizuje prezentację wewnętrznie. Limit1..100, brak globalnego cap.

Losowy256bit token jest nieprzezroczysty; seek jest wyłącznie na serwerze i wiąże owner/generation/epoch/limit/purpose/TTL10min. Ograniczamy8 początkowych sesji na requester w10min oraz2 ostatnie tokeny na sesję. Kontynuacja nie zużywa nowej sesji i pozwala dotrzeć do dowolnej głębokości; po odzyskaniu puli można zacząć ponownie. Bez kopii wyników, każda strona świeżo sprawdza publikację. Opt-out anchor nie blokuje seek; purge anchor unieważnia cursor. Zmiany live mogą powodować pominięcie/powtórzenie, wcześniejszych pobrań nie można zdalnie cofnąć.

## Przykłady i odbiór

2000kcal cel:1800 i2200 dają2,1799 daje1; pusty lub energy-null daje0, brak makr nie odbiera znanej energii. Ranking10,10,8 ma pozycje1,1,3. True odzyskane po restore nadal niewidoczne po rebuild, do nowej świadomej afirmacji w bieżącej epoce.

O1 otrzyma kontrakt, pending/local/server i invalidację cache logout; O3 provision/ACL/CLI/minutowy cykl/startup/backfill/restore. Osobny proces --once/co60s, bounded batches i graceful shutdown. Dowody autora, niezależnego nieautora≥9/10/zeroP1P2 i osiem exact-head/base CI będą zapisane w raporcie. Brak wdrożenia produkcji, Google/billing, E8.3/4/E9 lub automatyzacji.