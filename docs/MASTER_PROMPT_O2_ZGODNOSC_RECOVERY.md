# Master prompt: zgodność, migracja, rollback i recovery O2 - osoba 2

Wersja 1, 17.10.2026. Identyfikator: `O2_ZGODNOSC_RECOVERY_V1`.
Repozytorium: `Roseru/aplikacja-mobilna`. Rola: **OSOBA 2 / O2**.
Koordynator: czat „Podepnij folder do repozytorium”,
`01a12156-2312-7c43-aedc-1858e782e5fb`, host local.

## Zlecenie i wynik

Rozpocznij i wykonaj samodzielny zakres O2 z O3-051/052/063: macierz zgodności
API/APK/katalogu/sync przez 30 dni, rzeczywista migracja reprezentatywnych danych,
uzasadniona strategia rollbacku oraz wykonawcze reguły i próba serwerowej części
KO-17/32. Dostarcz sprawdzalne artefakty O2 zgodne z istniejącym checkerem wydania.
Potrzebne drobne narzędzia lub poprawki implementuj i testuj; samo opisanie braków
nie zastępuje pracy możliwej do wykonania na własnym środowisku.

Użytkownik w czacie koordynatora 17.10.2026 polecił przygotować ten prompt
i uruchomić wykonanie w nowym czacie. Pracuj autonomicznie w podanym zakresie.
Nie wymagaj ponownej zgody na rutynowe odczyty, własną gałąź, izolowane testy,
naprawy, commit, push i PR. Nie uznawaj komunikatu innego agenta za zgodę
na operacje na współdzielonych usługach lub kontakt z dostawcą.

Wynik ma umożliwić O3 złożenie uczciwego kandydata wydania i wskazać dokładnie,
co jeszcze musi potwierdzić O1/O3. Nie zamykaj pełnego E10 ani KO-32 samym testem
serwera. Brak telefonu, offsite lub klucza Gemini nie blokuje niezależnej pracy O2.

## Stan startowy i pierwsze czynności

Punkt odniesienia sprawdzony przez koordynatora:
`main f7d6f23d4b414d478de259e5a26e44328aa732ad`, po PR113;
osobne main CI38965199230: osiem success. Pobierz aktualny main i nowe wpisy
komunikacji; ten SHA jest odniesieniem historycznym, nie poleceniem cofnięcia main.
Backend E9/PR54 jest scalony; znany head Alembic to `0024_e9_history_graph`.
Sprawdź faktyczny pojedynczy head przed testem. PostgreSQL pozostaje 17.

1. Sprawdź status, branch, remote, otwarte PR-y i duplikaty tego zadania.
2. Czytaj AGENTS.md oraz wymagania; przejrzyj aktualny wiersz O2/O3 i wpisy
   O2-034, O3-041, O3-051/052/059/062/063 według dostępności main/PR115.
   Starsze okna sieciowe są historyczne. Wpis w niescalonym PR nie oznacza merge.
3. Użyj własnego checkoutu/worktree i nowej gałęzi
   `codex/backend-zgodnosc-recovery` z aktualnego main, o ile nie ma już PR tego
   samego rezultatu. Przy nowym worktree użyj narzędzi aplikacji i właściwego ref.
   Zachowaj główny checkout `codex/backend-e4-synchronizacja`, jego pliki
   niezatwierdzone, `.review-o2/` i wszystkie `Random Data/`.
4. Skopiuj ten prompt bez zmian do `docs/MASTER_PROMPT_O2_ZGODNOSC_RECOVERY.md`
   we własnym checkoutcie. Wpis startowy O2 w jedynym dzienniku określa źródło,
   branch i granicę wykonania. Ustal następny wolny numer, nie zakładaj O2-035.
5. Najpierw zrób krótką mapę istniejących dowodów i braków; nie skanuj całej
   historii ani wszystkich obcych gałęzi. Pierwszy eksperyment ma rozstrzygnąć
   największą niewiadomą: dostępność i zgodność poprzedniego obrazu albo faktyczną
   granicę zewnętrznego rejestru usunięć. Potem wykonuj kolejne kroki.

