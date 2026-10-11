# Master E8.1 + E8.2 — punkty, odznaki i ranking - osoba 2

Wersja 1, 11 października 2026 r. Wykonawca: Agent 2 / OSOBA 2. Priorytet: jakość, ochrona danych i czytelny projekt. Jest to pierwsza z trzech grup E8; E8.3 i E8.4 mają własne czaty/mastery, E8.5 odbiera koordynator. [Master koordynacji](MASTER_PROMPT_KOORDYNACJA_E8.md) określa autoryzację, przekazanie i workflow. Zlecenie startowe poda dokładny scalony main zawierający E7 i ten master; nie startuj z historycznego E4.

## 1. Rezultat i wejścia

Dostarcz kompletny E8.1+E8.2-O2: deterministyczne punkty/rangi, cztery odznaki z korektą/cofaniem, ranking opt-in, trwałe projekcje i osobny worker dojrzewania po lokalnej północy/catch-up. Rzeczywisty PG17, atomowe źródło+projekcje+sync/receipt, migracja/backfill/purge/ACL/restore, kontrakty i dowody są częścią wyniku. Endpointy lub sam reducer bez tych mechanizmów nie wystarczą.

Przeczytaj AGENTS, WYMAGANIA_PROJEKTOWE WF10–11/11.3/11.7 i odpowiednie KO, ARCHITEKTURA, PLAN_PRAC, WORKFLOW, aktualny KOMUNIKACJA_AGENTOW, raporty i przekazania E4/E5/E7 oraz aktualne diary/profiles/analytics/sync/identity/deletion. E7-O2 jest odebraną/scaloną podstawą; E7-R, official E5-C, rzeczywiste APK/WorkManager O1 i produkcja O3 pozostają osobne. Brak tych wejść nie blokuje niezależnej motywacji. Nie wykonuj E8.3/4, E9, Google, billing, produkcji lub harmonogramów Codex.

## 2. Zasady v1 — bez nowych reguł produktu

- `regularity_v1`: zamknięty efektywnie kompletny dzień =1 punkt, dodatkowy1 w celu ±10% dodatniego historycznego celu, z granicami włącznie. 0–2 pkt dziennie. Więcej posiłków/kcal/deficytu nie daje dodatkowych punktów. Odznaki nie dają punktów. Rangi: Rekrut0–19, Szeregowy20–59, Kapral60–119, Sierżant≥120; żadnych nowych uprawnień.
- Użyj wspólnej reguły efektywnej kompletności i `nutrition_v1`/Decimal. Pusty dzień, energia null, suma0, ostatni usunięty posiłek i brak deklaracji dają0. Brak makr nie jest zerem i sam nie odbiera znanej energii/kompletności. Kompletny dzień bez celu może dać1; `in_goal` przy brakującym celu pozostaje null.
- Cztery odznaki:10 kolejnych kompletnych dni,10 kolejnych dni w celu, pomiary w4 różnych dniach w14 kolejnych datach kalendarzowych (różnica skrajnych dat≤13), posiłki z racji w5 różnych dniach (nie muszą być kolejne). Wagę i racje można zaliczyć bez kompletności dziennika. Brak odznaki4000kcal.
- Wszystkie odznaki potwierdzamy na zamkniętych dniach; wcześniej jest tylko postęp. Dowolny poprawny historyczny witness daje odznakę, nie wyłącznie ostatnie7/30/90 dni. Po korekcie ostatniego witness cofnij; alternatywny witness podtrzymuje. Ponowne spełnienie reaktywuje tę samą unikalną tożsamość `(owner,badge_code,rule_version)`, zachowując first_awarded_at; nie tworzy drugiej nagrody.
- Dzień racji wymaga żywego posiłku z zachowanym snapshotem racji i rzeczywiście spożytą dodatnią pozycją powiązaną przez `ration_component_position`. Sam wybór racji lub nazwa posiłku nie wystarczy. Nie odczytuj bieżącego katalogu zamiast historycznego snapshotu; jest to deklaracja użytkownika, bez nowego systemu antifraud.
- Punkty i witnesses obejmują całą historię konta, także zatwierdzony import gościa. Okna wykresów90dni i sync30×24h nie skracają tej historii.

