# Master: przygotowanie odbioru O2 równolegle z E9 - osoba 2

Zlecenie właściciela, 13 października 2026 r.: wykonać trzy zaproponowane zadania, doprecyzować prompty i rozpocząć pracę, używając narzędzi i delegacji proporcjonalnie do korzyści. Baza rozpoczęcia: main `2fc70f7ae612c031f63d53c04d3c81b4402b72c5`, repo `Roseru/aplikacja-mobilna`. Koordynator O2: `01a12156-2312-7c43-aedc-1858e782e5fb`.

## Wynik i podział

Przygotuj jeden spójny pakiet odbioru O2: powtarzalny scenariusz rzeczywistego APK/API, materiały referencyjne E7-R i ograniczony przegląd styku zgód Androida z E9. E9 pozostaje jednym aktywnym zadaniem implementacyjnym w PR54; nie zmieniaj jego checkoutu, kodu lub zakresu. E10 i rzeczywiste Gemini nie są uruchamiane tym zleceniem. Projekt obecnie jest demo; nie zmieniaj źródeł w official.

Koordynator używa czystego własnego checkoutu i gałęzi `codex/docs-o2-przygotowanie-odbioru`. Trzy niezależne, ograniczone zadania może delegować subagentom: medium dla scenariusza i materiałów, high dla przeglądu uprawnień/zgód. Nie potrzeba nowych czatów wykonawczych lub watcherów. Wspólne pliki i publikację utrzymuje koordynator, wyniki delegacji są draftami do odbioru. Jeden PR obejmuje końcowy rezultat, prompty i dowody; ograniczenia nie stają się PASS.

Przed zmianami przeczytaj wymagania oraz istotną aktualną komunikację. Używaj istniejących skryptów i dokumentów, zamiast kolejnej platformy testowej. Krótki stan utrzymuj w istniejącym KOMUNIKACJA_AGENTOW, zachowując historię i wiersze innych osób. Prywatne dane/credentials/SDK/buildy poza Git. Nie restartuj cudzych usług, nie resetuj kont lub danych, nie wyłączaj TLS, nie zmieniaj infrastruktury O3.

## Prompt A: minimalna pełna ścieżka

Przygotuj odbiór obecnego APK: konto A → prawdziwe logowanie w przeglądarce/PKCE → bootstrap → GET /me i GET /motivation → poprawny odczyt właściciela, bez zmiany dziennika/celu/outbox lub implicit opt-in. Następnie logout/restart, B→A i odrzucenie spóźnionej odpowiedzi A. Osobno świadome opt-in/opt-out rankingu z zachowaniem zgody energii. Źródło zakresu: O1-023, aktualny kontrakt/backend i skrypty infra/integration.

Zacznij od największej niewiadomej: osiągalność origin/issuer i poprawny trust z telefonu. Wykonaj mały read-only preflight, jeżeli istnieją bezpieczne wejścia; zapisz adres/zakres i neutralny wynik bez sekretów. Loopback lub curl operatorski nie dowodzi ścieżki APK. Dla braku origin/CA wpisz właściciela O3 i dokładne potrzebne wejście. O1 ma wykonać scenariusz z realnym APK; O2 odpowiada za oczekiwane HTTP/DTO i ujawnione błędy backendu. Nie próbuj wdrożenia za O3 lub pisania klienta za O1.

Rezultat: krótka instrukcja z istniejącymi komendami przygotowania, punktami stop/PASS, oczekiwanymi odpowiedziami oraz neutralnym szablonem receipt (wersje/SHA, środowisko, stan danych przed/po, wyniki i niewykonane kroki). Powtarzalna próba daje te same niezmienniki. Diagnostyka: reprodukcja → hipoteza → pomiar → jedna zmiana → ponowna próba; oddziel kod, konfigurację i harness.

## Prompt B: corpus E7-R

Przygotuj materiały według istniejącego E7_R_MANIFEST i tools/ai_reference, bez Google/uploadów, billing i obchodzenia puli. Wykonaj ograniczoną inwentaryzację repo/projektowych źródeł. Zdjęcie musi mieć rzeczywisty plik, źródło/prawa, SHA-256, kategorię/czytelność i niezależną referencję głównych składników zamrożoną przed modelem. Masa/kcal pozostają nieznane, jeżeli brak podstaw. Publiczny obraz UI ani placeholder nie jest zdjęciem jedzenia.

