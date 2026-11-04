# Gemini — przekazanie dla Kamila

Stan sprawdzenia: 4 listopada 2026. Dokument opisuje ostatni zewnętrzny etap
zaakceptowanej edycji lokalnej MRE/DEMO. Do czasu jego osobnego odbioru działają
MOCK i ręczne wpisy; w tej instalacji nie wykonano konfiguracji Google ani
połączenia live.
Klucz nie jest całym wdrożeniem: potrzebne są zgodny zakres użycia, rzeczywiste
limity projektu, wspólna pula E7/E9, aktualne zgody i dowód działania przez aplikację.
Nie zmieniamy tej edycji w publiczny hosting, ARPOL lub pełne wydanie produkcyjne.

Osobny [PR #203](https://github.com/Roseru/aplikacja-mobilna/pull/203) O1 opisuje
deweloperski odbiór backendu Gemini na jednym zdjęciu oraz poprawkę schematu
dostawcy do `food-photo-schema-v2`. Nie jest to odbiór APK, E7-R ani zmiana
tej instalacji MOCK. PR scalono do main `1aee090` po ośmiu zielonych kontrolach
[CI41794971737](https://github.com/Roseru/aplikacja-mobilna/actions/runs/41794971737).
Ten dokument nie potwierdza niezależnie prywatnego smoke testu. Przed oknem
Kamil przypina aktualny odebrany main zawierający tę poprawkę i przygotowuje
z niego normalny obraz backendu. Obrazy dotychczasowej instalacji MOCK mają
własne zachowane piny; konfiguracja Gemini wymaga odbioru nowych obrazów/profilu.

## Najpierw decyzja o zakresie

Polska jest na [liście dostępnych regionów Google](https://aistudio.google.com/docs/available-regions).
Jednocześnie [warunki Gemini API](https://aistudio.google.com/docs/terms#use-restrictions)
wymagają Paid Services przy udostępnianiu klientów API użytkownikom w EOG,
Szwajcarii i Wielkiej Brytanii. Dostępność regionu i Free Tier nie usuwają tego
warunku. Warunki wymagają również pełnoletniości i ograniczają aplikacje
kierowane do osób niepełnoletnich. To nie jest zgoda na użycie medyczne.

Obecny kod świadomie dopuszcza live tylko w `ENVIRONMENT=development` i wymaga
`free_only=true`, `billing_disabled=true`, `development_only=true`. Zatem
**udostępnienie darmowego Gemini użytkownikom w Polsce jest zablokowane**.
Nie obchodzimy tego zagranicznym projektem, innym kluczem lub zmianą flagi.
Wyjątek dotyczący przetwarzania danych w EOG w tych samych warunkach nie zmienia
wymogu Paid Services przy udostępnianiu aplikacji.

Kamil z właścicielem ustalają przed oknem, czy chodzi wyłącznie o dopuszczony
wewnętrzny test deweloperski na niewrażliwych danych. Nie zakładamy automatycznie,
że nazwanie testu „demo” rozstrzyga warunki. Jeżeli celem jest używanie funkcji
przez użytkowników w EOG, potrzebna jest osobna decyzja właściciela o zmianie
dotychczasowego zakazu billing oraz nowy, sprawdzony kontrakt konfiguracji.
Ta procedura nie włącza płatności i nie zawiera płatnego fallbacku. Przy braku
zgodnego zakresu zamykamy etap wynikiem `BLOCKED_SCOPE`, pozostawiając MOCK.

## Co Kamil przygotowuje przed oknem

| Wejście | Konkretne wymaganie |
|---|---|
| Dostęp do projektu | Jeden istniejący projekt i jeden stabilny environment ID; potwierdzone uprawnienia do konfiguracji oraz brak billing. Nie twórz projektów do obchodzenia limitów. |
| Model i tryb | Dokładnie `gemini-3.5-flash-lite`, Standard REST v1beta. [Karta modelu](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite) potwierdza wejście obrazu i structured output; [cennik Standard](https://aistudio.google.com/docs/pricing#gemini-3.5-flash-lite) pokazuje bezpłatne wejście/wyjście. Odczytaj je ponownie w dniu konfiguracji. Nie podstawiaj `latest`, Batch, Flex, Priority lub grounding. |
| Limity | Datowany odczyt rzeczywistych RPM/TPM/RPD i dodatkowych wymiarów z właściwego projektu w AI Studio. [Google](https://aistudio.google.com/docs/rate-limits) stosuje limity do projektu, nie klucza; RPD odnawia się o północy Pacific. Wartości mogą się zmieniać i nie są gwarancją pojemności. Liczby mocka nie są limitami Gemini. |
| Sekret | Klucz dostarczony wyłącznie do prywatnej konfiguracji backendu/workerów. Bez klucza w APK, czacie, repo, argv, CI, zrzutach ekranu i raporcie. |
| Potwierdzenie | Prywatny UTF-8 JSON `AI_LIVE_CONFIRMATION`, do 16 KiB, zgodny dokładnie z [E7 — Gemini dev](e7/KONFIGURACJA_O3.md#gemini-dev-wymagane-datowane-wejścia): identyfikatory, model, rzeczywista data ze strefą, cztery potwierdzenia bool, RPM/TPM/RPD, potwierdzone `quota_windows`. Nie kopiuj przykładowych limitów jako faktycznych. |
| Dane i zgody | Konkretne niewrażliwe zdjęcie dopuszczone do wysłania do Google, aktualne photo notice i zgoda `this_photo`. Osobno zgoda na test referencyjny; zgoda na dziennik nie jest zgodą na corpus. |
| Odpowiedzialność | Kamil potwierdza zakres i zewnętrzne wejścia, operator prowadzi backend i piny, właściciel przyjmuje wynik. Tylko jeden operator zmienia instalację w oknie. |

Nie wymagamy od Kamila przesłania sekretów razem z potwierdzeniem dostępności
projektu. Sam dokument potwierdzenia również przechowujemy prywatnie. Aktualny
szablon zmiennych jest w [backend/.env.example](../backend/.env.example).

## Jedno kontrolowane okno konfiguracji i testu

Okno otwieramy dopiero po przygotowaniu wszystkich powyższych wejść i przyjęciu
zakresu użycia. Poniższe kroki wykonuje operator; nie są listą poleceń do
uruchomienia na obecnym MOCK bez odbioru. Zmiany wymagają nowych pinów i nowego
profilu, ponieważ dotychczasowy profil wiąże konfigurację i kontenery MOCK.

1. **Zabezpieczenie.** Odczytaj bieżącą epokę i dane, zanotuj piny usług i
   klientów. Wykonaj sparowaną kopię procedurą `START → BACKUP` z
   [LOCAL_RELEASE](../infra/integration/LOCAL_RELEASE.md), zweryfikuj archiwum.
   BACKUP pozostawia PostgreSQL running oraz gateway i wszystkich writerów
   zatrzymanych. Nie wykonuj restore lub resetu epoki, aby skonfigurować provider.
   Potwierdź fizyczny brak poprzedniego IO/held permits; brak pewności zamyka okno.
2. **Backend i pula.** Ustaw tę samą konfigurację API oraz istniejącego AI workera:
   `ENVIRONMENT=development`, `AI_PROVIDER=gemini`, `AI_PROJECT_ID`,
   `AI_ENVIRONMENT_ID`, `AI_MODEL=gemini-3.5-flash-lite`, prywatny
   `GEMINI_API_KEY` i czytelną wewnątrz właściwych kontenerów ścieżkę
   `AI_LIVE_CONFIRMATION`. Zachowaj prywatny `AI_PHOTO_ROOT`, prawa i role.
   API nadal używa API LOGIN, worker tylko AI LOGIN; configure-pool ma kontekst
   migratora. Sekret trafia jedynie do procesów backendu, które go potrzebują.
3. **Konfiguracja istniejącego limitera.** W tym samym środowisku, z właściwym
   migratorem, wykonaj istniejące polecenie:

   ```text
   python -m calorie_app.modules.ai.cli configure-pool --epoch CURRENT_UUID
   ```

   `CURRENT_UUID` pochodzi ze źródła, nie z kopii lub starego raportu. Polecenie
   nie kontaktuje się z Google; zapisuje potwierdzone limity. Sprawdź zgodność
   manifestu i `ai_pools`, jeden project/environment oraz wspólną pulę zdjęć
   i energii. Nie resetuj `attempts`, admissions, permits, receipts ani historii.
   Lokalny limiter rezerwuje jeden request i 10240 tokenów na **każde**
   countTokens/generateContent. Zaplanuj miejsce na co najmniej oba wywołania
   zdjęcia i dozwolone retry; nie zmniejszaj budżetu, aby wymusić test.
4. **Nowe przypięcie.** Operator kontrolowanie odbiera nowe ustawienia/kontenery
   na tej samej bazie i wolumenach, zachowując konta, epokę i dane. Tworzy NOWY
   profil `bind --provider gemini` z pełną odebraną Compose chain. Nie edytuje
   starego profilu, nie importuje realm, nie uruchamia provisioning/migracji
   i nie używa codziennego START do automatycznego przyjęcia driftu.
   Po odbiorze sprawdza HTTPS/issuer, workery, capabilities, profile/notice oraz
   brak niespodziewanych producentów. Automat E9 pozostaje wyłączony.
5. **Jeden rzeczywisty przypadek zdjęcia.** Przez istniejącą aplikację/API i tę
   samą kolejkę przyjmij jedną zatwierdzoną fotografię z aktualną zgodą.
   Potwierdź konkretną analysis/job/operation, countTokens i generateContent,
   walidację odpowiedzi, propozycję i ręczną decyzję użytkownika. Sprawdź
   zatwierdzenie lub ręczny fallback do dziennika oraz zwykły ACK/sync; wcześniej
   zapisane posiłki, cel i historia muszą pozostać zachowane. Odpowiedź Google
   sama nie zapisuje posiłku ani oficjalnego produktu. Nie wysyłaj ponownie po
   timeout/lost ACK: najpierw odczytaj tę samą operację/receipt. Unknown/daily
   429/safety/missing config kończy próbę bez nowego UUID lub zmiany projektu.
6. **Odbiór i zamknięcie.** Zapisz prywatnie datę, commit, nowy profil SHA,
   model/profile, epokę, konkretne operation/job/attempt IDs, wynik użytkownika,
   zużycie/rezerwacje i brak fizycznego osieroconego IO. Raport do przekazania
   zawiera wyłącznie te bezpieczne metadane i hashe, bez sekretów/zdjęć/raw
   odpowiedzi. Przy błędzie zatrzymaj dalsze zadania i zdiagnozuj ten przypadek;
   zachowaj rezerwacje i dowody. Powrót do MOCK to osobno odebrana konfiguracja
   z nowym profilem, bez restore lub kasowania ledger. Po sukcesie właściciel
   przyjmuje wyraźnie zakres: integracja live jednego przypadku.

## Kiedy wolno powiedzieć „Gemini odebrane”

Pojedynczy przypadek potwierdza połączenie i przepływ aplikacji. Nie potwierdza
trafności na zbiorze ani automatycznie całego E7-R. [Istniejący corpus](<../Random Data/AI_REFERENCE_E7_R_2026-10-13/README.md>)
ma 30 propozycji w przekroju 8/8/10/4, ale zapisane przyjęcia człowieka, zgody
dla providera i uploady wynoszą zero. Kamil i osoba oceniająca muszą zamknąć te
wejścia przed pierwszym testem referencyjnym.

Pełny odbiór stosuje [manifest E7-R](e7/E7_R_MANIFEST.md) i
[istniejący runner](../tools/ai_reference/README.md), przez API aplikacji.
Minimum: 30 zatwierdzonych różnych zdjęć, co najmniej 24/26 poprawnych
identyfikacji czytelnych przypadków i 100% ręcznego fallbacku dla wykonanych
przypadków. Brak błędnych struktur to brak obserwacji, nie wynik PASS 0/0.
Runner kończy `MANUAL_REVIEW_REQUIRED`, nie końcowym PASS; człowiek uzupełnia
odbiór aplikacji i fallbacku. Limit 10 zdjęć/konto/dzień UTC oznacza dla jednego
konta co najmniej trzy dni testów, dodatkowo ograniczone rzeczywistą pulą.
To trzeba uwzględnić w uzgodnionym harmonogramie tego etapu; nie tworzyć kont
lub resetów w celu obejścia limitów.

E9 korzysta z tej samej puli, lecz ma oddzielną zgodę/notice i kwalifikację
historii: minimum 10 kompletnych dni w oknie 14 dni i pomiary wagi w czterech
dniach, po dwa w każdej połowie. Brak historii oznacza poprawną odmowę analizy,
nie powód do sztucznego dopisywania historii bieżącego konta. Odbiór live E9
wymaga uzgodnionego kwalifikującego się konta i agregatów; automat nadal off.
Obowiązuje [konfiguracja E9](e9/KONFIGURACJA_O3.md), bez drugiej puli lub
samodzielnego stosowania wyniku modelu. Jeżeli test obejmował wyłącznie zdjęcie,
raport pozostawia live E9 jako niewykonane.

Końcowy komunikat do Kamila/właściciela rozróżnia: **lokalny MRE/DEMO odebrany**,
**integracja live odebrana lub zablokowana**, **E7-R/E9 live wykonane lub
niewykonane** oraz **udostępnianie w EOG niedopuszczone w obecnym free-only
kontrakcie**. Żaden z tych statusów nie wynika z samego posiadania klucza.
