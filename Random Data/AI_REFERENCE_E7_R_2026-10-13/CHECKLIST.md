# Checklista przyjęcia E7-R — WAITING_EXTERNAL - osoba 2

## Aktualny wynik kwalifikacji offline (13.10.2026)

[Propozycje referencji](reference_proposals.json) rozliczają wszystkie35 plików (30 pierwotnych +5 nowych):
30 PROPOSED (8/8/10/4),4 REJECTED (commons-03/07/08/20),1 UNRESOLVED (n5-16).
To propozycje LLM do człowieka, human_qualified/consents/uploads=0.
NOT-RUNNABLE; HUMAN_REVIEW_PENDING; O3_CONFIGURATION_PENDING.
Przekrój30 propozycji jest kompletny. Wszystkie oryginały pozostają zachowane; candidate_index
z opisem8/8/10/4 jest historycznym wyborem kandydatów, nie przyjętym corpus.
[Raport](../../docs/e7/RAPORT_PRZYGOTOWANIA_ZDJEC.md) podaje wyjątki, ograniczoną
próbę zamienników i domknięcie trzech slotów i przejście do istniejącego runnera.
[Audyt](technical_audit.json) ponownie potwierdza bajty/codec/hash/wymiary/GPS.

**Historia pozyskania:** pierwotnie wybrano30 kandydatów w [candidate_index.json](candidate_index.json), qualified=0. Przyjmujemy konkretne istniejące obrazy; odrzucone zastępujemy przed zamrożeniem. Dawne instrukcje dostarczenia P01 i początkowego braku zdjęć są historią przygotowania, a nie bieżącym brakiem wszystkich plików. [README](README.md) i [galeria](GALLERY.md) podają aktualny zakres.

Poniższe kroki dotyczą przyszłych prawdziwych wejść. Dokument i capture_plan.json nie są executable manifestem.

## Zdjęcia i niezależne referencje — właściciel/fotograf, O2, oceniający

1. Wyznaczyć jawny prywatny folder poza Git i politykę przechowania corpus. Nie przesyłać zdjęć, etykiet zawierających dane osobowe ani dowodów zgód do repo. Źródłowe zdjęcia są dostępne; actual_ready=0 oznacza brak przyjęcia/zgód, nie brak plików.
2. Małą próbę offline n5-01/n5-09/commons-03/commons-15 wykonano (raport). Trzy brakujące sloty uzupełniono: n5-17,commons-21/22. Rozstrzygnąć wyjątki i zatwierdzić przed zamrożeniem30 różnych zdjęć:8/8/10/4. Nie liczyć wielokrotnych ujęć tej samej fotografii ani syntetycznych rozmyć jako nowe nieczytelne przypadki. U01–U04 muszą zostać uznane za nieczytelne przez człowieka przed odpowiedziami modelu; jeśli identyfikacja jest możliwa, zmienić slot przed zamrożeniem.
3. Źródło każdej fotografii: autor/ID dowodu uprawnienia, kiedy wykonana, konkretny obiekt, prawo wykorzystania do tego testu; dla publicznej fotografii także URL pliku/ID, licencja i atrybucja. Sama karta producenta nie daje prawa do jego zdjęcia. Oddzielić źródło zdjęcia od źródła referencji składników.
4. Dla obrazu dostarczyć świadomą zgodę accepted/reference_use_accepted/nonsensitive=true, provider=gemini, scope=this_photo, faktyczny notice_version, rzeczywiste approved_at UTC i evidence_ref. Nie wypełniać tych pól na podstawie istnienia pliku lub tego planu. Osobno uzgodnić ewentualną publikację; zgoda testowa jej nie zastępuje.
5. Oceniający nie odczytuje wyników modelu przed referencją. Potwierdza readability i uzasadnienie; źródło to rzeczywista etykieta tego wariantu lub udokumentowana receptura/przygotowanie tej konkretnej porcji. Przy racjach zapisać opakowanie/menu/rocznik i faktycznie występujące komponenty; nie sumować alternatyw. Niepotwierdzona nazwa, producent lub dopasowanie wymaga wyjaśnienia przed kwalifikacją.
6. Zamrozić główne składniki i 1–20 accepted_aliases dla każdego z nich; nazwy muszą być niezależne od modelu. Czytelne: 1–30 głównych składników. Nieczytelne: readable=false i main_components=[]. Nie dopisywać niewidocznych składników tylko z typowego przepisu. Każdą rozbieżność przepisu/widoczności rozstrzygnąć jawnie w criterion przed runem.
7. Oracle runnera porównuje dokładne nazwy po NFKC/casefold/whitespace. Aliasów nie powielać między składnikami. Sukces wymaga wszystkich głównych składników; fuzzy/substring nie są obsługiwane. Regułę dodatkowych składników i wyższe kryteria sprawdza manual review. Masa/kcal nie rozstrzygają trafności; brak to null/nieznane, nie zero.
8. Sprawdzić nonsensitive, brak twarzy/osób/adresów/geolokalizacji i niepotrzebnych metadanych. Każdy ostateczny plik: JPEG/PNG/WebP ≤5 MiB, ≤4096 px/bok i ≤16 mln pikseli. Dokładne zatwierdzone bajty zabezpieczyć przed zmianą; SHA-256 liczyć dopiero po uzgodnionym przygotowaniu. Nie opierać się na przeskalowanej kopii z podglądu.