## 3. Czytelna struktura i wspólne interfejsy

Rozszerz istniejący moduł analytics wydzielonym `modules/analytics/motivation/`: models, rules, repository, service, schemas, router. Osobny `motivation_worker.py`/CLI i dokumenty `docs/e8/`. Router odpowiada za transport/auth, schemas za ścisły kontrakt, rules za deterministyczną domenę, service za przypadek użycia i granice transakcji, repository za SQL. Commit należy do caller; brak ukrytych commitów, ORM eventów zastępujących kontekst agregatu, drugiego backendu, Redis lub zewnętrznego brokera.

Jedno wspólne miejsce hooka dla przyjętej mutacji źródła, wewnątrz istniejącego savepointu sync po pełnej walidacji/flush, przed receipt/ACK/commit. Jawny SourceMutationContext przechowuje rodzaj źródła, stare/nowe daty, rewizje/pozycję wejściową i zmianę osi celu. Zaprojektuj punkt rozszerzenia przyszłych projekcji Nemesis E8.4, ale nie twórz pustej „zaliczonej” implementacji Nemesis. Koordynator zamraża ten interfejs przed zleceniem zależnego zakresu.

## 4. Dane i atomowość

Rezerwacja nowej migracji po E7: `0016_e8_motivation`, down_revision `0015_e7_ai`; przed zapisem sprawdź aktualny head i rezerwacje koordynatora. Jeśli main wprowadził kolizję, zgłoś koordynatorowi i uzgodnij kolejną nieopublikowaną migrację, nie przepisuj historii. Jedna linia Alembica;0001–0015 niezmienne.

Trwała prywatna projekcja dnia ma owner/date/rule, historyczną strefę, matures_at, source fingerprint/revisions, efektywną kompletność/in_goal, candidate_points i materialized_points0..2. Sparse dates są dopuszczalne; brak daty przerywa streak. Account projection ma całkowitą sumę/revision, source_position, stan backfill i należną maturację. Badge jest unikalną reaktywowaną tożsamością z minimalnym witness i datami aktywacji/cofnięcia. DB CHECK/FK/unique/indexy wymuszają invarianty; suma materializowana odpowiada sumie dni, liczba odznak liczbie aktywnych wierszy.

Korekta/przeniesienie posiłku lub wagi przelicza starą i nową datę. Zmiana historycznego celu/correction_of może wpływać na całą oś: użyj istniejącego `resolve_goal_dates`, porównaj skutki przed/po. `Meal.goal_id` nie jest wiążącym wyborem celu punktacji. Nie ożywiaj starego heada korekty i nie przepisuj snapshotów.

Źródło, projekcje, punkty, odznaki, append_change i receipt zatwierdzają się razem. Konflikt, błędny checkpoint/payload, rollback lub failure hooka nie zostawiają częściowej aktualizacji. Lost ACK/replay/already_applied nie dodaje kolejnego naliczenia. Nie dopisuj wyników do sześciu encji starego sync-v1 ani jego snapshotów/ACK; wyniki E8 mają własną rewizję, a source_position jest śladem wejścia, nie nowym sync checkpointem.

Upgrade nie publikuje historycznych kont z fałszywą sumą0. Dostarcz rzeczywisty restartowalny bounded backfill istniejącej historii pod per-owner blokadą/checkpointem; do ukończenia własny wynik jest pending_backfill i konto nie jest publikowane z wynikiem ostatecznym. Zapis współbieżny nie gubi ani nie duplikuje pracy. Nie importuj ruchomego kodu biznesowego z Alembica. Przy pustym downgrade zachowaj E0–E7; niepusty E8 downgrade domyślnie odmawia atomowo przed DDL. Polityka odtworzenia pochodnych jest jawna; utraconych źródeł nie odtwarzamy fikcyjnie.

