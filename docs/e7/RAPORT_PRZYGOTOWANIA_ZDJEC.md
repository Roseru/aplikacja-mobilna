# Przygotowanie referencji zdjęć E7-R - osoba 2

Stan 13.10.2026: **OFFLINE / NOT-RUNNABLE / HUMAN_REVIEW_PENDING /
O3_CONFIGURATION_PENDING / CORPUS_INCOMPLETE**. Baza: main
`28f70a59abb9f5d199f5a3e9fa6bb7f432a17be5`.
Gałąź: `codex/backend-e7-referencje-zdjec`.
Nie uruchomiono E7-R, E10, Gemini, workerów, billing lub Nemesis.
Nie mierzono trafności ani ręcznego fallbacku.

## Konkretny pakiet

[Galeria](<../../Random Data/AI_REFERENCE_E7_R_2026-10-13/GALLERY.md>),
[propozycje](<../../Random Data/AI_REFERENCE_E7_R_2026-10-13/reference_proposals.json>),
[audyt techniczny](<../../Random Data/AI_REFERENCE_E7_R_2026-10-13/technical_audit.json>)
i [master](../MASTER_PROMPT_E7_R_PRZYJECIE_ZDJEC.md).
Oryginalny candidate_index jest zachowany jako historia wyboru; jego 8/8/10/4
oznacza pierwotnych kandydatów, nie zaakceptowany przekrój.

| Licznik | Wynik |
|---|---:|
| Zbadane i obejrzane dokładne pliki | 32 |
| Technicznie poprawne / unikalne hash i RGB | 32 |
| Proponowane do człowieka | 27 |
| Nierozstrzygnięte | 1 (n5-16) |
| Odrzucone merytorycznie | 4 (commons-03/07/08/20) |
| Nowe pobrane obrazy / zastąpione | 2 / 1 (proponowana) |
| Human qualified / provider consents / uploads | 0 / 0 / 0 |

Proponowany przekrój to **8 produktów / 7 mieszanek / 8 racji / 4 nieczytelne**.
Brakuje jednej mieszanki i dwóch racji, zanim da się zamrozić minimum 30.
Wszystkie 32 przypadki rozliczono; odrzucone materiały pozostały w repo.

## Mały eksperyment i decyzje

Najpierw view_image dokładnych bajtów n5-01, n5-09, commons-03 i commons-15.
Jabłko potwierdza rekord apple; warzywna mieszanka potwierdza pomidory, ogórek
i marchew (anotacja baby carrots nie narzuca wyglądu całej baby carrot).
Nieprzezroczysty liść zasłania jedzenie: readable=false, main_components=[].
Blok chicken tetrazzini ma nazwę w podpisie, ale nie ma wiarygodnej receptury/
listy widocznych składników. Wynik eksperymentu: oddzielny photo_source,
reference_source oraz decyzja/niepewności i brak podpisów w każdym case.
Ten format zastosowano do wszystkich 30 oryginałów.

- commons-03: odrzucone — nie wyprowadzamy kurczaka/makaronu z samej nazwy.
- commons-07: odrzucone — źródło nie identyfikuje głównych dodatków/napojów;
  sama jambalaya nie opisuje całego widocznego zestawu.
- commons-08: odrzucone — etykieta kartonu 18 zestawów, bez fotografii jedzenia.
- commons-04: proponowane brown rice; ziarna widoczne, rodzaj potwierdza
  opis konkretnego zdjęcia, bez nazwy współczesnego menu.
- commons-10: proponowany wieloobiektowy widok pięciu przykładów owoców.
  Etykiety potwierdzają oddzielne pozycje; nie sumujemy alternatyw ani wartości.
- n5-16: wstrzymane — żółte kawałki dyniowatych nie mają jednoznacznego
  powiązania z chayote z anotacji. Człowiek musi rozstrzygnąć źródło lub wymienić.
