# Niezależna recenzja dokładnej średniej Nemesis — aktualny odbiór

12 października 2026 r. Recenzent: niezależny nieautor, Agent 2. Recenzent nie zmieniał tracked kodu, SQL, kontraktów lub testów autora.

**Aktualny właściwy freeze: `22d6bc99f9292f248e31c4d433339fb44d6601bc`, base `ce8a326c7f745a00583745b90b164496073a0a61`. Ocena: 9,3/10, zero nierozwiązanych zidentyfikowanych P1/P2 w sprawdzonym zakresie.** Poprawka SQL jest z upstream `07e032d1bd4cc046ef5036525f82274149311544`; finalne22d poprawia także referencję Python. W chwili odbioru22d był lokalnym commitem, jeszcze niewypchniętym. Branch produktu `codex/backend-e8-nemesis-wyniki`, [PR42](https://github.com/Roseru/aplikacja-mobilna/pull/42); recenzent ma czysty osobny detached checkout22d i nie publikuje.

## Istotna korekta poprzedniej oceny

Odbiór07/11cases nie wykrył błędu przy dokładnym kasowaniu powtarzających się ułamków na samym progu HALF_UP. Koordynator wskazał dodatkową usterkę P2; recenzent niezależnie wykonał nowe realne HTTP/PG próby i potwierdził ją. Poprzedni raport07 SHA256 `9788b4f658e91526dde08c5a490446b1efcb0689cb2b7d245e7829e79e122cd7` zachowano byteexact jako `RECENZJA_POPRAWKI_SREDNIEJ_NEMESIS_07_HISTORY.md`. Jest historią sprawdzonych wtedy wektorów; nie stanowi akceptacji nowo wykrytej granicy. Obecna ocena22d wynika z osobnego właściwego odbioru naprawy.

Na07 legalne źródła E2700/intake1800,1800,4500,2699.999999999946 mają dokładną średnią Fraction `1/2000000000000`, która musi dać"0.000000000001". Lustrzane3600,3600,900,2700.000000000054 dają dokładny ujemny remis i"-0.000000000001". SQL provisional i final były poprawne; Python zwracał"0". Własne **4/4 rzeczywiste RED w26,80s** obejmują oba znaki i odwróconą kolejność. Oczekiwań nie obniżono, błędu nie nazwano problemem harnessu i nie zwiększano precyzji lub timeoutów dla green. REDXML/log i4JSON zachowano przed ponowieniem.

Ostatni dodatni intake powstał przez realny HTTP Meal z2699.000003 przy100g oraz100.0006 przy0.999991g. Ujemny używa2700 przy100g i0.0001 przy0.000054g. Wszystkie wire inputs są legalne z najwyżej6miejscami; rzeczywiste wartości projekcji porównano z dokładnym planem. Wektory nowej usterki podał koordynator; własny harness, HTTP source commands, Fraction assertions i odbiór SQL/final/Python wykonał recenzent. Publicznych unitcases autora nie zaliczam jako własnych.

## Finalna naprawa i audyt

SQL z07 pozostaje niezmieniony: dzienne ułamki sumuje przez dokładne NUMERIC dodawanie/mnożenie; końcowe div/mod wykonuje HALF_UP raz. Manifest aggregate body SHA256 pozostaje `33e4c80889812fe66b41748730d0db07f80b12c509720d047a1e5523c5f18533`. Wcześniejszy własny PG probe starego wyrażenia dzielenia60 pokazywał błędne±10⁻¹² zamiast Fraction0; current07 SQL/HTTP dawał0. Ten osobny dowód zachowuje `exact-mean-old-expression-proof.json` i manifest07.

Diff07→22d obejmuje wyłącznie Python `aggregates.py` oraz4 nowe unitcases autora. Mean deficit przelicza każde finite Decimal na dokładny Fraction, sumuje je, dzieli przez właściwe eligible_days i dopiero potem rozstrzyga HALF_UP integer divmod. Decimal(units).as_tuple() oraz jawny exponent−12 zachowują wynik bez zależności od ambient Decimal context, zwiększania precyzji lub limitu sześciu cyfr części całkowitej; rounded_units0 daje kanoniczne"0". Membership/eligibility/maturity, points, hidden/null/counts, DTO, routing, źródła, SQL, migracje, ACL, capability i finalizer nie zmieniły się. Weight block oraz jego dotychczasowa ścieżka Decimal są byte-identical; `_precision` służy teraz wyłącznie wadze. Przejrzano rzeczywisty diff i finalne ciało funkcji.

## Własny odbiór22d

**19 targeted PASS w39,21s**, bez failure/error/skip. To **4 niezmienione realne HTTP przypadki RED→GREEN +12 własnych pure Fraction vectors +3 właściwe powtórzone przypadki SQL/Python z wcześniejszego zakresu**, nie19 nowych unikalnych przypadków ani suma dawnych11/19/4.

- Te same4 legalne HTTP przypadki z07 mają na22d identyczne właściwe SQL provisional/final oraz właściwy Python wynik±10⁻¹². Trzy ważne puste daty są wykluczone; eligible_days4/points4/closed_days7 pozostają zgodne.
- Dwanaście dodatkowych własnych pure vectors sprawdza exact cancellation±/reverse, order12 blisko obu stron progu i oba znaki, availablezero, dodatni/ujemny recurringthird oraz duży ujemny output. Fraction expectations są niezależne od wyniku aplikacji. Każdy sprawdza regularity i hidden bez counts.
- Trzy właściwe wcześniejsze probes ponownie wykonano na22d:90durablefacts zeligible88/complete89,90hidden oraz legalne tinyE0.000015 z HTTP intake999999.999998 i output `-6666666666553.333333333333`. SQL provisional/final i nowa referencja Python są identyczne. Dwa90-date probes używają jawnych trusted private fixture edits trwałych faktów po prawdziwym accept; nie są przedstawiane jako90HTTP źródeł lub dowód source qualification.

Środowisko: własny PostgreSQL17.11/SCRAM55524, fresh osobne bazy, losowe prywatne credentials, własny storage i procesy. Producer helper przygotowuje rzeczywisty production factory/DB lifecycle; nowe oczekiwania i polecenia wykonał recenzent. HTTP używa TestClient i syntetycznych podpisanych JWT/JWKS, co nie oznacza rzeczywistego Keycloak/TLS. Nie dotykano root55521/22, autora55523 lub cudzych checkoutów/usług.

## Aktualny instalowany wheel

Własny proces Python−I odczytał wyłącznie nowy zainstalowany wheel22d: SHA256 `2a8ad01e0bf68fea5bc1f38d8e574596620f08d9ad1028dd40bca07200da97a5`. Import pochodzi zsite-packages, sys.path nie zawiera checkoutu, cały moduł Nemesis odpowiada frozen22d,12SQLresources installed==wheel byteexact (pełna treść checkoutu po standardowej normalizacji GitCRLF/LF), brak tests wwheel, strict signed/hidden i production route PASS.

Dodatkowy installed22d proof wykonał12 kontroli exactcancellation: znaki±, forward/reverse, ambient Decimal contexts5/28/160. Wszystkie dały właściwe±10⁻¹². Nie zaliczam poprzedniego2486wheel07 lub2a8wheel605 jako aktualnego pakietu. Własny installed07 fresh migration/check/hashmanifest/realactivation/hardenedminimalSCRAM/noSETROLE/CLI proof pozostaje osobnym dowodem niezmienionej granicy SQL i provision; nie jest ponownie liczony jako19targeted22d.

## Zachowane dowody i polecenia

Dokładne argv, node IDs, środowisko bez credentiali oraz wszystkie XML/log/script/JSON hashes są w nowym prywatnym `exact-cancellation-independent-manifest.json`. Własny07RED używał `python -m pytest test_exact_cancellation_independent.py -q --junitxml=exact-cancellation-07-red.xml --basetemp=exact-cancellation-red-temp`. Proper22d uruchomił trzy wskazane testfiles z selekcją `-k "exact_cancellation or additional_vectors or durable90 or legal_tiny"`, XML `exact-cancellation-22d-green.xml`, temp `exact-cancellation-green-temp`. Osobno `installed-python -I package_exact_cancellation.py`.

| Dowód | SHA256 |
|---|---|
| exact-cancellation-07-red.xml | `ffc1e2e6ad20c03c3de560aae6ff740c445214bd0f60b049847b49fa8e8f3d97` |
| exact-cancellation-07-red.log | `2408d4c2b01c355c4e22e83a34caf493985cff2406099d869a1f9152590b8f29` |
| exact-cancellation-22d-green.xml | `0172090cd65bea1e1e094f7e6b8e4669f7ec53151d1ffdf3aac7779cbf14a52c` |
| exact-cancellation-22d-green.log | `2cfc7d0bbaee8e75f9cb2da1c2089f864c56057d280f2f6159ee227af39e446b` |
| package-exact-cancellation.log | `326dd5e539ad86d4b6a733921c0e65d01aea13e3dc7b7b516ed4d14056cc5395` |
| test_exact_cancellation_independent.py | `6a8f7873b11b853ebc76b5d1be051c265cfbc8bc76f3346d7d561130a8e78d47` |
| test_exact_cancellation_python.py | `43614b72fafcc1c5da031a0e577685090d477177df4b95b411a58d83d4575b6d` |

Proper22d targeted node IDs:

- `test_own_exact_cancellation_half_http_sql_final_and_python[exact_cancellation_positive]`
- `test_own_exact_cancellation_half_http_sql_final_and_python[exact_cancellation_negative]`
- `test_own_exact_cancellation_half_http_sql_final_and_python[exact_cancellation_positive_reversed]`
- `test_own_exact_cancellation_half_http_sql_final_and_python[exact_cancellation_negative_reversed]`
- `test_own_python_fraction_rounding_additional_vectors[cancel_tie_1]`
- `test_own_python_fraction_rounding_additional_vectors[cancel_tie_reversed_1]`
- `test_own_python_fraction_rounding_additional_vectors[near_1_1]`
- `test_own_python_fraction_rounding_additional_vectors[near_1_-1]`
- `test_own_python_fraction_rounding_additional_vectors[cancel_tie_-1]`
- `test_own_python_fraction_rounding_additional_vectors[cancel_tie_reversed_-1]`
- `test_own_python_fraction_rounding_additional_vectors[near_-1_1]`
- `test_own_python_fraction_rounding_additional_vectors[near_-1_-1]`
- `test_own_python_fraction_rounding_additional_vectors[available_zero]`
- `test_own_python_fraction_rounding_additional_vectors[positive_recurring]`
- `test_own_python_fraction_rounding_additional_vectors[negative_recurring]`
- `test_own_python_fraction_rounding_additional_vectors[large_integer]`
- `test_own_durable90_fraction_eligibility_scope_and_python_parity[ninety_eligible88_exact]`
- `test_own_durable90_fraction_eligibility_scope_and_python_parity[ninety_hidden_no_counts]`
- `test_own_legal_tiny_E_large_integer_signed_and_twelve_places`

## Granice przekazania

Ocena nie sumuje historycznych19prób4c,4supplement605,11SQL/samples07, wyników autorów lub root. Wykryty P2Python na07 jest zamknięty actual4RED→GREEN i właściwym pakietem22d. Aktualny code/doc push i osiem CI nowegohead/base nadal musi wykonać uzgodniony pojedynczy writer/koordynator; CI07 nie jest CI22d. Docker, osobny CI main, rzeczywisty APK/UI/cache O1, rollout/schedule/RPO/RTO O3 oraz pełny E8/E8.5 pozostają swoimi odbiorami. Nie deklaruję ich za innych.

WłasnyPG55524 po odbiorze ponownie STOPfast/wait; HTTP55534 nigdy nieuruchomiony. Checkout22d czysty, bez tracked changes, dodatkowego PR lub pusha. Raport07 i jego hash zachowane jako historia; aktualna ocena niniejsza zastępuje jego akceptację zmienionej granicy Python.