Zachowaj bounded pamięć/batche i indeksowane odczyty, także dla historii>90dni. Nie załatwiaj limitu zasobów cichym obcięciem historii, częściowym ACK, zawężeniem30dni lub arbitralnym zmniejszeniem wcześniej wspieranego zakresu. Opisz granice zasobów i wykazuj zachowanie na dużej syntetycznej historii oraz resume/rebuild; brak N+1 po każdym posiłku/dniu.

## 5. Czas, worker i blokady

Maturity punktów/streaków wynika z zachowanej strefy `DiaryDay`, nie z później zmienionego profilu. Zmiana profilu nie przepisuje historii. Wspólny reducer/resolver zamknięcia dnia używany przez E5 i E8 musi być spójny; jeśli E5 używa bieżącej strefy do oceny historycznego dnia, popraw tylko właściwą klasyfikację i daj regresję, zachowując kontrakt oraz okna7/30/90. Nie twórz drugiego wzoru kompletności/in_goal.

Waga bez DiaryDay nie tworzy sztucznego dnia. Distinct weight date staje się świadectwem po zamknięciu daty w zachowanej strefie żywego pomiaru; przy kilku strefach tej samej local_date wystarcza dojrzały poprawny pomiar, a usunięcie/przeniesienie ostatniego takiego źródła przelicza kwalifikację. Tak samo świadectwo racji korzysta z właściwego historycznego czasu źródła. Future dates nie dostają potwierdzonego wyniku.

Matures_at to pierwszy rzeczywisty moment po zakończeniu danej lokalnej daty: następna lokalna północ/jej prawidłowe rozstrzygnięcie IANA → UTC, z roundtrip walidacją. Nie dodawaj24h w UTC. Sprawdź Warsaw23/25h, midnight offset changes/skipped dates i granice dat wspieranych kontraktem. Kontrolowane testy mają niezależny oracle UTC; nie śpij do prawdziwej północy.

Lock order: konto → sync_counter → przyszłe challenges UUID ASC → projections konta/dni w stabilnym porządku. Worker wybiera bounded kandydatów bez wcześniejszego lock projection, potem konto/counter, recheck active/generation/źródła i czas DB `clock_timestamp()` po blokadach. Nie odwracaj kolejności przez SKIP LOCKED projekcji→konto. Przy mutex transakcyjnym DB nie dodawaj zbędnej zewnętrznej kolejki lub IO lease.

Osobny proces motivation worker: startup catch-up, cykl co60s, `--once`, bounded batches, graceful shutdown/status/backlog i restart bez duplikacji. Nie zmieniaj `calorie_app.worker` AI ani jego uprawnień do prywatnego dziennika. Ustal przed kodem minimalny odrębny LOGIN/rola E8 lub ściśle ograniczone funkcje dotychczasowego calorie_app_worker; uzasadnij wybór w decyzjach i sprawdź effective permissions. Nie dawaj raw UPDATE punktów callerowi API/worker; źródła pozostają jedyną podstawą. O3 dostaje dokładne provision/ACL/CLI/schedule/monitoring, nie deklarację wdrożenia przez autora.

Bieżący dzień zapisuje już kandydata należnego po zamknięciu. Przed maturity confirmed0; po północy worker materializuje bez nowego sync. Odczyt jawnie odróżnia pending_materialization od final, również po downtime. Wiele procesów/restartów/korekt nie duplikuje punktów. Stary odczyt workera przed correction rewaliduje po uzyskaniu locków.

## 6. Kontrakt HTTP i prywatność

Normą jest FastAPI→backend/openapi.json i generated schemas/przykłady. V1: `GET /api/v1/me/motivation` (własne punkty/ranga/odznaki/postęp/revisions/aktualność) i `GET /api/v1/ranking` (bieżący dobrowolny ranking). Statusy pending/final/revoked i reguły muszą być jawne, odpowiedzi bounded do1MiB i no-store także przy błędach auth/parsera. Wynik lokalny nie jest potwierdzonym serwerowym wynikiem.

