# Odbiór APK/API O1 — uzupełnienie R3, 19.10.2026

Identyfikator: `O1-O3-APK-API-20261019-R3`. O1/agent1 we współpracy z O3.
Nowe, osobne okno: **09:06:26.320467–09:26:26.320467 Europe/Warsaw**.
R3 uzupełnia cztery odczyty oznaczone NOT_RUN w [historycznym raporcie R2](ODBIOR_APK_API_O1_R2_20261019.md).
Nie powtarza ani nie zmienia zaliczonego oracle późnego GET/logout z R2.

## Tożsamość i przebieg

Istniejący O1Api35/API35, bez instalacji lub kasowania danych:
0.8.12.validation/code1023/Room9, źródło
`e319e53130020b3bbcdb50588ef4a2205a241118`.
APK SHA-256 `89164efd5199c8e1329f4fc833107a4045d034533ded6ef0e93f00996c50efcb`,
driver SHA-256 `91b788998c3aa20b928e65e3f4d63a5ff3ad9048cc3de8c70f5ba8b86ecc231f`.
O1 zweryfikował zainstalowane pliki i wykonał świeży check TLS/discovery200/readiness200,
nowego własnego klienta i nowy lease. O3 zachował issuer/CA, schema24 i obraz
wskazane w R2; nie przypisujemy nowego main lub locka do tej instalacji.

Wykonano rzeczywisty PKCE do B, zakończony bootstrap, zwykły GET profilu,
a po jego ukończeniu GET motywacji. Następnie jawny PKCE z B do A i ta sama
para odczytów. Każdy wynik ma nowy request ID/czas, ukończony podgląd DTO
oraz kontrolę kontekstu. Nie użyto starych metadanych jako nowej próby.

## Cztery świeże odczyty

| Konto / ścieżka | UTC 19.10.2026 | X-Request-ID | Wynik |
|---|---|---|---|
| B `/api/v1/me` | 07:14:36.096630Z | `878bdebc-ae56-41be-a4ab-4318753626ba` | 200 / no-store / DTO przyjęty / kontekst zgodny |
| B `/api/v1/me/motivation` | 07:16:08.181707Z | `96ad1f47-69e4-4f49-b235-4b72ba41da6c` | 200 / no-store / DTO przyjęty / kontekst zgodny |
| A `/api/v1/me` | 07:20:36.086847Z | `8c4fe2d3-bba7-4c40-9da2-0dc9b3d8c94a` | 200 / no-store / DTO przyjęty / kontekst zgodny |
| A `/api/v1/me/motivation` | 07:21:35.538478Z | `ac59c840-79fe-4af1-8154-c5fa48711dc3` | 200 / no-store / DTO przyjęty / kontekst zgodny |

**4/4 odczyty zaliczone.** Dla `/me` porównanie dotyczy `account_id` i
`sync_epoch`; ten DTO nie zawiera `account_generation`. Oba profile były
prawidłowo puste (`null`). Dla `/me/motivation` kontrolowane są
`account_generation` i `sync_epoch`.

Dowód zgodności kontekstu opiera się na dokładnym, niezmienionym źródle
klienta: `SessionController.readPrivate` sprawdza powiązanie, właściciela,
lease oraz wymienione pola przed przyjęciem odpowiedzi, a `publish` usuwa
podgląd niezgodny z bieżącym kontekstem. Rzeczywisty ukończony DTO pozostał
widoczny pod tymi guardami. Nie eksportowano tożsamości lub body odpowiedzi.
O3 zaakceptował ten sposób dowodu dla pary B w bieżącej koordynacji.

Motywacja pokazała gotowy wynik serwerowy. Nie generowano własnych zer
zamiast brakujących danych. W B widoczne były znane punkty i „Potwierdzone
przez serwer”; komunikatu niedostępnych punktów nie było również w A.
Nie wymuszano syntetycznej odpowiedzi pending/null w tej próbie. Akceptacja
pustego profilu nie jest testem wszystkich możliwych stanów motywacji.

Pierwsza obserwacja motywacji B nie zastała przycisku odświeżania po
powiększeniu karty. Ukończony DTO i unikalny świeży receipt potwierdzono
bez powtórzenia żądania; nie traktowano braku widocznej kontrolki jako błędu API.

## Dane i zamknięcie

Przed R3 wykonano nowy prywatny baseline wszystkich23tabel Room9.
Po parze B oraz po parze A **15/15 tabel danych lokalnych identycznych**
z baseline: dziennik/pozycje, cele, outbox, katalog/racje, profil, waga,
dni i szkice zdjęć. FK clean, B ma odrębnego właściciela, A wróciło do
pierwotnego właściciela, a generacje lease rosły. Nie deklarujemy
niezmienności metadanych logowania, które zmieniają się zgodnie z tym testem.

O1 zamknął własny R3 lease/NAT/reverse i klienta o
**`2026-10-19T07:22:20.2290396+00:00`** (09:22:20 CEST), przed końcem okna.

Zachowano APK/driver, dane i prywatne dowody poza Git/OneDrive; usunięto
własny tymczasowy zrzut UI z AVD. O3 potwierdził w bieżącej koordynacji
zamknięcie własnego relay o09:23:43.3603175 CEST po sprawdzeniu własności
procesu i braku aktywnych połączeń. To wcześniejsze
`OWNER_STOP_AFTER_PEER_DISCONNECT`, a nie automatyczny koniec TTL.
Po zamknięciu O3 potwierdził brak listenera/połączeń18444, świeże
HTTPS/readiness/discovery200, issuer/CA/schema24/obraz i wymagany monitoring.
Nie restartowano komputera.

Bez importu gościa, push dziennika, zmian zgód, Nemesis lub Gemini,
wdrożenia nowego backendu i zmiany epoki. Ten wynik uzupełnia konkretną
parę odczytów dla dwóch kont; nie zamyka całego E4/E7, recovery/retencji
lub KO32. Lokalny nowy0.8.23/Room14 i jego320testów stanowią osobny odbiór.
