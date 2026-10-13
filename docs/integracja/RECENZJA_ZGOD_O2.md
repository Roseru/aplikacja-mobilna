# Niezależny ograniczony przegląd zgód rankingu i styku E9 - osoba 2

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