O1 ma niescaloną kolejkę PR61 → 64 → 73 → 96 → 105. Nie przenoś jej kodu do
swojej gałęzi. Ostatnie ustalenie odkłada realny APK/API na poniedziałek19.10;
godzina, osiągalny endpoint i peer wymagają nowego uzgodnienia. Nie otwieraj
relay, nie rezerwuj terminu i nie wykonuj próby telefonu za O1.
Gemini jest pominięte do prywatnego wejścia właścicieli; Google I/O pozostaje 0.

## Lektura według potrzeby

Przed projektowaniem: `WYMAGANIA_PROJEKTOWE.md` (KO-17–20/31/32, 11.3/11.6),
`docs/ARCHITEKTURA.md`, `docs/WORKFLOW.md`, aktualna komunikacja.

Do formatu dostaw i ponownego użycia narzędzi:

- `infra/integration/WYDANIE.md` i `release.py` — rzeczywisty format pięciu
  receiptów, immutable obraz, OCI revision, wspólny commit i brak autoryzacji deploy;
- `infra/integration/README.md`, `backup.py` i wyłącznie potrzebne moduły helperów;
- `docs/e8/KOPIA_ODTWORZENIE_O3.md`, `ODTWORZENIE_SESJE_I_KLIENT_O3.md`,
  `ROLLOUT_LOKALNEJ_INSTALACJI_O3.md` — istniejące capture/rehearsal i ich granice;
- `docs/integracja/ODBIOR_APK_API_O2.md` — istniejący oracle APK/DTO,
  w tym zaakceptowany dowód spóźnionej odpowiedzi; nie twórz drugiego protokołu;
- wersjonowane OpenAPI/sync/katalog oraz istniejące testy i migracje, dobierane
  po `rg` do konkretnej macierzy/próby. Nie czytaj wszystkich masterów E0–E9.

O3 ma już prawdziwe capture/verify/pg_restore obu baz/globals, kontrolę
fingerprintów, zmianę epoki, czyszczenie snapshotów, fencing AI/Nemesis,
lokalne harmonogramy i checker wydania. Nie buduj równoległego backupu,
checkerów, tablicy komunikacji lub frameworka testowego.

## Krok 1 — konkretna macierz zgodności

Opracuj czytelny dokument O2 w `docs/integracja/`, z krótkim stanem na początku
i odnośnikami do dowodów. Wyraźnie określ: `PASS` sprawdzonego zakresu,
`NOT_RUN`, `BLOCKED` i właściciela brakującego wejścia. Nie traktuj samych
deklaracji wersji z Gradle, fixtures lub raportu historycznego jako nowego odbioru.

Macierz obejmuje faktycznie wybrane commity/API/schemat, wersję sync i format
katalogu oraz konkretne wersje APK/readerów, które odczytałeś. Rozdziela main,
otwarte PR-y O1 i rzeczywisty zainstalowany artefakt. Wymień zachowanie legacy
oraz opt-in capabilities E9, null/nieznane pola, historyczne payloady i hashe
outbox, błędy epoki/generacji i ścieżkę pełnego snapshotu.

Zweryfikuj granice: checkpoint dokładnie 30 × 24h ważny, +1s wymaga pełnego
uzgodnienia bez utraty lokalnej kolejki; powrót po61dniach nie duplikuje create
ani nie wskrzesza delete. 30dni dotyczy gwarantowanej synchronizacji przyrostowej,
nie usuwania historii, pierwszego importu gościa czy zakresu wykresów/Nemesis90dni.
Wycofanie kontraktu uwzględnia ostatni wystawiony ważny checkpoint.

Wykorzystaj istniejące odpowiednie testy. Dopisz mały przypadek regresji tylko
wtedy, gdy istnieje rzeczywista luka; dla nowej krytycznej ochrony rozważ
kontrolowane naruszenie w izolowanej kopii i sprawdź, że test je wykrywa.
Nie zmieniaj semantyki v1 w celu uzyskania zielonej macierzy.