Docelowy przekrój30:8 produkty,8 dania mieszane,10 racje,4 nieczytelne ujęcia. Najpierw mały eksperyment z jednym publicznym źródłem mającym jawną licencję i dopasowane annotations. Jeśli mały rzeczywisty podzbiór jest dostępny i zgodny, zachowaj źródła/wersje/jednostki i przygotuj go bez dużych archiwów. Nie nadawaj kategorii lub groundtruth bez sprawdzenia. Materiały właściciela można wykorzystać po wskazaniu projektowego folderu i praw do wysyłki; nie skanuj prywatnych katalogów w ciemno.

Jeżeli brak zdjęć lub referencji, dostarcz30-slot capture_plan jawnie oznaczony jako PLAN i listę wejść. Plan nie jest runnable manifest i nie spełnia min30. Raport podaje actual_ready/pending, brakujące prawa/annotations i sposób niezależnego przeglądu. Publikuj wymagane publiczne materiały projektowe i pochodzenie; prywatne zdjęcia oraz wejścia do provider upload pozostają zgodnie z uzgodnioną retencją. Realne E7-R czeka osobno na konfigurację O3 i zatwierdzony corpus.

## Prompt C: review zgód

Przejrzyj scalony PR50 na aktualnym main: RankingConsentProtocol/HTTP/UI, SessionVault/Controller i istniejące testy, backend PUT /me/consents. Zakres: świadoma decyzja, zachowanie automatic_energy_adjustment, exact retry tego samego key/body/revision/epoch, konflikty, logout/A→B→A, off→on/restore i stale responses. Przy E9 czytaj wyłącznie konkretny aktualny seam zgód/profile; roboczy PR54 nie staje się odebranym kodem.

Uruchom tani, właściwy zestaw testów w własnej izolowanej przestrzeni, jeżeli dostępny; nie uruchamiaj pełnego emulatora lub wszystkich regresji dla samego dokumentu. Dla krytycznej reguły rozważ jedną odwracalną mutację izolowanej kopii: test musi wykryć rzeczywiste naruszenie preservation/fence. Istotne wykryte błędy mają mały przypadek regresji z niezależnym oracle; nie zmieniaj zakresu produktu bez zgłoszenia właścicielowi.

Raport wskazuje dokładne SHA, metodę/wykonane testy, wynik, uwagi i ograniczenia. Wysoka ocena wymaga argumentów, a brak badania runtime pozostaje jawny. Istotne uwagi przekaż O1 lub wykonawcy E9 z konkretnym reproduktorem; koordynator nie naprawia równolegle tego samego kodu. Fake HTTPS i dowody autora nie są własnym odbiorem rzeczywistego APK.

## Publikacja i koniec

Koordynator odbiera wyniki i ograniczenia, usuwa duplikaty opisów, zapisuje źródła i krótki bieżący stan z właścicielami. Aktualizuje jeden wpis O2-029 oraz własny wiersz w KOMUNIKACJA_AGENTOW. Prompty i rezultaty trafiają do jednego PR; zachowaj cudze zmiany przy zwykłym merge aktualnego main. Commit `agent 2: <konkretny wynik>`, diff-check i kontrole adekwatne do dokumentacji/materiałów. Wszystkie aktualnie wymagane joby/ci-required oraz osobny main po merge mają rzeczywisty wynik; nie obchodź ochrony ani O3 CI.

Gotowy pakiet przygotowania może zostać odebrany mimo konkretnego braku origin lub części zdjęć, pod warunkiem że brak jest dokładnie rozliczony i żaden test/corpus/full-path PASS nie został wymyślony. Pełne APK/API i min30/live E7-R zamykają się dopiero na własnych wymaganych dowodach. Przy wejściu zależnym od właściciela zapytaj wcześnie i wykonuj niezależne zadania dalej.

Dostarczane rezultaty: [scenariusz APK/API](integracja/ODBIOR_APK_API_O2.md), [przegląd zgód](integracja/RECENZJA_ZGOD_O2.md) i [materiały E7-R](../Random%20Data/AI_REFERENCE_E7_R_2026-10-13/README.md). Krótki aktualny stan oraz następne wejścia pozostają w [jedynym dzienniku](KOMUNIKACJA_AGENTOW.md).
