# Prywatne przekazanie Gemini development do O3

Wybrany wspólny scope E7/E9: `project_id=181003336626`,
`environment_id=calorie-dev-e7-e9`, `model=gemini-3.5-flash-lite`.
Nie tworzyć innego environment dla E9, rotacji klucza lub ponowienia.
Numer projektu pochodzi z O1-044/045. O2 potwierdza przypisanie numeru jako
identyfikatora backendu; nie dopisujemy nieznanego slug project ID.

O1 przekazał ręczny odczyt panelu z 14.10.2026: RPM15, TPM250000, RPD500.
Potwierdzenie Free Tier nie zostało automatycznie zamienione na
`billing_disabled=true`. O1 sprawdza i potwierdza brak aktywnego billing oraz
powiązanie klucza/modelu/limitów z tym projektem. O3 ogranicza instalację do
`ENVIRONMENT=development`. Brakujące potwierdzenie pozostaje blokadą.

## Pliki O1

Przygotować poza checkoutem i OneDrive dwa pliki: `gemini-key.txt` z samym
kluczem oraz `confirmation.json` dokładnego formatu z
[KONFIGURACJA_O3](KONFIGURACJA_O3.md#gemini-dev-wymagane-datowane-wejścia).
Wstawić powyższy project/environment/model i rzeczywiste limity, datę potwierdzenia
ze strefą oraz wyłącznie faktycznie potwierdzone flagi. `quota_windows={}` pozostaje
poprawne, gdy nie znamy dodatkowych quota IDs; wtedy unknown/daily429 jest terminalne.
Nie kopiować flag true jako przykładu. Klucz po ujawnieniu w rozmowie wymienić
przed trwałym wdrożeniem. Żaden krok poniżej nie kontaktuje się z Google.

Z checkoutu zawierającego [helper](../../infra/integration/secret_handoff.py):

```powershell
# Zmienne wskazują istniejące prywatne źródła i nowy, nieistniejący katalog.
uv run --project backend --locked python infra/integration/secret_handoff.py prepare --directory "$Transfer" --host 192.168.137.29 --manifest "$Manifest" --key "$KeyFile"
```

Helper zakłada ACL użytkownika/SYSTEM, sprawdza konfigurację rzeczywistym parserem
backendu, scope i limity. Brak potwierdzonych flag blokuje paczkę. Nie zmienia
puli, liczników, backendu, zgód ani capabilities. `payload.zip` zawiera sekret:
nie publikować ZIP, manifestu prywatnego, klucza ani klucza TLS w repo/PR/release.

## Wysłanie do jednorazowego odbiornika O3

O3 publikuje **nowe** okno i konkretny peer w jedynym dzienniku komunikacji.
Bieżące okno nie jest przedłużeniem kanału kont A/B. Dla obecnej sieci:
TCP `192.168.137.1:18446`, tożsamość TLS `192.168.3.162`, odbiorca O1
`192.168.137.29`; publiczny CA jest w posiadanym pakiecie APK/API `tls/ca.pem`.
Po zmianie adresu O1 najpierw zgłasza nowy adres, bez rozszerzania peer.

```powershell
uv run --project backend --locked python infra/integration/secret_handoff.py send --directory "$Transfer" --host 192.168.137.1 --identity 192.168.3.162 --port 18446 --ca "$Bundle/tls/ca.pem"
```

O3 wykonuje `receive` z własnym istniejącym certyfikatem/key, exact peer i
nowym prywatnym katalogiem. Odbiornik ma skończony termin (maksymalnie godzina),
przyjmuje jeden poprawny POST i zamyka port. Sprawdza długości, allowlist nazw,
parser i wszystkie potwierdzenia. Brak kluczy w URL/argumentach/odpowiedziach/logach.
TLS i oryginalna tożsamość są weryfikowane; zmiana adresu TCP nie zmienia TLS.
Nie stosować `-k`, publicznego release ani ponownego kanału kont.

`receiver_confirmed` oznacza prywatny odbiór i walidację; **nie oznacza wdrożenia**.
O1 wpisuje tylko czas i wynik. O3 po własnym odbiorze przygotowuje jeden pool,
ACL/storage/worker i zgodne limity API/E7/E9 z zachowaniem liczników/epoki.
Realne generowanie i odbiór zdjęć są osobnym etapem z właściwymi zgodami.

Alternatywa, gdy kierunek O1→O3 jest niedostępny: helper ma bounded `serve/fetch`
HTTPS z nowym publicznym certyfikatem i jego SHA256; sekret nadal nie trafia do Git.
Wymaga osobno uzgodnionych adresów/okna, nie automatycznej zmiany zapory.