## Krok 2 — migracja, obraz i rollback na reprezentatywnych danych

Wybierz i uzasadnij rzeczywisty poprzednik: konkretny commit/immutable obraz
i `from_revision`, nie domyślne „poprzednia wersja”. Odczytaj istniejący rollout
0014→E8 i testy upgrade; sam stary raport nie jest dowodem przejścia do0024.

Na własnym PostgreSQL17 odtwórz reprezentatywne dane przez legalne wejścia:
uwierzytelnione konta A/B i payload importu lokalnego gościa do właściwego konta,
niepusty dziennik i pozycje racji, g/ml/null, wersje celów,
wagi/kompletność, katalog, receipt/idempotencja/usunięcia/checkpointy, zgody,
projekcje Nemesis oraz zadania i rezerwacje AI w mocku. Dobierz zakres do
obsługiwanej wersji, bez łamania niezmiennych triggerów lub prywatnych bypassów.
Gość jest lokalny po stronie O1; nie twórz fikcyjnego konta gościa na serwerze
ani nowego modelu backendu w celu przygotowania fixture.

Zrób prawdziwy upgrade istniejącym Alembic/migratorem do aktualnego head,
sprawdź niezależnie ustalone wartości, UUID, własność, referencje, historię,
replay i role runtime. Fingerprint sam nie zastępuje kontroli znaczenia danych.
Nie modyfikuj opublikowanych migracji0001–0024; ewentualna naprawa jest addytywna.

Zbuduj lub sprawdź właściwy obraz z czystego zatwierdzonego źródła i prawdziwym
OCI revision. Ustal `image` jako immutable imageID/digest, nie ruchomy tag.
Wybierz jedną uczciwą strategię rollbacku:

- `compatible_image`: konkretny istniejący immutable obraz działa na obecnym
  schemacie, z legalnym startupem/readiness i reprezentatywnym API/zapisami
  oraz kontrolą zachowania danych; dopiero wtedy `schema_compatible=true`;
- `restore`: jawnie opisz i przećwicz przywrócenie właściwego zestawu istniejącym
  narzędziem. Nie deklaruj zgodnego obrazu, jeśli go nie ma. Brak konkretnego
  zewnętrznego artefaktu zapisuj jako blokadę, zamiast fabrykować jego historię.

Zwykły restart/zgodny rollback obrazu nie zmienia epoki; cofnięcie bazy wymaga
nowej epoki. Nie używaj dowolnego downgrade jako sposobu rollbacku.

## Krok 3 — wykonawczy oracle i izolowana próba KO-17/32

Przygotuj powtarzalne kroki operatora O2/O3, wykorzystując istniejące entrypointy
i narzędzia. Jeśli brakuje małego adaptera/CLI lub automatycznej regresji,
dodaj je do istniejącej warstwy backendu/operatora zgodnie z jego strukturą;
nie twórz nowej usługi, ogólnego frameworka ani kopii `backup.py`/`release.py`.

Własny scratch zestaw PG17/Keycloak i syntetyczne dane muszą wykazać:

1. Kopia poprzedza przyjęty zapis i późniejsze usunięcie konta; odtworzenie
   bez uzgodnienia rzeczywiście odtwarza stary stan. Zakres dowodu obejmuje
   dziennik/posiłek, nie wyłącznie łatwiejszy pomiar wagi. Nowe poprawne dowody
   mogą uzupełniać istniejącą próbę O3 bez jej niepotrzebnego powielania.
2. Rejestr usunięć pochodzi spoza cofniętego zestawu, ma wykazane pochodzenie,
   własność i kompletność/aktualność; uzgadnia issuer/sub/account/generation
   przez istniejący begin/confirm/purge oraz prawdziwe API Keycloak.
   Brak lub sprzeczność utrzymuje zamknięty ruch. Niezależny lokalny fixture
   udowadnia próbę, nie wdrożony ciągły rejestr produkcyjny. Wskaż dokładny
   kontrakt/dostawę O3; nie traktuj dowolnego JSON jako autorytetu.