Użyj istniejącego `UserConsent.ranking=false` i `/me/consents`/If-Match/Idempotency-Key. Nie twórz drugiej zgody rankingowej ani nie przestawiaj automatic_energy_adjustment przy zmianie rankingu. API nie przyjmuje owner/points/rank/badge/status/rule authority z klienta. Exact JWT/owner/active/generation/epoch zasady pozostają, admin/moderator nie odczytuje cudzych prywatnych motywacji.


Świeżość publikacji ma oddzielny server-side znacznik ranking_consent_epoch/source_revision, bez drugiej zgody i bez zmiany starego body UserConsent. Wybór v1: opcjonalny nagłówek `X-Ranking-Consent-Epoch` istniejącego PUT /me/consents. Jawne ranking=true z dokładnym aktualnym nagłówkiem, nową faktycznie zatwierdzoną operacją i poprawnym If-Match potwierdza aktualną epokę; niepoprawny kontekst odmawia atomowo. Body bez tego nagłówka zachowuje stare zachowanie zapisu, lecz nie ustanawia brakującej świeżości publikacji. Opt-out ją unieważnia; zmiana automatic_energy_adjustment, read, backfill, idempotent replay lub samo odtworzone true nie odnawiają zgody. Początkowo przed aktywacją E8 ranking wymaga takiej świeżej afirmacji także dla istniejących true bez dowodu epoki. O1 dostaje jawny pending_consent_refresh/effective ranking stan i UI świadomej afirmacji. Nowy nagłówek jest częścią semantyki i hash nowej operacji; stare receipts bez niego pozostają kompatybilne, reuse key z inną semantyką daje409 i żaden replay nie reaktywuje publikacji.

Ranking obejmuje wszystkie aktywne konta z aktualnym opt-in potwierdzonym w bieżącej epoce, ukończonym backfill i żywym profilem. Pokazuje tylko pseudonim, punkty, rangę i liczbę aktywnych odznak; bez account UUID/issuer/sub/email/surowej masy/celu/posiłków. Własny odczyt może mieć własną pozycję nullable poza opt-in. Pozycja konkursowa `RANK` wyłącznie po punktach:10,10,8→1,1,3. Pseudonim+UUID stabilizują tylko sortowanie prezentacji, nie remis; UUID pozostaje wewnętrzny.

V1 wybiera bounded live keyset pagination, limit1..100, bez limitu globalnej pozycji uczestnika. Opaque losowy token wiąże requester/generation/sync_epoch/limit/purpose/TTL10min; minimalny seek tuple jest po stronie serwera, a token nie ujawnia account UUID/pseudonimu/punktów (podpisany plaintext/base64 nie wystarcza). Cursor nie jest kopią wyników rankingu. Każda strona/ponowienie świeżo sprawdza aktualny opt-in/profil/state i RANK po punktach przed ograniczeniem strony. Seek przy usuniętym/opt-out anchorze nie zależy od jego publikacji; po purge anchoru unieważnij powiązany cursor i zwróć jawny restart bez prywatnych danych. Dokumentuj możliwe powtórzenie/pominięcie przy zmianach między stronami żywego rankingu. Ogranicz liczbę aktywnych cursorów i ich tworzenia per requester, cleanup i odczyt, zachowując legalną kontynuację has_more i dostęp do głębokich pozycji po odzyskaniu puli, bez trwałego obcięcia rankingu. Opt-out/deleting/brak profilu odcina kolejne odczyty po commit; wcześniej pobranych danych nie obiecuj zdalnie cofnąć. Zmiana pseudonimu korzysta z bieżącego profilu. Nie dodawaj publicznych danych kontaktowych/adresowania Nemesis w tej grupie.

### Szczegóły kompatybilności v1

