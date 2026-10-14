# Zabezpieczenia GitHuba i aktualizacje zależności — O3

Odczyt i zmiana operatora: 14.10.2026, 16:16–16:22 CEST, repozytorium
`Roseru/aplikacja-mobilna`. Źródła konfiguracji: rzeczywisty REST API GitHuba
i [dependabot.yml](../.github/dependabot.yml). To odbiór ustawień i dostawa
konfiguracji; wykonanie aktualizacji przez bota wymaga jej obecności na main.

## Potwierdzone ustawienia repozytorium

| Ustawienie | Stan po zmianie | Weryfikacja |
|---|---|---|
| Secret scanning | enabled | PATCH200 i ponowny GET repozytorium |
| Secret scanning push protection | enabled | PATCH200 i ponowny GET repozytorium |
| Dependency graph / Dependabot alerts | enabled | PUT204, następnie GET204 |
| Dependabot security updates | enabled, paused=false | PUT204, następnie GET200 |
| Ochrona main | zachowana | GET200 przed/po; porównanie ustawień identyczne |

Wcześniejszy odczyt pokazał wyłączenie wszystkich czterech funkcji.
Zmiana dotyczyła tych ustawień publicznego repozytorium. Nie włączano
produktu GitHub Advanced Security lub Code Security.

Ochrona main wymaga PR, aktualnej bazy (`strict=true`) i `ci-required`
z aplikacji GitHub Actions15368. Agregator istniejącego Project CI wymaga
sukcesu siedmiu jobów; razem sprawdzamy osiem wyników. Administratorzy
podlegają ochronie, wymagane jest rozwiązanie rozmów, force-push i usuwanie
main są wyłączone. Decyzja właściciela o opcjonalnym review pozostaje:
0 wymaganych zatwierdzeń, `require_last_push_approval=false`.

Odczyt16:53 CEST: oba endpointy open alerts odpowiedziały200 i zwróciły0
otwartych alertów sekretów/zależności (limit100, puste listy).
Endpoint historii skanów odpowiedział404; nie przypisujemy temu odczytowi
potwierdzenia kompletnego skanowania historii.

## Automatyczne propozycje aktualizacji

Konfiguracja obejmuje rzeczywiste manifesty repozytorium:

| Ekosystem | Katalogi | Cykl Europe/Warsaw |
|---|---|---|
| uv | backend, tools/contracts; pyproject.toml i uv.lock | poniedziałek08:00 |
| Gradle | android; pliki Kotlin DSL | poniedziałek09:00 |
| GitHub Actions | .github/workflows | poniedziałek10:00 |
| Docker | backend/Dockerfile, infra/integration/Keycloak.Dockerfile | poniedziałek11:00 |
| Docker Compose | infra/local i infra/integration | poniedziałek12:00 |

W każdym wpisie ustawiono limit2 otwartych PR aktualizacji wersji.
Wersje minor/patch są grupowane, a major pozostają osobnymi propozycjami.
Automatyczne aktualizacje bezpieczeństwa są odrębną włączoną funkcją GitHuba.
Ten PR nie aktualizuje żadnej biblioteki, obrazu lub akcji.

Aktualizacje przechodzą ten sam PR → końcowy head/osiem kontroli → merge →
osobny odbiór main. Nie dodano auto-merge. O3 sprawdza zgodność pełnych SHA
akcji, digestów obrazów i powielonych odniesień w Dockerfile/workflow/Compose;
bot może zaproponować zmianę tylko części takich odniesień. O1/O2 rozliczają
zmiany swojego kodu, migracji i kontraktów. Nie wolno osłabiać testów lub
zmieniać istniejących danych, aby przyjąć aktualizację.

Po scaleniu O3 odczytuje rzeczywisty job aktualizacji Dependabota i ewentualne
PR. Sama poprawna składnia YAML lub aktywne security updates nie dowodzą
wykonania harmonogramu aktualizacji wersji. Brak dostępnej nowszej wersji
nie jest błędem, jeśli job faktycznie wykonał poprawny odczyt manifestów.

## Sekrety i nowe wejście Gemini

Klucze, hasła, private keys, tokeny, stan kont, DB/WAL i prywatne zdjęcia
pozostają poza Git, PR, Actions artifacts oraz APK. Włączony skaner uzupełnia
te zasady. Przy blokadzie pusha sprawdź dokładny wskazany plik/commit i usuń
sekret z proponowanej zmiany; rzeczywisty ujawniony klucz wymaga rozliczenia
z właścicielem właściwego dostępu.

Właściciel14.10 przekazał A1 utworzenie projektu i klucza Gemini.
A1 dostarcza O3 prywatnie klucz oraz dowód projektu bez aktywnego billing,
datę odczytu, dokładny model i rzeczywiste RPM/TPM/RPD/dodatkowe limity.
Nie wpisuje klucza do wspólnego dziennika i nie umieszcza go w Androidzie.
O3 zachowuje odpowiedzialność za weryfikację manifestu, jeden wskazany
development runtime, wspólną pulę E7/E9, storage/worker i własny live receipt.
Warunki i pola opisują [E7](e7/KONFIGURACJA_O3.md#gemini-dev-wymagane-datowane-wejścia)
i [E9](e9/KONFIGURACJA_O3.md#bramki-zewnętrzne). Datowanych limitów projektu
nie zastępujemy przykładowymi liczbami mocka lub samym cennikiem dostawcy.

## Źródła techniczne

- [REST: ustawienia repozytorium i funkcje bezpieczeństwa](https://docs.github.com/en/rest/repos/repos#update-a-repository).
- [REST: Dependabot alerts](https://docs.github.com/en/rest/repos/repos#enable-vulnerability-alerts).
- [REST: security updates](https://docs.github.com/en/rest/repos/repos#enable-dependabot-security-updates).
- [Opcje Dependabot](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).
- [Obsługiwane ekosystemy](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories).
