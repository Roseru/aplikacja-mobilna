# Niezależny ograniczony przegląd zgód rankingu i styku E9 - osoba 2

**Aktualizacja 25.10.2026:** [przegląd klienta E9](#przegląd-e9--25102026)
potwierdza naprawę historycznego P2 na poziomie przypiętych źródeł O1.
Pełny E9 nadal wymaga synchronizacji i rzeczywistego odbioru APK/API.
Poniższy pierwotny raport z 13.10 zachowuje swój historyczny zakres.

Data: 13.10.2026. Zakres: PR50 na wskazanym main; read-only styk nieodebranego PR54/E9. Raport nie jest odbiorem całego E9 ani rzeczywistej integracji APK/API.

**Ocena PR50 na obecnym main: 9,3/10; brak znalezionych P1/P2 w jego działającym kontrakcie. Integracja z E9 wymaga zamknięcia poniższego P2 po stronie komunikatu/statusu klienta.**

## Źródła i metoda

- Main: `2fc70f7ae612c031f63d53c04d3c81b4402b72c5` (PR50 już scalony według zlecenia). Własny checkout odczytu, gałąź `codex/docs-o2-przygotowanie-odbioru`. Bez fetch, przełączenia, merge lub modyfikacji Git.
- Dostępny lokalny ref `origin/codex/backend-e9-korekta-zapotrzebowania`: `0c81fb7428bae783d7202e03dec1e1ab876f85cc`. Wnioski o E9 dotyczą wyłącznie tego SHA, nie późniejszego final-head.
- Przeczytano wymagania 11.2/11.5, O1-023 z dopiskami i bieżące przekazania O3. Odczytano RankingConsentProtocol/Screen, ProfileReadProtocol, BootstrapGateway, SessionVault, SessionController, oba testy JVM zgód, RankingConsentScreenTest, scenariusze zgód SessionSecurityTest oraz PUT backendu i testy E8.
- Porównano 14 odczytanych plików z obiektami wskazanego main po normalizacji CRLF/LF: zgodne. Manifest `consents-source-manifest.json` zapisuje blob SHA. `profiles/service.py` ma ten sam blob na main i E9: `f000f7c6cf6db517654d33f851a9882578e3ce6e`; DTO i router PUT również nie mają diff w E9.
- Odczyt E9 ograniczono do energy DTO/router, afirmacji, resetu zgód, baseline/state/generation oraz instrukcji `docs/e9/INTEGRACJA_O1.md`. Nie przeglądano ani nie testowano całego worker/rules/retention E9. `git status` w udostępnionym checkoutcie zgłaszał błąd dostępu/worktree; nie deklaruję jego czystości. Sprawdzenie konkretnych źródeł wykonano niezależnie przez porównanie z Git.

## Wynik review obecnego kontraktu

1. **Świadoma decyzja i energia:** GET profilu + motywacji nie zapisuje zgody; świeży source nonce, maksymalnie 300 s, ranking requested i bieżąca epoka muszą się zgadzać. Checkbox zaczyna od false i resetuje się dla nowego source. PUT zachowuje odczytany `automatic_energy_adjustment` dla obu boolów; konkurencyjny zapis wymaga rozstrzygnięcia If-Match, więc nie nadpisuje energii na podstawie starego odczytu.
2. **Idempotencja i receipt:** przed siecią pełny attempt trafia do AES-GCM/AtomicFile/noBackup i jest odczytywany kontrolnie. Jawny retry zachowuje key, body, bazową rewizję i epoch; opt-in wysyła `X-Ranking-Consent-Epoch`, opt-out go pomija. Redirect nie ponawia PUT. ACK wymaga dokładnie `baseRevision+1`, obu oczekiwanych boolów i cytowanego ETag. Brak/niepoprawny receipt zachowuje intent; 409/400/422 usuwa go i wymaga nowego odczytu/decyzji.
3. **Własność i odpowiedzi:** fences obejmują lease, operację, API session, account ID/generation, sync epoch i context revision przed wysłaniem i zastosowaniem wyniku. Logout usuwa vault; A→B→A ma nową lease. Cancel zachowuje decyzję bez automatycznego wysłania; ręczny refresh unieważnia późny ACK. Observer Room usuwa prywatny profil/zgody po zmianie kontekstu. Backend wiąże owner z tokenem, blokuje konto/counter i sprawdza kontekst receipt przed replay; replay nie afirmuje ponownie rankingu.
4. **Restore/off→on:** E8 nie publikował starego true bez nowej afirmacji bieżącej epoki; dawny receipt nie przywraca odwołanej publikacji. Istnieją małe regresje PG dotyczące tych przypadków, body/header mismatch, duplicate epoch i atomowości odmowy. To odczyt testów, nie własny PG PASS.

## P2 do O1 przed integracją E9: komunikat myli zgodę z aktywnym automatem

**Źródła:** main `RankingConsentScreen.kt:68–69`; E9 `backend/migrations/versions/e9_0022/maintenance.sql:1–9`, `history.sql:139–158`, instrukcja `docs/e9/INTEGRACJA_O1.md`, sekcja „Automat”.

**Reprodukcja wyprowadzona z kodu:** konto ma `automatic_energy_adjustment=true`, aktualną afirmację/baseline/notice i effective=true. Użytkownik na ekranie rankingu widzi „Automatyczna korekta zapotrzebowania pozostanie włączona” i potwierdza udział lub opt-out. Nowy PUT zwiększa wspólną revision, trigger E9 usuwa baseline i notice, boolean pozostaje true, lecz `automatic_effective=false`. Stary klient nie czyta energy/state i nie potrafi ponownie afirmować energii. Każde późniejsze potwierdzenie rankingu może więc zatrzymać automat przy obietnicy jego zachowania.

To **celowa polityka backendu**, jawnie opisana w przekazaniu E9; nie wskazuję jej jako nieautoryzowanego resetu ani nie żądam osłabienia off→on/restore. Jest jednak konkretnym wymaganiem zgodności UI przed odbiorem E9. O1 powinien zastąpić obietnicę aktywności informacją o zachowaniu samej zapisanej zgody oraz wymaganiu osobnej afirmacji; klient obsługujący E9 powinien po PUT odczytać energy/state i pokazać requested/effective. Nie afirmować energii automatycznie po kliknięciu rankingu. Dodać regresję: effective=true → rank-only PUT przy energy=true → requested=true/effective=false → osobny notice/affirm, oraz identyczny replay PUT bez drugiego resetu. Analogicznie jawnie obsłużyć rank opt-out, restore i energy off→on. Brak E9 na main oznacza, że uwaga nie unieważnia obecnego odbioru PR50.

## Własne testy i ich skuteczność

Snapshot z `git archive` wskazanego main w prywatnym `consents-main-snapshot`; odrębny basetemp, bez cache/pyc w repo. Python 3.13.9, pytest 9.1.1 z istniejącego środowiska, bez instalacji i bez usług.

```text
python -m pytest -q -p no:cacheprovider tests/unit/test_e8_consent.py tests/unit/test_e3_profiles.py -k "consent or if_match or headers_canonical" --basetemp <własny katalog> --junitxml <własny plik>
28 passed, 45 deselected in 1.48s; exit 0
```

Środowisko: `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=<snapshot>/backend/src`, cwd `<snapshot>/backend`. Dowody: `consents-unit.log`, `consents-unit.xml`. Interpreter drukuje ostrzeżenie o real location, ale uruchamia Python/pytest i zwraca exit 0; nie potraktowano ostrzeżenia jako PASS testów.

Eksperyment odwracalny tylko w tej kopii: usunięcie epoch z `consent_request_hash`; istniejący `test_header_presence_and_epoch_change_are_distinct_semantics` wykrył błąd `assert 1 == 3` (1 expected FAIL). Oryginalne bajty przywrócono w finally i sprawdzono ich równość. Dowody `consents-mutation.log/xml`. Pierwsze przygotowanie eksperymentu zatrzymał guard dopasowania CRLF przed jakąkolwiek mutacją; po normalizacji przeprowadzono właściwą próbę. Nie sumujemy mutation FAIL z normalnymi PASS.

## Ograniczenia i następny odbiór

Nie uruchomiono Android JVM/build/emulatora, PG ani rzeczywistego HTTPS/OIDC/APK. Wcześniejsze O1/O3 i CI to cudze, oddzielne dowody. Fake HttpsURLConnection/Session fixtures nie dowodzą TLS, osiągalności telefonu lub PKCE. Nie wykonano full E9 ani aktualnego GitHub CI review; nie zmieniono kodu, journalu ani publicznej dokumentacji i nie wysłano wiadomości do innych czatów.

Pierwszy test integracyjny O1 po uzyskaniu stabilnego origin/issuer/trust O3: prawdziwe A/PKCE/bootstrap, GET/me+motivation bez mutacji, świadomy opt-in/opt-out z zachowaniem obu wartości energy; lost ACK/restart exact retry, logout/A→B→A i spóźniona odpowiedź. Po E9 dodać powyższy krótki przepływ energy/state→rank PUT→osobne notice/affirm oraz kontrolę niezmienionego celu/dziennika/outbox. Zapisać dokładny APK SHA, backend SHA, epokę i wynik; zachować mały powtarzalny przypadek regresji. Pełny odbiór E9 pozostaje osobnym zadaniem.

Uwagi przekazano [O1 w PR50](https://github.com/Roseru/aplikacja-mobilna/pull/50#issuecomment-6147962277) oraz aktywnemu wykonawcy E9. Odbiorcy sami potwierdzają odczyt; wykrytego P2 integracyjnego nie oznaczono jako naprawionego. [Pierwszy rzeczywisty scenariusz](ODBIOR_APK_API_O2.md) ma oddzielny odbiór.


## Niezależny odbiór pakietu przygotowania

Drugi zakres tego samego recenzenta,13.10.2026:9,3/10,brak nowych P1/P2 w pakiecie. Nie ponawiał audytu PR50/E9 lub runtime. Potwierdził30 plików i unikalnych source IDs/hashów,8/8/10/4,10 558 270B,16 dokładnych Nutrition5k records i primary Commons provenance. Zatwierdzenia/zgody/uploady0 oraz brak prywatnych ścieżek/sekretów są jawne. Galeria ma te same30 plików;60 lokalnych celów Markdown istnieje. Zmienił się wyłącznie własny wiersz O2,dopiski zachowują cudzą historię. Dwie opcjonalne P3 — puste linki Public domain i nieoznaczony historyczny inventory/checklista — poprawiono tekstowo. Istniejący P2 integracyjny E9 nadal otwarty.

Koordynator wykonał istniejący E0:9schemas/95valid/35invalid/18scenarios/561links oraz diff-check PASS. Walidator nie wykonuje PG/Room/OIDC/deployment. Hashe/rozmiary obrazów sprawdzono niezależnie przy składaniu pakietu; kwalifikacja człowieka i rzeczywisty runner pozostają osobno. Publikacja ma własne wymagane final-head CI; przygotowanie nie jest pełnym APK/E7-R/E9 PASS.

## Przegląd E9 — 25.10.2026

Ograniczony przegląd zgodności komponentu O1 z API: **nie wykazano nowego
materialnego P1/P2 w prześledzonym REST/UI; historyczny P2 requested/effective
jest naprawiony w źródłach. Pełny E9: HOLD.** Niezależny odbiór raportu po
korektach: **9,3/10**, bez istotnych nierozwiązanych uwag do publikacji.
Nie jest to ogólny audyt bezpieczeństwa ani odbiór live.

### Piny i rzeczywisty zakres dowodów

- Backend: `00dae4aa1e89fcc9de8ac24b2391daa1f6d06707`,
  tree `b1d4c99fe6289bf7a69829d5863997bf621fb66d`.
  Android: dostawa `e16f317f75379ced9ac1d8e2241fdffaab9316f3`,
  code `50eb470c25a76dbd523cb722838b5369117764c7`,
  android/app tree `d1f5d621f4aadf5560e5c46c11fbf9f574953183`.
  Oba piny Androida mają identyczne drzewo aplikacji; różnią się dokumentacją.
- Źródła czytano z Git blobs, bez cudzego working tree. Niezależnie sprawdzono
  manifest 73/73 plików: blob, SHA-256 i rozmiar. Nie zmieniono produktu.
- Wykonano **14/14 oczekiwanych wyników DTO**: 5 fixture O1 i 5 ręcznie
  odtworzonych kształtów requestów przyjętych przez rzeczywiste modele
  Pydantic oraz 4 negatywne granice odrzucone. To nie wykonanie builderów
  Kotlin, routera, SQL lub transportu. Istniejący test schematu: **1 PASS**.
- Kopia schematu O1 jest semantycznie zgodna z aktualnym schematem backendu.
  Poprawiony analizator zbadał 148 wzorców inline: 17 osiągalnych przez REST,
  0 problematycznych w REST; wszystkie 78 problematycznych wystąpień leży
  pod `EnergyPullResponse`. Samo sprawdzenie nazwy `$ref/UnicodeText` nie
  wystarczało, ponieważ wygenerowany schemat zawiera ten wzorzec inline.
  Korekta metody nie wymagała nowych testów produktu. V1 raportu zachowano.
- Nie wykonywano JVM/Gradle/Room/AVD/PG, realnego APK/API, OAuth lub Gemini.
  Sześć przypadków instrumentacji O1 to cudzy, osobny wynik na code50eb470,
  opisany w [jego raporcie](https://github.com/Roseru/aplikacja-mobilna/blob/e16f317f75379ced9ac1d8e2241fdffaab9316f3/android/KOREKTY_ZAPOTRZEBOWANIA.md).

### Rozstrzygnięcie zgód i zgodności REST

Historyczny komunikat obiecujący zachowanie aktywnego automatu zastąpiono
informacją o zachowaniu deklaracji i konieczności osobnego potwierdzenia
([RankingConsentScreen:68](https://github.com/Roseru/aplikacja-mobilna/blob/e16f317f75379ced9ac1d8e2241fdffaab9316f3/android/app/src/main/java/pl/roseru/kalorie/ui/RankingConsentScreen.kt#L68)).
Klient rozdziela requested/effective, traktuje cache jako ostatni podgląd,
blokuje effective przy niepewnej zmianie zgód i zachowuje trwały nonce.
Compare-and-clear nie pozwala spóźnionemu GET skasować nowszego znacznika
lub znacznika aktywnej mutacji
([EnergyRepository:98](https://github.com/Roseru/aplikacja-mobilna/blob/e16f317f75379ced9ac1d8e2241fdffaab9316f3/android/app/src/main/java/pl/roseru/kalorie/energy/EnergyRepository.kt#L98)).
Odtworzenie pending zgody i guards lease/binding/session są uwzględnione
w analizie źródłowej. Nie jest to wykonany realny scenariusz po restarcie.

Nowy PUT zgód unieważnia afirmację i baseline zgodnie z polityką backendu;
identyczny replay wraca z receipt przed kolejnym zapisem revision.
Nie dodano automatycznej afirmacji po odczycie lub zmianie rankingu.
Prześledzono ścieżki REST, null/Decimal/paginację, zamrożone UUID/body/If-Match,
kontekst konta i niezmienną historię E. Accept/revert zmienia E, nie cel
kcal/B/T/W, klasę ani wcześniejszy dziennik.

Expiry propozycji odnosi się do gotowego wyniku: backend ustawia `created_at`
przy zakończeniu generacji i `expires_at` o 24 h później
([worker.sql:118,134–135](https://github.com/Roseru/aplikacja-mobilna/blob/00dae4aa1e89fcc9de8ac24b2391daa1f6d06707/backend/migrations/versions/e9_0022/worker.sql#L118)).
To osobny czas od admission `accepted_at`. Klient sprawdza relację dat
i używa `expiresAt` do dopuszczenia accept
([EnergyProtocol:39](https://github.com/Roseru/aplikacja-mobilna/blob/e16f317f75379ced9ac1d8e2241fdffaab9316f3/android/app/src/main/java/pl/roseru/kalorie/energy/EnergyProtocol.kt#L39)).

### P3 ETag przy potwierdzeniu energy consent — poprawka O2

Stan początkowego przeglądu, na pinie `e16f317f`:

Nowy [EnergyGateway](https://github.com/Roseru/aplikacja-mobilna/blob/e16f317f75379ced9ac1d8e2241fdffaab9316f3/android/app/src/main/java/pl/roseru/kalorie/energy/EnergyGateway.kt#L15)
nie przenosi ETag odpowiedzi. ACK sprawdza status 200, oba booleany i
`revision = If-Match + 1`, lecz pomija zgodność cytowanego ETag
([EnergyRepository:256](https://github.com/Roseru/aplikacja-mobilna/blob/e16f317f75379ced9ac1d8e2241fdffaab9316f3/android/app/src/main/java/pl/roseru/kalorie/energy/EnergyRepository.kt#L256)).
Poprawna odpowiedź przypiętego backendu jest kompatybilna. Źródłowy
kontrprzypadek to 200 z poprawnym body, ale bez ETag lub z innym ETag:
operacja zostaje uznana za zakończoną. Nie wykonano tej próby na Androidzie.

O1 powinien przenieść i sprawdzić ETag przed zakończeniem próby oraz zachować
ten sam UUID/body przy brakującym lub błędnym nagłówku. To drobne uzupełnienie
walidacji odpowiedzi dla E9, nie nowy blocker bieżącego odbioru Room23.

**Aktualizacja 25.10.2026: poprawka wykonana i odebrana lokalnie.** O1
[delegował ją O2](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6398843748).
Wypchnięty [commit `4cc2d4db43b5022244772e43313d63e45a7c9b9c`](https://github.com/Roseru/aplikacja-mobilna/commit/4cc2d4db43b5022244772e43313d63e45a7c9b9c)
na `codex/android-o2-etag-energia` ma dokładnie rodzica `e16f317f` i cztery
dozwolone pliki: EnergyGateway, ACK consent w EnergyRepository,
EnergyTransportTest i nowy EnergyConsentReceiptTest. Pozostałe źródła,
fixture i pięć JSON, Room/migracje oraz konfiguracja buildu są zachowane.

Transport przenosi surowy opcjonalny nagłówek. Przed zakończeniem próby
repozytorium wymaga silnego cytowanego ETag zgodnego z body revision;
zachowuje kontrolę statusu 200, obu boolów i `If-Match + 1`. Brakujący,
błędny, weak, niecytowany, niekanoniczny, padded lub wielokrotny ETag
pozostawia trwałe `unknown`. Zamknięcie/otwarcie rzeczywistego Room i jawny
poprawny retry zachowują UUID/body/fingerprint/If-Match tej samej operacji.
Nie powstaje automatyczna afirmacja lub nowa zgoda.

Wykonano **13 unikalnych testów urządzeniowych PASS: 11 receipt + 2 transport,
0 failure/error/skip**, na osobnym pakiecie i AVD API35 offline. Build app/test
validation, compileDebugKotlin i lint PASS; lint: 0 błędów, 8 ostrzeżeń,
2 informacje poza zmienionymi plikami. Niezależny przegląd źródeł i surowych
XML/logów: **9,5/10, brak materialnych P1/P2**. Root porównał cztery bloby
finalnego commita z recenzowanym i testowanym manifestem oraz zdalnym pinem.
To lokalny odbiór komponentu z syntetyczną granicą API/sesji; bez dowodu
TLS/live API, zdalnego CI lub pełnego E9. Rezerwacja czterech plików wraca
do O1, który włączy deltę do swojego dużego E9. Osobny carrier runtime/Room23
nie zawiera tej zmiany Room25; nie utworzono checkpoint-PR.

### Synchronizacja, własność i następny odbiór

Opublikowany klient nadal obsługuje poprzednie sześć typów sync. Nie ma
projekcji `energy_estimate` ani opt-in `energy_estimates_v1`; ten stan
jest jawnie opisany przez O1. Przed włączeniem nowego zakresu wymagane są
walidacja/projekcja encji, zgodne push i pull oraz pełny snapshot z nowymi
podpisanymi tokenami. Dopisanie nagłówka do starego tokenu nie wystarcza.
Outbox, frozen bytes, UUID i odzyskiwane operacje muszą pozostać zachowane.
Przed użyciem `EnergyPullResponse` potrzebna jest iteracyjna walidacja znaków
i regresja długich tokenów, w tym 4096 znaków. To znana blokada przyszłego
sync, nie wykazany aktualny trigger REST.

Runtime O2 `325446b0` został już dostarczony i odebrany. O1
[potwierdził jego przyjęcie wraz z lifecycle Factory](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6398434885)
i rozpoczął integrację carrier11fac87a z osobnym driverem Room23.
Jego [nowsze przekazanie](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6398540989)
wymaga potwierdzenia publicznego API/issuer/CA przez O3 przed dostawą czterech
APK. [Opublikowana integracja Room23](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6399203852)
ma source `eacc8f19` i receipt `2319357d`: O1 raportuje build/lint/JVM PASS
oraz 7 native z wynikiem 6 PASS/1 FAIL, a po poprawieniu fixture osobny
1 PASS. Nie opisujemy tego jako jednego przebiegu 7/7. Cztery skonfigurowane
APK, android_acceptance, remote CI i live pozostają osobnym odbiorem O1/O3.
Nowa encja, walidator i gateway E9 są zakresem O1; ewentualne zmiany
`SyncWork/SyncCoordinator` wymagają uzgodnienia styku O2. Ten przegląd
nie przydziela tych plików ponownie. Nie obejmuje też nieopublikowanego
szkicu opt-in O1, oddzielonego od aktualnego odbioru Room23.

Realny E9/Room25 wymaga własnego zgodnego zestawu APK, kontraktu i kwalifikacji;
zamrożony driver Room23 ich nie zastępuje. Po uzgodnieniu wersji kolejny
wspólny scenariusz to PKCE/bootstrap → state/history → rank-only PUT przy
aktywnym automacie → requested=true/effective=false → osobny notice/affirm
→ lost ACK/restart/exact retry → A→B→A i późna odpowiedź, a następnie nowy
scope snapshot z zachowanym outboxem. O1 dostarcza integrację/APK, O3
konfigurację i odbiór środowiska, O2 sprawdza zgodność handshake/replay.
Wynik musi wiązać konkretne APK/backend SHA i epokę.