Bez X-Ranking-Consent-Epoch pozostaw dokładnie dawny fingerprint na strukturze {'body': ..., 'if_match': ...}; nie dodawaj klucza null lub nowej wersji do starego hash. Przy obecnym nagłówku fingerprint obejmuje kwalifikowaną epokę i jej obecność; present/absent lub inna epoka pod tym samym key daje409. Nowe effective/pending_consent_refresh występują wyłącznie w nowym GET motivation, nie w ConsentInput/Consent/ProfileRead.consents lub zapisanych response receipts; zachowaj strict DTO O1. source_revision znacznik afirmacji jest provenance, nie warunkiem równości z bieżącą UserConsent revision: energy-only bez nowej afirmacji zachowuje ważny marker, lecz nie ustanawia brakującego po restore. Opt-out go unieważnia, późniejsze legacy true go nie przywraca.

Zachowaj historyczne racje z dodatnimi pozycjami i ration_component_position=null bez automatycznego dopisywania markerów/źródeł. Brak kwalifikującego provenance dotyczy odznaki racji, nie zwykłych punktów kompletnego dnia. Dodaj osobny legacy fixture i opisz tę granicę w przekazaniu O1.

## 7. ACL, purge, restore i zgodność

Zachowaj oddzielne API, worker, AI, migrator i deletion role, zamknięty search_path i REVOKE PUBLIC EXECUTE/column grants. Effective privileges oraz preconditions hostile grants testuj rzeczywiście w PG/SCRAM. API bez DDL/deletion, AI bez raw diary/E8, worker bez arbitralnego naliczania na body klienta. Konto deleting nie publikuje rankingu nawet przed purge.

Nowa warstwa purge usuwa E8 projections/badges przed account delete i zachowuje cały wrapper E7→E6→E5/E4, cleanup intents/anonimową pulę AI oraz wspólny katalog. Retry nie wskrzesza konta/odznak. Historyczne świadectwo nie zależy od tombstone usuwanego przez retencję. Restore ze starszej kopii z nową epoką zachowuje E4 reconciliation i E7 gate; wyłącz publikację nieuzgodnionych pochodnych do bezpiecznego rebuild/catch-up, nie przedstawiaj potencjalnie utraconych punktów jako final. Rebuild punktów nie potwierdza aktualnej zgody: przywrócone ranking=true nie wystarcza, konto pozostaje niewidoczne do świeżej afirmacji w bieżącej epoce. Nie resetuj false/revoked, zgód lub źródłowej historii w celu otwarcia rankingu. Własna motywacja może wrócić po poprawnym rebuild niezależnie od publikacji.

## 8. Weryfikacja

Wykonaj istotny zakres unit/kontrakt/realPG17/HTTP/race/process i właściwą regresję E0–E7. Minimum:

1. Granice±10%, null/zero/pusty/ostatni posiłek/declared=false/brak celu, max2pkt, rangi19/20/59/60/119/120 i cofnięcie. Niezależne Decimal oczekiwania.
2. Cztery odznaki:9/10/11 streak/luka,4 daty wag vs4pomiarów1dnia,13/14dni różnicy,5different ration dates vs5meals1day/selected-only, alternatywny witness, history>90dni, revoke/reactivation jednej tożsamości.
3. Historia celu/correction branches, move obu dat, remove-last-item, strefa historyczna/weight-only/multi-zone, profil change bez przepisywania raw values; zgodność E5.
4. Północ bez nowego klienta, Warsaw DST/skipped local date, pending przed workerem, realne dwa procesy/worker kontra sync/opt-out/deleting/purge, restart/catch-up/rollback/lostACK bez duplikacji. Bariery i kontrolowany czas DB, nie fixed sleep jako dowód.
5. Ranking1,1,3/live opt-in/off/profile/delete i kolejne strony/replay, Unicode/duplicate pseudonyms, A/B ownership/wrong issuer/aud/token/roles/no-store oraz brak prywatnych danych w payload/errors/logs.
6. Stare snapshoty/outbox/6wire entities/receipts/sync_epoch/source rowsets niezmienione; cały source+projection savepoint rollback i rejected op niczego nie nalicza.
7. Restore privacy: opt-in true→backup→opt-out false→restore+nowa epoka→rebuild nadal niewidoczne; świeża afirmacja obecnej epoki dopiero otwiera publikację, opt-out ponownie zamyka. Stary replay i zmiana samego automatic_energy_adjustment nie odnawiają zgody. Pierwszy upgrade true bez potwierdzonej epoki również pending, nie fałszywy opt-out lub automatyczny regrant.
8. Ranking>10100uczestników, tie na granicy strony, legalne has_more/seek, opt-out anchor/purge/profilechange, cursor obcego ownera/generation/epoch/TTL i decode bez prywatnych danych; bounded quota/cleanup bez globalnego obcięcia.
9. Fresh/filled0015→0016/backfill/restart/concurrent write, invariant sum/badges, raw ACL/PUBLIC/column denials, purge chain i restore nowej epoki, downgrade atomowo, duża historia/bounded zasoby.
10. Wheel/sdist/installed-I resources, schema/OpenAPI/examples/E0/WindowsCRLF, uv.lock/Ruff/format/diff. Wymagane8CI zachowane, żadnych skips jako PASS i żadnego Gemini w CI.

