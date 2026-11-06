# Developerski APK i Gemini — okno 5 listopada 2026

Agent 1. Źródło badanej aplikacji: main `5f9112e3b82d2d9536e069cb5f1a863f7567c990`,
Android 0.8.47.validation / 1058 / Room27. To raport rzeczywistej próby,
nie potwierdzenie zakończenia E7-R, E9 lub wydania 1.0.

## Wynik

Publiczne PKCE, bootstrap/pełna kopia, wybór zdjęcia i pojedynczy upload przez
aplikację zostały wykonane. `countTokens` zakończył się poprawnie, lecz
`generateContent` zwrócił **HTTP503**. Analiza zakończyła się
`provider_result_unknown`. **Rozpoznawanie przez ten APK nie otrzymało PASS.**
Nie powtórzono uploadu pod nowym UUID, nie zmieniono projektu, klucza, puli,
epoki ani zachowanej historii. Worker zatrzymano. Późniejszy ręczny wpis
i jego synchronizacja są osobnym pozytywnym wynikiem.

[Odbiór backendu z 4 listopada](ODBIOR_GEMINI_DEV_2026_11_04.md) pozostaje
oddzielnym dowodem. Jego wcześniejszy sukces nie kwalifikuje tej nowej analizy.
Instalacja MOCK dostarczona przez Agenta 3 pozostała niezależna.

## Tożsamość artefaktów i poprawka operatora

Badany APK ma SHA-256
`50a4345c72648425be68a0823bae75cb4cfd2a51fb36187bc16b3bb3c87eb7e8`.
Jego publiczny API base kończy się wymaganym `/api/v1`.

Wcześniejsze APK `739e13c6…` i `7abd7757…` otrzymały błędny parametr operatora:
sam origin bez `/api/v1`. Ich kontrola zgodności zasobów z tym parametrem nie
była odbiorem konfiguracji API. Zachowano artefakty i niezaliczoną próbę.
Poprawny operator build przebudował wyłącznie zasoby, w 2m43s, zachowując
identyczne DEX względem `739e13c6…`. Źródła Androida nie zmieniły się.
Domyślne test APK `9499361a…` skopiowano bajtowo, bez jego ponownego wykonania.

Zwykła aktualizacja zachowała własną instalację, konto i Room. Nie czyszczono
danych. Publiczny CA zainstalowano wcześniej przez Ustawienia Androida,
bez roota, pomijania ostrzeżeń TLS lub zmiany magazynu zaufania Windows.
Logowanie odbyło się przez prawdziwy formularz Keycloak i AppAuth callback;
nie wstrzykiwano sesji ani tokenów. Pierwsze anulowane logowanie pozostawiono
w dowodach; późniejsze prawidłowe logowanie nie zmienia jego wyniku.

## Przepływ zdjęcia i zamknięcie próby

Użyto wyłącznie wcześniej zatwierdzonego publicznego zdjęcia jabłka USDA,
z [raportu backendu](ODBIOR_GEMINI_DEV_2026_11_04.md). Systemowy Photo Picker,
przygotowanie lokalnej kopii i jawna zgoda na to zdjęcie poprzedziły upload.
Nie wysłano innych fotografii ani historii dziennika.

GET metadanych modelu HTTP200 potwierdził dostęp do modelu, nie jego bieżącą
zdolność generowania, limity lub billing. Obowiązywało datowane potwierdzenie
właściciela: test developerski Free Tier bez billing i 15 RPM / 250000 TPM /
500 RPD. Klucz pozostał wyłącznie w prywatnej konfiguracji backendu.

Normalny API i worker miały ten sam obraz oraz zachowaną wspólną historię.
Terminalny generate503 zapisano bez automatycznego retry. Końcowe liczniki:

- 6 analiz: 4 failed i 2 succeeded, w tym wcześniejsze wyniki backendowe;
- 12 attempts: 6 countTokens OK, 3 generate denied, 2 generate OK,
  1 generate UNKNOWN;
- 0 niedomkniętych IO i 0 zajętych permits;
- 1 wcześniejsza decyzja AI; nowa nieudana analiza nie materializowała posiłku.

## Ręczny fallback, ACK i PULL

