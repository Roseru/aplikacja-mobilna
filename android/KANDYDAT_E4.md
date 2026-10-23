# Wspólny kandydat ręcznego posiłku i ponowienia ACK

## Aktualny skonfigurowany pakiet — 23.10.2026

**Dostawa na GitHub potwierdzona:** [robocze wydanie z czterema APK](https://github.com/Roseru/aplikacja-mobilna/releases/tag/untagged-a106e469bb345cdfa8b1),
ZIP44941585B, SHA256 `8bcf6105e7fb064c35ba5d42321cc4cc8547a5a5b61796bdfc75510ff112522d`.
GitHub potwierdził size/digest asset668891678; wydanie pozostaje draftem,
dostępnym dla osób z dostępem do repo. Pobranie przez O3 nie jest jeszcze potwierdzone.
Package-SHA, CRC i podpisy4APK zweryfikowane. Signer O1:
`e1167912de15c155ed2ce4baf809c4fdf209a6705d860f847e5298d5f7f150b5`.
O3 używa świeżego osobnego AVD API35, bez instalacji nad własnym starszym APK
z innym signerem lub prywatnym dziennikiem. Zamrożony manifest wewnątrz ZIP
opisuje stan sprzed uploadu; jego LOCAL_READY nie jest aktualnym stanem dostawy.
Odczytano wynik O3-086/PR147 dla Room14; nie przenosimy go na ten nowy pakiet.

Źródło APK: **dc012fabf395480c6aa2d1b2a1d59b766ec4add3**,
Android **0.8.27**, debug38, validation1038/**0.8.27.validation**, Room17.
Zawiera scalony pełny pull PR144, ochronę21tabel i wymóg lokalnego zastosowania
najnowszej pełnej kopii konta przed każdą fazą drivera. Zwykły merge aktualnego
main ef4bb4f do2f85e91 nie zmienił żadnego wejścia kompilacji Androida;
sprawdzono wszystkie zapamiętane sumy plików. Istniejący PR138 przechodzi na main.

[Manifest czterech APK, konfiguracji i odbioru](KANDYDAT_E4_0_8_27.json)
zastępuje wcześniejszy pakiet0.8.23 jako kandydat do nowej próby. Historyczne
raporty niżej pozostają dowodami swoich źródeł, bez przenoszenia ich wyników.

- Skompilowane issuer/API odpowiadają wejściom O3-085; CA PEM SHA256
  `01f120ef25f091a6413a535dcaa5e333575a8d08a016503c47998333eef3a6f6`.
  Zaufanie dodatkowego CA dotyczy wyłącznie wariantu validation i dokładnego
  hosta192.168.3.162. Brak zaufania user CA, cleartext i includeSubdomains.
- Build debug/validation/domyslny test APK oraz lint PASS:0error/4warning/1info.
  **24 celowane JVM PASS**,12bariera/7HTTP/5odciski,0fail/error/skip.
  Nie uruchamiano ich ponownie przy budowie opt-in.
- Osobny opt-in build PASS280,11s. Domyślne APK nie zawierają drivera;
  debug nie zawiera bariery ACK. Opt-in test APK zawiera LiveMealReplayTest,
  lecz nie był instalowany ani uruchamiany. Validation APK zachował identyczny SHA.
- **4/4 native PASS,0fail/0skip**, API35, nowy osobny O1Replay35.
  Sprawdzono zainstalowane SHA, samolot/Wi-Fi off/brak aktywnej sieci przed i po.
  Test łączący producenta z replay sprawdza teraz także rzeczywisty zapis
  końcowej kopii do Room i zachowanie prywatnego produktu/źródła/gościa.
  Pozostałe trzy przypadki obejmują nawigację zdjęcia, jego odtworzenie po
  recreation i ekran320dp z font1,5. To zakres celowany, nie pełna regresja.
- Pierwszy prywatny weryfikator po poprawnym buildzie oczekiwał0.8.27 zamiast
  zamierzonego przyrostka.validation. Zachowano pierwotny wynik i poprawiono
  tylko oczekiwanie weryfikatora; źródła, trzy gotowe APK i wynik24JVM zachowano.
- **Otwarty problem CI:** main39916344347 miał358/359PASS i timeout drugiego
  revealPreview po recreation. Odczytano XML i logcat; powyższy focus przeszedł
  bez zmiany aplikacji/testu. Nie uznajemy tego za naprawę ani przyczynę wyjaśnioną.

Pakiet4APK z handoff-manifest.json i SHA256SUMS został dostarczony do roboczego
wydania GitHub wskazanego wyżej. To potwierdzenie uploadu, bez potwierdzenia
pobrania przez O3. Nowe okno i aktualny peer wymagają ustalenia przed wspólnym
transportem API oraz rzeczywistą próbą. Zdalny CI nowego head PR138 jest osobnym odbiorem.

**Live E4/HTTP/COMMIT/kill/PG C0C1C2, Gemini/E7-R/recovery/KO32 NOT_RUN.**
Nie otwarto starego relay, nie zmieniano epoki/kont/baz ani zachowanego API5558.
24JVM,4native i statyczna zgodność14plików backendu/3schematów z8ff7c0c
nie zastępują wspólnego testu. Trzy duże moduły O2 są opisane osobno w PR146;
nie są warunkiem rozpoczęcia ograniczonej próby wybranego Meal/create.

## Historyczny kandydat0.8.23

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


## O1-100 — aktualizacja rodzica139,21.10.2026

Zwykły merge f7cf71e i dokładnego139/afb6a0a. Cały Android/app i nadrzędne
wejścia Gradle/settings/properties/wrapper identyczne z f7cf71e; brak nowej
kwalifikacji APK lub runtime. Dokładny source APK nadal d3f6dba, istniejące
cztery SHA i pakiet nie zostały zmienione. Lokalnych jednostkowych/buildów
nie powtarzano. Narzędzia/CI/backend/infra z main e651fea. README i dziennik
rozstrzygnięto zachowując wszystkie145/224 historyczne wystąpienia i wiersze.

O2-048/eea45ae odczytane: źródłowa zgodność badanego zakresu PASS, runtime
PARTIAL. Nowy skonfigurowany validation/opt-in APK powstanie dopiero po
aktualnych wejściach obrazu/schema/projekcji, issuer/API/CA i sesji od O3.
owner_id PG musi odpowiadać binding.accountId, nie lokalnemu storageScope.
PR138 nadal draft na139; własny pełny CI po integracji rodziców wymagany.
Świeże okno i realny E4/C0C1C2/kill/replay pozostają NOT_RUN. Brak nowego
API/Gemini/relay/deploy lub zmian używanej instalacji i prywatnego dziennika.