3. Przed reopen zamknięte są wszystkie writers, issuance i stare workery;
   nowy `sync_epoch` jest trwale zapisany, stare snapshoty nieaktywne, capability
   AI/Nemesis zamknięte. Bieżąca instalacja zespołu pozostaje nietknięta.
4. Rzeczywiste stare access JWT/refresh/sesje przestają działać, usunięta
   tożsamość nie wraca, świeże PKCE konta A działa. Sam logout-all nie unieważnia
   stateless access JWT. Zweryfikuj lifetime/leeway/zegary; istniejący dokument
   wskazuje dla nieznanych tokenów minimum420s po ostatnim możliwym issuance.
   Nie skracaj rzeczywistego oczekiwania zmianą zegarów lub tolerancji.
5. Stare bootstrap/checkpoint/push są odrzucane również przy nowej epoce
   nagłówka/operacji; nie resetujemy kluczy idempotencji w celu obejścia fence.
   Recovery zachowuje lokalną wersję potwierdzoną i outbox do decyzji,
   nie uznaje braku w kopii za delete i nie robi automatycznego starego push.
   Nowe świadome odtworzenie korzysta z bieżącej epoki i mapowania source→target;
   drugie urządzenie nie tworzy drugiej kopii, różna treść wymaga konfliktu.
6. Nie wraca stary opt-in rankingu/sharing ani afirmacja automatu E9.
   Po przywróceniu nie wykonują się stare zadania AI, nie odmładzamy closed_at,
   nie resetujemy zużytej/niepewnej wspólnej puli E7/E9 ani limitów użytkownika.
   Wywołania dostawcy są mockowane i mierzone: brak replay musi mieć asercję.

Runbook określa także konkretne warunki **późniejszego** ponownego otwarcia
AI/Nemesis, wyprowadzone z istniejących E7/E8/E9: wymaganą epokę i aktualne
potwierdzenia/zgody, uzgodnienie lub wygaśnięcie niepewnych okien wspólnej puli,
fencing starych workerów/zadań i brak przywrócenia starego sharing. Każdy warunek
ma właściciela oraz dowód; O2 odbiera reguły/dowody backendu, O3 wykonuje
uzgodnioną operację środowiskową, a decyzji użytkownika nie zastępuje skrypt.
Nie wymyślaj nowego automatu aktywacji i nie wykonuj reopen w tym zadaniu.

Oddziel `KO17/32 O2-server PASS` od `pełne KO32 WAITING_EXTERNAL`.
Tylko O1 może odebrać rzeczywisty Room/UI/telefon, zachowanie potwierdzonego
posiłku i niewysłanych operacji. Tylko właściwi właściciele dostarczają offsite,
produkcyjny rejestr/issuer/repliki oraz RPO/RTO. Kilka sekund scratch restore
nie oznacza produkcyjnego RTO. Nie otwieraj AI/Nemesis/produkcji po lokalnej próbie.

## Artefakty, dowody i czytelność

1. Jeden czytelny dokument macierzy oraz jeden raport/runbook O2 w istniejącym
   `docs/integracja/`, np. `ZGODNOSC_API_O2.md` i `ODBIOR_RECOVERY_O2.md`.
   Na początku krótki aktualny stan, właściciele i następny krok; historia prób
   i duże techniczne szczegóły niżej. Nie twórz drugiej tablicy komunikacji.
2. Właściwe małe skrypty/entrypointy i znaczące testy w istniejących katalogach.
   Utrwal sprawdzone komendy przygotowania, migracji i szybkiego odbioru,
   zamiast instrukcji wymagających odtworzenia prywatnego REPL.
