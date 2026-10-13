# Pierwszy odbiór APK → PKCE → bootstrap → prywatne odczyty - osoba 2

Przygotowanie O2, 13.10.2026. Źródła odczytane z main `2fc70f7ae612c031f63d53c04d3c81b4402b72c5` w osobnym checkoutcie koordynatora. Odrębny zakres od aktywnego E9/PR54; bez zmian kodu, journalu, kont lub środowiska. Status: **PREPARED / WAITING_EXTERNAL**, bez realnego APK PASS.

## Krótki stan i największa niewiadoma

- O1-023 określa pierwszy przebieg: APK, rzeczywiste konto A/Chrome/PKCE, bootstrap, GET me/motivation, potem logout/restart i B→A. Same odczyty nie potwierdzają zgody ani nie synchronizują dziennika.
- O3 `docs/e8/ROLLOUT_LOKALNEJ_INSTALACJI_O3.md`: zachowany origin `https://192.168.3.162:18443`, issuer z końcówką `/realms/calorie-dev`; gateway związany z `127.0.0.1:18443`. Historyczny operatorski HTTPS/PKCE/200 nie jest dostępem telefonu. `infra/integration/ANDROID_PKCE.md` dotyczy starszego APK 0.8.0 bez bootstrap/API; nie zalicza tego scenariusza.
- Wczesny mały eksperyment: telefon musi otworzyć discovery pod **dokładnym issuer** z poprawnym TLS, bez ostrzeżenia Chrome, i osiągnąć readiness API. Dopiero wtedy wykonać poniższy przebieg. Pozwala oddzielić routing/trust od kontraktu i Room.
- Bieżąca próba O2, 13.10.2026 około 16:24 CEST: `ipconfig` nie pokazał przypisanego `192.168.3.162`; Wi-Fi disconnected. Próby .NET TCP do `127.0.0.1:18443` i `192.168.3.162:18443`, każda z limitem2500ms, zakończyły się `SocketException / AccessDenied`. CIM `Get-NetIPAddress` także odmówił dostępu. **To ograniczenie wykonania lokalnej próby, nie connection-refused, timeout serwera ani dowód niedostępności portu.** Nie wykonano HTTPS, discovery, PKCE lub uwierzytelnionego GET. Nie eskalowano, nie zmieniano trust/sieci/usług.