Nieautor ma sam wykonać ważny nowy zakres na swoim zamrożonym source/PG/process i własne adversarial oracles. Minimum9/10, zero otwartych istotnych P1/P2. Autor nie recenzuje własnej implementacji jako niezależnej. Naprawiaj ten sam PR i odbieraj właściwy nowy zakres po zmianie head; nie sumuj powtórek.

## 9. Dostawa i koordynacja

Własny managed worktree i gałąź `codex/backend-e8-motywacja-ranking` z dokładnego source zlecenia; nie przełączaj głównego E4 lub checkoutu koordynatora. Główny wykonawca właścicielem wspólnych sync/projection hooks/purge/worker/migracji w tej grupie. Korzystaj z subagentów z reasoning dopasowanym do ryzyka i jednym właścicielem pliku. Zapisz przed implementacją decyzje i przykłady `docs/e8/DECYZJE_MOTYWACJA.md`; pokaż koordynatorowi freeze interfejsów do zależnej pracy, nie deleguj sam E8.3.

Dostawa: RAPORT_MOTYWACJA.md, RECENZJA_MOTYWACJA.md, INTEGRACJA_O1_MOTYWACJA.md, KONFIGURACJA_O3_MOTYWACJA.md w docs/e8/, pierwsze nagłówki `- osoba 2`. O1 dostaje serwer/pending/local/states/correction/privacy i cache logout; O3 role/provision/worker/schedule/startup/backfill/restore. To przekazanie, nie przypisanie ich odbioru autorowi.

Commit `agent 2: ...` lokalną tożsamością po diff/tests/review, push własnej gałęzi, jeden PR do main, finalny opis i wymagane CI dokładnego head/base. Przed końcowym push nowe main/komunikacja, zwykły merge na czystym checkoutcie, bez force-push/utraty wpisów. Jedyny dziennik KOMUNIKACJA_AGENTOW; koordynator przy dispatch poda numer wpisu, aby uniknąć kolizji.

Właściciel bezpośrednio autoryzował wykonawców nowych czatów E8 do odpowiedzi koordynatorowi `01a12156-2312-7c43-aedc-1858e782e5fb`. Zadaj rzeczywiste blokujące pytanie lub zgłoś freeze/wynik temu czatowi; cytuj bieżące ludzkie zlecenie koordynacji E8 jako źródło, nie komunikat agenta. Final + wait_threads również wystarcza. Nie dodawaj watchera/automatyzacji.

Zakończ raportem branch/head/base/PR, migracją/kompatybilnością, faktycznymi local/nieauthor/CI dowodami i ograniczeniami. Własne usługi zatrzymane. Werdykt: gotowe do odbioru koordynatora albo konkretna zależność z właścicielem i dowodem wznowienia. Nie scalaj sam PR ani nie wykonuj E8.3/4/E9; kolejną grupę zleca koordynator.