## Manifest istniejącego runnera — O2

- Top-level dokładnie format_version=e7-reference-manifest-v1, created_at, o3_confirmation, o3_evidence_ref, expected_profile, cases. Bez pól planu, rozmiarów, wymiarów lub dodatkowych danych w ścisłym manifeście; te dowody przechować w prywatnym sidecar.
- Case dokładnie case_id, group, image, image_sha256, legal_source, consent, reference. Grupy products/mixed/rations/unreadable; minimum 8/8/10/4. ID ASCII do 40 znaków. image to względna ścieżka z / bez .., dysku/ADS/backslash, symlink/reparse. 30–100 przypadków, unikalne obrazy i rzeczywiste unikalne SHA-256.
- Consent dokładnie accepted, reference_use_accepted, nonsensitive, provider, scope, notice_version, approved_at, evidence_ref.
- Reference dokładnie readable, criterion, source, reviewed_at, reviewer, main_components. Składnik dokładnie label, accepted_aliases. Wszystkie czasy faktyczne UTC Z, bez przyszłych dat.
- Manifest UTF-8 ≤256 KiB, brak duplicate keys/NaN/Infinity/NUL, depth≤20. Przeczytać aktualne tools/ai_reference/README.md i walidator run.py; plan nie jest generatorem ani alternatywnym runnerem.
- O2 i niezależny oceniający podpisują datowany hash manifestu, listę hashów corpus, referencje i stan 30/30. Przechować dowód, że nastąpiło to przed pierwszym wynikiem modelu. Żadne późniejsze aliasy/korekty nie nadpisują zamrożonej wersji; nowa wersja zachowuje historię i stare wyniki.

## O3 i kontrolowane pierwsze wykonanie

- O3: faktyczne project/environment/model, potwierdzone Free Tier Standard, billing disabled i development-only, RPM/TPM/RPD i dodatkowe wymiary, model_verified, quota_windows oraz datowany o3_evidence_ref. Bez zgadywania wartości, billing lub pozyskiwania sekretów przez O2.
- expected_profile z rzeczywistych capabilities, zgodny z O3 i backendem; actual notice_version. API/worker/storage/cleanup/restore/pool gotowe. Token przekazany poza argv/repo/logami. Output istniejący prywatny absolutny poza Git z ACL opisanymi w README runnera; nie używać katalogu niniejszego planu jako output.
- Po rzeczywistym kompletowaniu wejść operator wykonuje istniejący runner --max-cases 1 przez API aplikacji; potem świadome dalsze partie ≤10 z poszanowaniem limitów. Bez Google SDK/direct call, automatycznych uploadów ani nowych kluczy po unknown. Nie kasować state.json dla obejścia odmowy/quota.

## Dowód odbioru — nadal otwarty

Przy 26 czytelnych zdjęciach wymagane co najmniej 24 sukcesy identyfikacji. Raportuje się wszystkie planowane/wykonane/niewykonane i terminalne błędy. Brak zaobserwowanych błędnych struktur to brak przypadków, nie PASS 0/0. O1/manual review osobno sprawdza 100% ręcznego fallbacku oraz O3 dowód cleanup; runner tego nie zamyka. Sam plan, walidacja offline lub mock nie zaliczają E7-R ani wydania AI.