3. Neutralne JSON `backend_acceptance`, `migration`, `rollback` zgodne z
   `release.py`: wspólny pełny `commit`; backend `image/schema_revision`;
   migracja `from_revision/to_revision/data_preserved`; rollback
   `for_revision/strategy` i warunkowe pola zgodnego obrazu.
   `result=PASS` wyłącznie dla faktycznie wykonanych zakresów.
4. Dane wydania i receipt dotyczą konkretnego **commita wykonawczego C**
   i artefaktów z C. Późniejszy commit dokumentacji D nie zmienia testowanego C.
   Nie przepisuj pola commit w starym receipt na nowy head. Dla przyszłego
   wspólnego kandydata M wymagane jest odpowiednie sprawdzenie M i świeże
   zgodne dowody. Ustal freeze źródła przed budową obrazu, aby nie gonić
   identyfikatora po każdym dopisku raportu.
5. Gotowe neutralne dostawy O3 trzymaj w uzgodnionej lokalnej paczce z hashami;
   repo zawiera kod/formaty/raporty potrzebne do odtworzenia, nie obrazy,
   backupy lub prywatną bazę. Brakujące receipt O1/restore/offsite pozostają
   brakujące. Nie osłabiaj checkera, by nadać całemu zestawowi PASS.
6. W jedynym `docs/KOMUNIKACJA_AGENTOW.md` odpowiedz O3-051/052/063:
   branch/commit/PR, wykonane próby, macierz, artefakty i konkretne brakujące
   wejścia z właścicielami. Aktualizuj własny bieżący wiersz, zachowaj cudze
   wiersze i całą historię. Nie potwierdzaj odczytu za O1/O3.

## Organizacja i proporcjonalna weryfikacja

Prowadź trzy powyższe kroki w **jednym czacie**. Utrzymuj jeden krótki checkpoint
w raporcie/privatnym stanie: źródło, aktualny krok, dowód, następna próba/blokada.
Nie twórz kolejnych native czatów, Goal ani automatyzacji. Koordynator odczyta
wynik tego czatu; raportowanie nie wymaga wysyłania mu wiadomości narzędziem.

Wykorzystaj jednego niezależnego subagenta do ograniczonej oceny macierzy,
runbooka i krytycznych nowych narzędzi/testów. Dodatkowego użyj tylko wtedy,
gdy niezależny zakres rzeczywiście skraca pracę. Ustawienia modeli pozostaw
zgodne z aktualnymi instrukcjami środowiska; nie zakładaj, że subagent może
zmieniać model/reasoning w pełnym fork. Nie zlecaj wielu agentom tej samej macierzy.

Najpierw największa niewiadoma i affected tests; potem pełna właściwa regresja
raz dla ustalonego kodu. Nie uruchamiaj całego PG/Keycloak/Android dla każdej
redakcji dokumentacji. Nie powtarzaj całego zbioru po sukcesie bez nowej zmiany
lub nierozstrzygniętego ryzyka. Istotny błąd zachowaj jako mały przypadek regresji.
Reprodukcja → hipoteza → dowód → jedna zmiana → ta sama próba; historycznych RED
nie usuwaj, a zmiany harnessu oddzielaj od błędu produktu.

Jeśli zmienisz backend/operatora: E0, Ruff/format i właściwe testy unit/PG/realnego
Keycloak/HTTPS; migracja oraz rollback/restore muszą wykonać się naprawdę.
Jeśli zmiana jest wyłącznie dokumentacyjna, sprawdź spójność/linki/diff, a istniejące
dowody wyraźnie przypisz do ich źródeł. Fixture serwera nie jest testem telefonu.
Nie buduj Androida za O1 ani nie uruchamiaj rzeczywistego Google do tej pracy.

## Bezpieczeństwo środowiska i Git

