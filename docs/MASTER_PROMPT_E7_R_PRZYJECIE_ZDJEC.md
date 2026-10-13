# E7-R: kwalifikacja zdjęć i przygotowanie referencji — osoba 2

Kod startu: E7_R_PHOTO_PREPARATION_2026_10_13_O2. Bez rozpoczynania E10.
Wykonawca gpt-6.1-sol/medium; jeden niezależny subagent gpt-6.1-sol/high,
fork_turns=none. Przegląd agenta nie jest podpisem człowieka.

## Cel i granice

Przygotuj do ludzkiego zatwierdzenia kompletny, sprawdzony pakiet referencyjny
minimum 30 różnych rzeczywistych zdjęć: 8 produktów/składników, 8 dań mieszanych,
10 racji/składników i 4 nieczytelne ujęcia. Każdy obraz: dokładne bajty/hash,
pochodzenie/licencja, widoczność, propozycja głównych składników i aliasów,
powód przyjęcia/odrzucenia oraz jawny stan zatwierdzeń. Używaj istniejącego
runnera; nie buduj drugiej platformy.

Źródła: Random Data/AI_REFERENCE_E7_R_2026-10-13, PR56: 16 Nutrition5k i
14 Commons. Przy starcie human_qualified/provider_consents/uploads=0.
Odczytaj świeży main, E9 PR54 i komunikację PR58. Nie zaczynaj pozyskania od
zera ani nie powtarzaj archiwów lub poprzednich regresji. Demo pozostaje bez
official/producer verification.

To przygotowanie OFFLINE. Zlecenie nie daje aplikacyjnej zgody na wysłanie
zdjęć do Gemini. Nie odczytuj kluczy; nie uruchamiaj API/provider uploads,
workera, billing lub Nemesis; nie wdrażaj za O3. LLM i subagent nie nadają
human approval. Nie twórz fikcyjnych approved_at/reviewer/notice/profile/limitów.
Braki pozostają pending/null; brak składnika, makra lub masy nie oznacza zera.

## Start i kontekst

Sprawdź status/branch/remotes/otwarte PR-y, AGENTS.md, WYMAGANIA_PROJEKTOWE.md
(szczególnie 11.6), bieżący wiersz O2 i nowe wpisy KOMUNIKACJA_AGENTOW.
Czytaj README, CHECKLIST, GALLERY, candidate_index, README podzbiorów,
źródłowe anotacje/prawa, docs/e7/E7_R_MANIFEST.md i tools/ai_reference/README.md.
run.py czytaj dla ścisłego formatu/oracle; nie osłabiaj walidacji braków.
Własny czysty managed worktree z origin/main, gałąź
codex/backend-e7-referencje-zdjec. Zachowaj cudze checkouty, Random Data i
niezatwierdzone pliki. Ten master utrwal w tym samym PR, bez prywatnego stanu.

## Działania i mierzalne rezultaty

1. Mały eksperyment: obejrzyj przez view_image dokładny plik z każdej grupy;
   porównaj widoczne jedzenie z właściwym źródłem i zapisz cztery propozycje.
   Rozstrzygnij, czy racje i zasłonięte ujęcia mają uczciwą referencję, a nie
   tylko nazwę w podpisie. Oddziel źródło fotografii od źródła składników.
   Zastosuj sprawdzony format do wszystkich 30 przypadków.
2. Wszystkie pliki: hash/unikalność/codec/bajty/wymiary, pochodzenie,
   licencja/atrybucja, EXIF/dane osobowe. Obejrzyj każde zdjęcie. Zachowaj
   oryginały; konieczny wariant ma nowy hash i opis przetworzenia.