- n5-10: proponowany jeden agregat bulw yam + sweet potato. Nie można ich
  osobno przypisać wizualnie. Człowiek musi przyjąć tę granularity lub zmienić
  przypadek; pojedynczy alias batat nie zalicza obu. n5-14: część brokułu
  zasłonięta; sałatka pozostaje zbiorczą potwierdzoną pozycją caesar salad.
- commons-15–18: różne zdjęcia/obiekty, ale ten sam mechanizm liści.
  Nie domyślamy się składników ukrytych w opakowaniu z typowych receptur.
  Przekrój nie sprawdza naturalnego rozmycia lub złego oświetlenia.

W żadnym przypadku nie dodano niewidocznej soli/oleju z Nutrition5k.
Nazwy zbiorcze berries/caesar salad pozostają jawne, a nie rozbite na
nieudokumentowane przepisy. Masa/kcal w propozycjach to null, nie zero.

## Ograniczone pozyskanie zamienników

Rozpatrzono trzy publiczne źródła Commons: FEMA 39890 peanut butter,
First Strike Ration i MRE No.23 (cropped). Zapisano jeden batch pierwotnych
metadanych w
[dowodzie źródeł](<../../Random Data/AI_REFERENCE_E7_R_2026-10-13/commons/replacement-source-evidence.json>).
Pierwsze dwa oryginały pobrano; trzeci request (MRE23) zwrócił **HTTP429**,
więc przerwano bez retry. Pobrano2 nowych kandydatów, mniej niż limit6.
commons-19 ma czytelną etykietę peanut butter i zastępuje w propozycji
commons-08. commons-20 pokazuje zamknięty zestaw i dłoń; odrzucony, bez
domyślania zawartości z typowej listy źródłowej. Zapis batch index nie
dokończył się po błędzie; odzyskane bajty obu plików sprawdzono przez SHA1
oryginału Commons i SHA256. retrieved_at=null; mtime zapisano jawnie
jako obserwację filesystem, nie wymyślony czas pobrania.
[Indeks nowych kandydatów](<../../Random Data/AI_REFERENCE_E7_R_2026-10-13/commons/replacement-index.json>).
O2 po osobnym wznowieniu może sprawdzić brakujące sloty; obecny pakiet nie
ukrywa braku trzech miejsc.

## Kontrole offline

Wszystkie 32 dokładne pliki obejrzano przez view_image.
Audyt ponownie dekoduje obrazy i sprawdza bajty/SHA-256/wymiary/codec,
unikalność hashów i identycznych RGB, brak GPS, licencje/locatory,
atrybucję, pending/null i spójność galerii z obrazem/hash/ID.
Nie zmieniono oryginalnych bajtów. EXIF opisu aparatu/pustych opisów,
camera/date/orientation w odrzuconym commons-08 i ICC pozostają źródłowe;
nie znaleziono prywatnej tożsamości/GPS. Adresy producentów na etykietach
to publiczne dane produktu. Ludzka decyzja nonsensitive pozostaje null.
Backend przy późniejszym autoryzowanym przygotowaniu usuwa metadane;
obecny audyt nie nadaje zgody.

Powtarzalna komenda (Python z Pillow, jak w backendzie):

```powershell
python tools/ai_reference/validate_proposals.py
python -m unittest discover -s tools/ai_reference -p test_validate_proposals.py
python tools/contracts/validate.py
git diff --check
```

Walidator jest tylko offline i nie eksportuje manifestu lub nie wywołuje HTTP.
`OFFLINE_PACKET_VALID_NOT_RUNNABLE` oznacza spójność materiału, nigdy E7-R PASS.
Siedem powtarzalnych kontroli: pending nigdy runnable, zmienione bajty/hash, kolizja aliasów, duplikat ze zgodnym indeksem, brak locatora i podmieniony hash rekordu źródłowego.
E0: 10 schemas, 95 valid / 35 invalid, 18 scenarios, 16 Decimal vectors.
PG/Keycloak/emulatorów nie uruchamiano; CI nie zmieniano.
Niezależny przegląd zakończony9,2/10, zero otwartychP1/P2/P3; final-head CI jest osobną wymaganą kontrolą publikacji.