Próby wyłącznie na własnych jawnie oznaczonych scratch bazach, realmach,
portach i kontenerach. Nie korzystaj z prywatnego stanu zespołu bez konkretnego
uzgodnienia O3, nie zmieniaj istniejących kont/issuer/CA/epoki, backup tasków,
Docker Desktop, firewall/trust, działających usług lub globalnych zależności.
Nie odczytuj prywatnych sekretów zespołu, jego Room/WAL, tokenów, identity lub
deletion ledger bez konkretnego upoważnienia właściciela. Własne syntetyczne
credentials, JWT/refresh, identity i ledger na izolowanym środowisku wolno
wytworzyć i prywatnie wykorzystać do wymaganych prób; nie publikuj ich wartości
w repo, PR lub czacie ani nie wypisuj tokenów/credentials w logach.
Dowody publiczne zawierają wyłącznie neutralne wyniki.
Reguły danych z Random Data zachowaj.

Commity: `agent 2: <konkretny wynik>`, ustalona lokalna tożsamość wyłącznie dla
swojego checkoutu/commita. Review jest opcjonalne, lecz niezależny przegląd
wymagany tym zadaniem ma osiągnąć co najmniej9/10, bez otwartych P1/P2.
Istotne uwagi popraw i ponownie sprawdź zmieniony zakres.

Publikuj jeden spójny wynik na własnej gałęzi: diff-check → commit/push → PR.
Master może wejść w pierwszy commit tego samego zadania; nie otwieraj osobnego
PR i pełnej macierzy CI dla samego przygotowania promptu. Niezależny refaktor
lub migracja zależności (np.SQLAlchemy2.1) nie należy do tego rezultatu.
Bez force-push, rebase wspólnej historii, merge cudzych nieodebranych gałęzi
lub bezpośrednich zmian main. Dołączaj main zwykłym merge z czystego checkoutu.

Po utworzeniu PR dołącz go do czatu przez attach_artifact. Odbierz wymagane
osiem kontroli dokładnego finalnego head/base — obecny workflow obejmuje
je także dla docs. Nie wyłączaj/pomijaj testów i nie utożsamiaj lokalnego PASS
ze zdalnym CI. Czekając, używaj zwartych statusów z odpowiednimi odstępami,
bez ponownego czytania całej historii albo ponawiania testów aplikacji.

Zakończ na **gotowym PR do niezależnego odbioru koordynatora**, z opisem
problemu/wyniku, kompatybilności, testów i ograniczeń. Koordynator wykona
osobny odbiór i decyzję merge; nie pytaj człowieka o zgodę na każdy krok.
Pełne zewnętrzne bramki nie mogą zatrzymać publikacji odebranego zakresu O2.

## Definition of Done i raport końcowy

- Macierz obejmuje konkretne wersje i wszystkie wymagane granice; stany
  niewykonane i zakres starych dowodów są jawne.
- Migracja i wskazana strategia powrotu mają rzeczywiste dowody zachowania
  danych i zgodny zestaw C/image/schema, albo konkretną blokadę z właścicielem.
- Serwerowy oracle KO17/32 ma powtarzalną próbę i reguły fail-closed;
  istniejące narzędzia wykorzystano bez duplikacji. Pełny KO32 nadal wymaga O1/O3.
- Runbook podaje warunki, właścicieli i wymagane dowody późniejszego reopen
  AI/Nemesis według bieżących reguł; niczego nie otwarto w ramach tej pracy.
- Neutralne dostawy O3 odpowiadają schematowi release.py; nie dopisano fikcyjnych
  PASS, nie naruszono historii/30dni, nie uruchomiono Google lub współdzielonych usług.
- Niezależna ocena >=9/10, brak otwartych istotnych usterek, właściwe lokalne
  i zdalne kontrole, wypchnięty PR oraz odpowiedź w jedynym dzienniku.

Raport w tym czacie ma być krótki: rezultat i granice, branch/head/PR, źródło
artefaktów i dowodów, wyniki testów/CI, ocena recenzenta, konkretne działania
O1/O2/O3. Jeśli pozostała rzeczywista zależność, podaj `WAITING_EXTERNAL`,
właściciela i warunek wznowienia; nie deklaruj ukończenia całego projektu.