3. Jeden maszynowy plik propozycji i aktualizacja istniejącej galerii.
   Stabilne ID/grupa/hash, widoczne główne komponenty/aliasy, źródła,
   uzasadnienie i niepewności. Bez ukrytego oleju/soli Nutrition5k;
   bez sumowania alternatyw racji. Sprawdź commons-03/04/07/08/10 i
   podobieństwo opakowań z liści. Nieczytelność wynika z rzeczywistego obrazu,
   bez wygenerowanych rozmyć/duplikatów. Oracle: dokładne
   NFKC/casefold/whitespace, bez fuzzy i kolizji aliasów między komponentami.
4. Odrzuć nieuzasadnione przypadki. Legalne zamienniki tylko dla brakujących
   slotów, znane źródła pierwotne, maksymalnie 6 nowych pobranych kandydatów.
   Po nieudanych próbach nazwij brak; nie wymyślaj referencji ani nie
   pobieraj wielkiego datasetu. Bez kontaktowania dostawców.
   Publiczne pobranie źródła nie jest Gemini. Jakość/prawa mają pierwszeństwo
   przed liczbą 30; ujawnij niepełny przekrój.
5. Pakiet publiczny pozostaje NOT-RUNNABLE. Opisz deterministyczne przejście
   do ścisłego manifestu istniejącego runnera i brakujące wejścia człowieka/O3.
   Helper tylko jeśli ogranicza błędy; bez alternatywnego CLI/frameworka.
   Prawdziwe zgody/ludzkie referencje, aktualne notice/profile i datowane O3
   są wymagane; finalny manifest/output i środowisko poza Git.
6. Jedna niezależna recenzja: wszystkie metadane, wszystkie racje/nieczytelne,
   próbka czytelnych Nutrition5k i każda sporna propozycja.
   Próg >=9/10, zero P1/P2, uczciwie rozliczony każdy case.
   Human pending blokuje qualification/live, nie jakość pakietu.
   Naprawy i ponowny przegląd tylko zmienionego zakresu; po dwóch
   nieskutecznych cyklach nazwij przeszkodę. Drugi agent/xhigh tylko
   dla konkretnego unresolved problemu z uzasadnieniem.
7. Raport: zbadane/technicznie poprawne/odrzucone/zastąpione/proponowane,
   human_qualified/zgody/uploads, rozkład grup, kontrole, braki i właściciele.
   Bez wniosków o Gemini accuracy lub fallbacku z przygotowania.

## Kontrole i Git

Deterministyczna inwentaryzacja skryptem, istniejący E0 i diff-check,
hashes/liczności/formaty/źródła/aliasy/spójność galerii z bajtami.
Helper: negatywne przypadki podmienionych bajtów/hash, braków potwierdzeń,
kolizji aliasów i duplikatów; brak zgód nigdy nie daje runnable/PASS E7-R.
Nie uruchamiaj PG/Keycloak/emulatora dla samych materiałów.
Nie zmieniaj CI: siedem jobów i ci-required nadal wymagane.

Agent 2 commit, zwykły push i jeden spójny PR do main, bez force-push.
Uzupełnij tylko własny wpis/wiersz KOMUNIKACJA_AGENTOW; przed publikacją
pobierz nowy main i komunikację, przy merge zachowaj wszystkich autorów.
PR opisuje końcowy rezultat, faktyczne kontrole i granice.
Publiczne legalne źródła/dokumentacja w Git; bez sekretów/prywatnych zgód.
Nie scalaj sam: raportuj koordynatorowi branch/SHA/PR i final-head CI.

## Zakończenie i wznowienie

Pakiet do człowieka z uczciwymi brakami może być dobrym wynikiem.
Po konkretnym niezależnym przeglądzie pokaż galerię i zadaj jedno zbiorcze
pytanie o ludzkie przyjęcie, z wyjątkami i zakresem zgody.
HUMAN_REVIEW_PENDING i O3_CONFIGURATION_PENDING nie oznaczają E7-R.
Wznowienie: zatwierdzenia + kompletny przekrój + O3 + prywatny manifest/output,
istniejący runner przez API, najpierw jeden case.
Realne wykonanie wymaga osobnego zlecenia; to nie jest dispatch live Gemini.