Przez istniejący ekran ręcznego produktu zapisano jawny przykład testowy:
jabłko, 100 g, 52 kcal/100 g. Porcja nie była ważona; wpis nie jest wynikiem AI.
Makra pozostawiono **NULL**, a aplikacja pokazała brak danych zamiast zera.

Zwykła synchronizacja otrzymała `accepted` dla jednego Meal oraz jednego
prywatnego `product_draft`, oba revision1, przy tym samym owner/epoch.
Stary posiłek pozostał revision1. Łącznie były dwa posiłki, bez duplikatu.
Prywatny szkic nie został automatycznie opublikowany w katalogu.

Odczyt zachowanej kopii rzeczywistej Room27 potwierdził dokładny payload
nowego posiłku w zarchiwizowanej przyrostowej stronie PULL i jego projekcji.
Czasy porównano jako chwile UTC. Strona miała trzy rekordy; całkowite pięć
zmian serwera obejmowało też dwa pochodne `diary_day`. Zachowano wcześniejsze
odmowy obserwatora spowodowane kodowaniem UTF-8 i błędnym oczekiwaniem
liczby zmian; nie przypisano im PASS.

## Uruchamianie i ograniczenia dowodu

W próbie online obserwowano ANR aplikacji/System UI przy presji RAM.
Zachowany pierwszy `lastanr` nie zawiera stosu ANR, tylko „no ANR since boot”.
Nie jest podstawą diagnozy przyczyny.

Osobny pojedynczy zimny start tego samego APK offline, bez Dockera/backendu
i UI automatora: MRE_READ trwał 20,033s na wątku tła, a START→RENDER
ready=true 21,773s. ActivityManager nie zapisał ANR. Zrzut bezpośrednio po
logu gotowości nadal pokazywał ładowanie. Log pochodzi z Compose SideEffect;
nie dowodzi zaprezentowania klatki. **Formalny startup PASS pozostaje otwarty.**
Nie podniesiono timeoutów testu ani nie wyłączono guardów.

## Dowody i zamknięcie zasobów

Prywatne dowody zawierają identyfikatory i dane kont; nie są publikowane.
Bezpieczne sumy SHA-256:

| Dowód | SHA-256 |
|---|---|
| końcowy receipt zamknięcia | `7c066292efdbec11cc5448118d5e56ea53341f939d5a38f6872d9b5d55b21560` |
| terminalny błąd analizy | `72b6d6fb5e801ca59431c9be6918df89f54c79090b07ee0864f754a3c7769e0f` |
| bezpieczny log workera | `be985d0099b0fe724fd07add07cd0355996adc475344672f9b23b2b06c8364dd` |
| zarchiwizowana strona PULL | `bde0f7d2f412b8c93d10a1bad423fa47a386265d40525e253ebd24d58b21f583` |
| log zimnego startu offline | `f7901b763e6864aee5a797b0d1c174b46b5b2b7871ff72d5416620f11490bb7c` |
| zrzut po logu ready | `9d2a612bb7a65fa4f50c08f419ca369f58c1434780f383958daab997e91f24e3` |

Własny emulator, dedykowany ADB i usługi zatrzymano, zachowując dane.
Docker Desktop zakończył pracę. Na osobne polecenie właściciela zatrzymano
dziewięć kontenerów laboratoriów i ustawiono `restart=no` — **nie przywracać**.
Nie restartowano komputera.

## Następny zakres

Nowa zmiana prezentacji w `codex/android-gemini-apk` wyjaśnia terminalne błędy
AI i przy takim wyniku udostępnia istniejący ręczny edytor bez zależności od
sesji lub internetu. Nie pokazuje błędu jako gotowego szacunku i nie inicjuje
nowego uploadu. To kod późniejszy niż badany APK50a; nie przypisujemy mu
wyników zainstalowanego starszego artefaktu.

Wąska kompilacja trzech zmienionych plików produkcyjnych i nowego testu UI
przeciw odebranemu main5f9112e: PASS, JVM384MB, 14,265s. Dwa nowe przypadki
UI są skompilowane, **jeszcze niewykonane**. Nowego APK, formalnego odbioru
startu, nowego sukcesu Gemini, E7-R i E9 live nie deklarujemy. Kolejnego
wywołania nie wolno użyć do obejścia terminalnej niepewności tej samej próby.
