# Wspólny kandydat ręcznego posiłku i ponowienia ACK

Agent1,21.10.2026, lokalnie `codex/android-kandydat-e4`, istniejący
[PR138](https://github.com/Roseru/aplikacja-mobilna/pull/138).
Dokładne źródło kwalifikowanych APK: `d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075`.
Zwykłe merge własnych139/a1f547a i138/eff71c3 oraz raportu138/6ae5633;
bez przepisywania historii. Docelowa baza istniejącego138 to
`codex/android-posilek-reczny-sync`/a1f547a/PR139; kolejność129→139→138.
Nie scalono dziecka do139/129 i nie powstał drugi PR z tym samym kodem.

## Zachowanie i test łączący funkcje

Normalny DiaryRepository.addCustomProduct tworzy prywatny produkt, lokalny
szkic i oddzielny kanoniczny Meal/create. MealPushStore zamraża kopertę,
SessionController wysyła ją i validation może zatrzymać poprawny ACK przed
trwałym zapisem. Nowy test manualConsumptionAndAckGatePreserveFrozenWireAcrossCancelledAcknowledgementAndReplay
nie seeduje kanonicznego posiłku SQL. Sprawdza porcję150.5, manual/product=null,
protein=null/fat=0, attempted=true, brak ACK/revision0, anulowanie korutyny,
odtworzenie kontrolera, dokładnie te same bajty żądania i already_applied/
revision1/acked/complete. Zachowuje lokalne item/product/source oraz dane
i kolejkę gościa. Transport fixture ma pusty HTTP receipt: **to nie jest
rzeczywisty HTTP, COMMIT, kill procesu ani PG C1/C2**.

## Historia nowego testu i kwalifikacja

Pierwszy pełny build c3110bd PASS881,08s,330/369JVM0fail/errors/skips.
Pierwszy focus nowego przypadku1/1FAIL: po poprawnym replay/revision1/
complete asercja błędnie szukała acked w canonicalMealOperations, które
jawnie wyklucza acked. Log FAIL SHA256:
`df2aa5d9fe20e76d39396457bafe113c61cbb6b2186e1bf0a1d9ab41ecb46698`.
d3f6dba zmienia tylko ten test: odczyt konkretnej operacji po operation_id
oraz dodatkowa asercja pustej kolejki aktywnej. Kod produkcyjny bez zmian,
oba APK aplikacji identyczne jak c311. JVM wejścia niezmienione;
raporty330/369 po poprawce pozostają UP-TO-DATE, nie są nowym wykonaniem JVM.
Poniższe nowe APK testów/focus/pełny native/opt-in dotyczą dokładnego d3f6dba.

## Faktyczna kwalifikacja tego źródła

- Pełny build PASS237.5s:330debug/369validation JVM,
  failures/errors/skips0; wspólne testy powtarzają się, nie sumujemy ich.
  Lint0error/4warning/1info. Osobny nowy test łączący funkcje1/1PASS.
- Pełny native **329/329PASS,0fail/0skip**,1197.97s,
  API35 offline na O1Tests35/5556. Install-r zachował29tabel,Room14/FK clean;
  dokładne zainstalowane SHA zgodne z artefaktami. Tryb samolotowy włączony,
  Wi-Fi wyłączone i brak sieci domyślnej przed/po. Zwykły5554/manual139 i API5558 zachowane.
- Osobny opt-in build PASS228.23s. Domyślny testAPK
  wyklucza LiveMealReplayTest, opt-in go zawiera i nie był uruchamiany live.
  Validation APK identyczny przed/po opt-in. Debug DEX bez bariery, rzeczywiste
  constant pool kontrolera/transportu bez referencji obserwatora w debug,
  z record/beforeApplyAck w validation. Wejścia i4artefakty niezmienione.
- Pierwsza próba uruchomienia Gradle nie połączyła się z własnym daemonem
  w ograniczonym środowisku, przed kompilacją. Jej stare wyjścia139 nie są
  dowodem kandydata. Powyższy wynik pochodzi z odrębnego poprawnego przebiegu.

| Artefakt0.8.23/Room14 | SHA-256 |
|---|---|
| debug | `f800b1a1b4955d57b6328daed708956521239ccc8c112d13bdbd507ff0bb234c` |
| validation | `7037fb85e37fba022bd41dd55c197d72e6e5bb7311ade90c4892f9adcfed4ffb` |
| tests | `6a0a783cd1ed6b7f1908388c329bb7b58fe905438aa2ee72f91761ac6b2f0d69` |
| optin_tests | `75bd907ec1c0ceb8197b37effc206797dccbaf61ca465ef9b5b78cd8239b9254` |

Debug applicationId pl.roseru.kalorie/code34; validation
pl.roseru.kalorie.validation/code1034. Dokładny pakiet4APK z
handoff-manifest.json/HANDOFF-SHA256SUMS poza Git w output-apk/joint-e4-d3f6dba.
Log329 SHA256:`e48250092f3fb4224de5f11cdb9723a7dcb7d6728d40ad8c5164ff820c721722`.
Pierwotny319/320FAIL i poprawiony320/320 standalone138 są zachowane
w [osobnym raporcie](DRIVER_REPLAY_E4.md); nie zastępują tego nowego odbioru.

## Wejścia potrzebne do właściwej próby

To kwalifikowany **wariant offline bez issuer/API/overlay TLS**, nie gotowy
skonfigurowany APK do wspólnego live E4. Trzy dołączone schematy sync/common/
domain są zgodne po LF z zasobami archiwalnego8ff7c0c wskazanego przez O3.
To kontrola źródeł, nie aktualnego obrazu, checkpointu lub osiągalności.

O2/O3: proszę potwierdzić docelowy obraz/schema24 lub osobne środowisko,
aktualne publiczne issuer/API, zaufane CA i sposób prywatnego przekazania
konta syntetycznego. O1 zbuduje oddzielny skonfigurowany wariant z overlay,
zweryfikuje jego manifest/SHA i dopiero przekaże gotowość do uzgodnienia okna.
Nie publikować haseł, tokenów, raw body lub baz w dzienniku.

Technika przerwania: osobna faza hold drivera po poprawnej HTTP200,
zewnętrzny niezależny C1, potem am force-stop wyłącznie dedykowanego pakietu
validation przed deadline45s. Replay uruchamiany w nowym procesie z niezależnym
external_kill_utc; driver wymaga innego PID/start i identycznej koperty.
Timeout/release lub anulowanie korutyny nie zastępują rzeczywistego kill.
Odczyt C1 i kill muszą zmieścić się w pozostałym czasie, inaczej próba NOT_RUN.

Bez restartu PC, wipe/clear/uninstall, relay/API/Gemini/deploy lub zmiany
schema24/epoki/kont. **Live prepare/hold/replay/kill/PG C0C1C2, pełny E4,
E7-R/recovery/KO32 NOT_RUN**. Import, legacy i WorkManager osobno.