## Deterministyczne przejście do istniejącego runnera

1. Człowiek przegląda galerię i dokładne hashe, rozstrzyga wyjątki oraz
   zatwierdza czytelność/główne składniki/aliasy/źródła/niesensytywność.
   O2 uzupełnia trzy brakujące sloty legalnymi zbadanymi zdjęciami.
   Propozycja LLM nie jest podpisem; prawdziwy reviewer i reviewed_at dopiero
   z datowanego dowodu człowieka przed wynikiem modelu.
2. Osobno świadoma zgoda na każdy konkretny hash, Gemini, this_photo,
   reference use i aktualny notice. accepted/reference_use_accepted/
   nonsensitive, approved_at/evidence_ref tylko z rzeczywistych wejść.
   Obecne przygotowanie nie nadaje tej zgody; samo publiczne źródło również nie.
3. O3 przekazuje datowane potwierdzenie development Free Tier bez billing,
   rzeczywistych project/environment/model/limitów/quota windows,
   actual capabilities profile i notice, gotowości API/worker/storage/
   cleanup/restore. O2 nie wypełnia tych pól na podstawie planu.
4. Po komplecie operator kopiuje dokładne zatwierdzone bajty do prywatnego
   corpus poza Git. Mapowanie case: case_id/group/image/image_sha256 oraz
   legal_source z photo_source. proposal nie jest kopiowana automatycznie
   do reference: ludzki zatwierdzony wynik dostarcza dokładnie readable,
   criterion, source, reviewed_at, reviewer, main_components. Komponenty
   mają tylko label i accepted_aliases. Consent ma dokładnie pola z
   [README runnera](../../tools/ai_reference/README.md). Pola audytu/decision/
   proposal/uncertainties pozostają sidecar, poza ścisłym manifestem.
5. Top-level ma wyłącznie format_version, created_at, o3_confirmation,
   o3_evidence_ref, expected_profile, cases. 30–100 unikalnych przypadków,
   minimum8/8/10/4, daty UTC Z, bez przyszłych dat. Zamrozić i podpisać
   hash manifestu/listę image hashes. Prywatny output ma ACL poza Git.
6. Dopiero osobne zlecenie realnego wykonania: istniejący run.py przez API
   aplikacji, --max-cases 1, dalej świadome partie według limitów.
   Bez direct Gemini, countTokens, automatycznych retry po unknown
   lub resetowania journalu. Aktualna walidacja nie wykonuje tych kroków.

Właściciele braków: człowiek — referencje/zgody; O2 — trzy sloty i prywatny
manifest po dowodach; O3 — konfiguracja/środowisko; operator — osobne zlecenie
pierwszego przypadku; O1/człowiek — późniejszy fallback, O3 — cleanup.
Pozostaje development demo i blokada wydania z wymagań11.6.

## Odbiór publikacji

Jedna niezależna recenzja gpt-6.1-sol/high: **9,2/10, zero otwartychP1/P2/P3**.
Recenzent sprawdził wszystkie30 pierwotne hashe/audyty,16 rawrecords/hash/parse
Nutrition5k i14 Commons metadata/licencje, obejrzał wszystkie14 Commons
oraz próbkę7 Nutrition5k z każdym spornym przypadkiem.
Po wskazanych dwóchP3 sprawdził tylko zmieniony zakres: pointery dokumentów,
locator/hash walidatora,7 własnych testów,2 nowe fotografie/metadane/hash/audyt.
ObaP3 zamknięte; n516 unresolved i brak3slotów są uczciwymi brakami corpus,
a nie pozorną akceptacją. Recenzja subagenta nie jest human approval.
Lokalnie: walidator32 PASS,7 testów PASS,E0 PASS586linków,diff-check PASS.
CI: siedem jobów +ci-required wymagane, wynik finalnego head do odczytu w PR.
Koordynator odbiera finalny branch/SHA/PR/CI i decyduje o merge.