Dodatkowy preflight koordynatora po dopuszczeniu odczytu sieci: TCP `127.0.0.1:18443` zwrócił `ConnectionRefused`; `192.168.3.162:18443` osiągnął timeout po 2500 ms. Odczyt przypisanych adresów potwierdził `historicalOriginAssigned=false`. To faktyczny wynik tej próby, odrębny od wcześniejszego sandboxowego AccessDenied. Nie potwierdzono HTTPS/discovery, gotowości całego środowiska ani APK; nie zmieniano usług. [Przekazanie O3](https://github.com/Roseru/aplikacja-mobilna/pull/51#issuecomment-6147961766) prosi o gotowy wariant origin/issuer/CA i stan istniejącej instalacji.

## Bramka środowiska i istniejące komendy

O3 dostarcza aktualny origin/issuer/publiczny CA oraz osiągalność z telefonu i zgodność deploymentu. Nie zmieniać jednostronnie issuer na loopback/10.0.2.2 lub nowy LAN IP; `(issuer, sub)` to tożsamość. Przy nowym issuer potrzebny odrębny uzgodniony plan. Nie stosować reinit, resetu kont, trust-all, cleartext ani obchodzenia ostrzeżeń TLS.

O1 potwierdza SHA256, commit, applicationId i faktyczne resources APK. `CALORIE_API_BASE_URL` musi mieć ścieżkę `/api/v1` lub `/api/v1/`; sam origin zostanie odrzucony przez `BootstrapHttpProtocol.endpoint`. Domyślne obie właściwości Gradle są puste, więc sam install-r APK5234edb nie dowodzi konfiguracji API. Room8/version0.8.7/code18 to odczyt źródeł main; bieżący artefakt wybiera O1.

Po wskazaniu **istniejącego** prywatnego stanu przez O3, z właściwego checkoutu O3:

```powershell
uv run --project backend --locked python infra/integration/run.py status --state "$ExistingState"
uv run --project backend --locked python infra/integration/run_e8.py status --state "$ExistingState"
```

To status operatora, nie receipt telefonu. `run.py verify` nie jest read-only preflight: wykonuje bootstrap i inne scenariusze mutujące. Nie uruchamiać go na współdzielonych kontach jako zamiennika odbioru APK. `android_scope.py` przypisuje scope administracyjnie; także nie jest read-only i pozostaje u O3.

Jeżeli O3/O1 wybierają istniejący wariant validation z lokalnym publicznym CA, wykorzystują dotychczasowy overlay zamiast nowego harnessu. Przygotowanie **nowego, nieistniejącego** katalogu overlay i build wykonują właściwi właściciele:

```powershell
uv run --project backend --locked python infra/integration/android_overlay.py --state "$ExistingState" --output "$NewOverlay"
# W android/ checkoutu odebranego commita O1; wartości publiczne od O3:
.\gradlew.bat :app:assembleValidation --init-script "$NewOverlay/init.gradle" "-PCALORIE_OIDC_ISSUER=$ApprovedIssuer" "-PCALORIE_API_BASE_URL=$ApprovedOrigin/api/v1"
Get-FileHash -Algorithm SHA256 .\app\build\outputs\apk\validation\app-validation.apk
```

Nie wykonywano tych komend w tym zadaniu. Validation to inne applicationId/dane niż zwykły APK; odbioru validation nie podpisywać jako zachowania istniejącego dziennika regularnego APK. APK ufa ograniczonemu publicznemu CA dla dokładnego hosta, Chrome ma osobny trust. Zaufanie urządzenia uzgadniają O1/O3; brak publicznego CA nie oznacza prawa do jego instalacji lub zmiany w tym podtasku.

## Minimalny przebieg i oracle O2

1. O1 zapisuje prywatny baseline gościa/A/B oraz zainstalowanego artefaktu: aktywny owner, dziennik/składniki, profile, cel i jego historię, wagi, kompletność, outbox; kopia Room razem z WAL, nie sam niepełny plik SQLite. Brak clear/uninstall. Snapshot po bootstrapie stanowi baseline dla kolejnych odczytów; bootstrap może legalnie utworzyć serwerowe konto/receipt.
2. Rzeczywisty login A przez Chrome: publiczny `calorie-android`, `openid profile`, Code+PKCE S256, state/nonce i dokładny callback applicationId (`pl.roseru.kalorie:/oauth2redirect` albo validation). Discovery/JWT/API mają zgodny issuer, token audience `calorie-api`; bez client secret w APK.
3. APK wysyła `POST /api/v1/me/bootstrap`, Bearer oraz `Idempotency-Key` kanoniczny UUID; **bez body**. Oczekiwane200 `Bootstrap`: `account_id`, `sync_epoch`, `account_generation` dodatnia revision, `server_time`. Replay tego samego key zachowuje pierwotny receipt/czas, nie tworzy drugiego konta; nie wymuszać replay przez ręczne zmiany bazy/Vault. Tożsamość pochodzi z tokenu.
4. APK `GET /api/v1/me`:200 `ProfileRead`: te same `account_id`, `sync_epoch`; `profile` może być null; `consents` ma booleany ranking/automatic_energy_adjustment, dodatnią revision i updated_at; goal_timeline_revision może być0. ProfileRead nie zawiera account_generation. Nie wymagać ETag GET jako oracle zgód: ETag ustawia PUT.
5. APK `GET /api/v1/me/motivation` bez query:200 `MotivationRead`, zgodne `account_generation`/`sync_epoch`; regularity_v1, revision/source_position to 64-bit county, status pending_backfill/pending_materialization/final, cztery odznaki. Pending/null nie prezentować jako finalnych0pkt. `ranking.requested/effective/pending_consent_refresh/consent_epoch/own_position` zachować zgodnie z DTO. Dla konta z ranking=false pozostaje brak implicit opt-in; istniejącego ranking=true nie resetować dla testu.
6. Oba GET i API errors mają `Cache-Control: no-store` oraz `X-Request-ID`. Porównać pełny baseline Room po bootstrapie z po obu GET: dziennik, cel/historia i outbox niezmienione. Zmiana materiału/projekcji serwera lub czasu motywacji nie oznacza zmiany lokalnego dziennika. Nie powinno być PUT zgód ani operacji import/push z samego loginu/odczytu.
7. Logout A, restart aplikacji; zalogowanie B, następnie A. Nie widać A ani jego prywatnego profilu/motywacji/cursorów w B/gościu; B używa własnego bootstrap identity. Wszystkie zapisane zbiory każdego ownera pozostają jego zbiorami, gość bez automatycznego importu. Po powrocie A świeży GET, nie reaktywacja starego cache.
8. Spóźniona odpowiedź A po logout/przełączeniu: O1 używa własnej odebranej techniki kontrolowanego opóźnienia w osobnym środowisku; O3 odpowiada za transport. Jeśli nie dostarczono realnej odpowiedzi po zmianie ownera, oznaczyć **NOT_RUN**, nie zastąpić fixture PASS. Wynik nie może odtworzyć session/podglądu A w B/gościu. Opóźniony refresh z dawnego APK nie dowodzi tego konkretnego GET/code-exchange.

Świadomy PUT opt-in/opt-out, realny ranking, E4/push/ACK/import/WorkManager, KO31, recovery i Nemesis są kolejnymi odrębnymi odbiorami. Nie rozbudowywać pierwszego scenariusza, aby zamknąć je pozornie.

## STOP, PASS i odpowiedzialność

- STOP przed loginem: brak stabilnego osiągalnego issuer/origin, certyfikat/trust mismatch, pusty/nieprawidłowy api_base_url, inne applicationId/callback albo brak jednoznacznego artefaktu/baseline. Nie naprawiać przez czyszczenie danych.
- 401: odnowienie przez istniejący mechanizm O1, najwyżej jego przewidziana próba, bez nieskończonej pętli; prywatny stan i lokalny zapis zachowane. 403 account_bootstrap_required wymaga bootstrapu, account_deleting blokuje online. 409 generation/epoch jest fence/recovery, nie zgodą na blind retry/import. 422 traktować jako niezgodność żądania/DTO. 429/503 respektują retry/backoff; nie są200/PASS. Do diagnozy O2 przekazać status, code, request_id i zanonimizowany kształt, bez tokenu/body prywatnego dziennika.
- PASS minimalnej ścieżki: faktyczne APK+browser PKCE+bootstrap+oba GET, zgodne DTO/kontekst, no-store, niezmieniony baseline i potwierdzony logout/restart/B→A. Spóźniona odpowiedź ma osobny wynik; cały rozszerzony scenariusz PASS wymaga także jej faktycznego odbioru.
- O1: APK/UI/Room/Vault/cache i receipt urządzenia. O3: działające deployment/origin/issuer/CA/routing bez zmiany tożsamości. O2: oracle HTTP/DTO, poprawa ujawnionego backendowego błędu na własnej gałęzi. Każdy podaje własne dowody; samo przygotowanie nie przejmuje odbioru innej osoby.

## Neutralny receipt (wypełnić dopiero po próbie)

```text
Data/strefa, wykonawca i scope:
App commit / versionCode / applicationId / APK SHA256 / Room version:
Deployment commit / schema / origin i issuer zgodność / public CA SHA256:
Urządzenie / sieć / trust potwierdzone bez TLS warning:
Przed/po baseline (prywatna lokalizacja dowodu; tylko equality/counts w publicznym opisie):
Discovery/readiness: NOT_RUN | PASS | FAIL, powód:
APK browser PKCE A / bootstrap200 / me200 / motivation200 / DTO-context / no-store:
GET bez implicit consent/import/push; cel/dziennik/outbox zachowane:
Logout/restart / B→A / izolacja i świeży read:
Spóźniona odpowiedź A: NOT_RUN | PASS | FAIL; rzeczywisty typ odpowiedzi i kolejność:
Pierwsza odmowa/status/code/request_id (bez credentials/tokenów/account identity):
Wynik: WAITING_EXTERNAL | PARTIAL | PASS | FAIL; następny krok i właściciel:
Granica: operator API smoke, fixtures, CI oraz starszy APK nie zastępują realnego APK wyniku.
```

Credentiale, tokeny, identity/sub, Room/WAL, prywatny dziennik i surowe logi poza Git. Receipt nie zawiera niepotwierdzonych wyników. Po niepowodzeniu: reprodukcja → jedna hipoteza → pomiar → jedna zmiana właściwego ownera → ta sama próba; historię odmowy zachować.

Dokument powiązany: [review zgód i uwaga E9](RECENZJA_ZGOD_O2.md). Samodzielne techniczne źródło uruchomienia: [infra/integration](../../infra/integration/README.md).
