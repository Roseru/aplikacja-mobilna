# Odbiór APK/API O1 — 19.10.2026, R2

Identyfikator: `O1-O3-APK-API-20261019-R2`. Agent 1/O1, we współpracy z O3.
Okno O3: 08:28:41–08:58:41 Europe/Warsaw. Ten raport opisuje wykonane próby;
nie zamyka całego E3/E4/E7 ani KO32. Normatywny zakres:
[odbiór O2](ODBIOR_APK_API_O2.md), [driver i obserwacja](OBSERWACJA_APK_API_O1.md).
Komunikacja: O3-078 i O1-077 w [dzienniku](../KOMUNIKACJA_AGENTOW.md).

## Przypięty zestaw

| Element | Rzeczywiście użyta wersja |
|---|---|
| AVD | Istniejący O1Api35, API35, osobny od emulatorów zwykłego APK i testów offline |
| Aplikacja | 0.8.12.validation, versionCode1023, Room9 |
| Źródło | `e319e53130020b3bbcdb50588ef4a2205a241118` |
| APK SHA-256 | `89164efd5199c8e1329f4fc833107a4045d034533ded6ef0e93f00996c50efcb` |
| Driver SHA-256 | `91b788998c3aa20b928e65e3f4d63a5ff3ad9048cc3de8c70f5ba8b86ecc231f` |
| Publiczny CA SHA-256 | `01f120ef25f091a6413a535dcaa5e333575a8d08a016503c47998333eef3a6f6` |
| Działający serwer według O3-076/077 | schema `0024_e9_history_graph`; obraz `sha256:05c1792f3551725f0303cc3786892771392532a25edc18ff710faad9e6b7e9a9` |

O1 zweryfikował hashe obu zainstalowanych APK. Nie wykonywano instalacji,
wipe, clear, odtwarzania AVD lub zmiany jego konfiguracji. O3 identyfikuje
używany obraz oddzielnie od nowszego kodu/schema26 w repozytorium.
Właściwe adresy i dane kont pozostały prywatne. Nowy klient O1 i nowy lease
przechodziły świeży check TLS/discovery200/readiness200 w oknie R2.

## Zwykły GET i dokładny driver

Po rzeczywistym formularzu PKCE konta A aplikacja pokazała „Sesja dostępna”.
Wykonano jawne sprawdzenie połączenia konta oraz zwykły GET `/api/v1/me`.
Wynik został poprawnie sparsowany: pusty profil i podgląd ostatniego odczytu,
bez trwającego pobierania. Neutralny receipt pierwszego GET:
UTC `2026-10-19T06:39:56.760879Z`, HTTP200, no-store,
request ID `4d88162b-0506-4f66-8597-5431758445e0`.

Następne uruchomienie drivera miało **0 PASS / 0 FAIL / 1 SKIP**. Nie jest
zaliczeniem oracle. `hasSession` tego klienta wymaga dostępu ważnego jeszcze
ponad30s; sam zapis refresh tokenu lub wcześniejszy odczyt nie wystarcza.
Wygaśnięcie dostępu przed guardem jest hipotezą zgodną z przebiegiem;
nie przypisujemy pominięcia ustalonej usterce serwera lub kontrolera.

Jawnie odnowiono sesję. Ponowny kontrolny GET i ukończony DTO zostały
powiązane z bieżącym czasem, a nie ze starym logiem: UTC
`2026-10-19T06:47:19.720497Z`, HTTP200/no-store,
request ID `dc00ca61-1405-4dbe-b0fd-1c92ef3f024a`.
Natychmiast potem uruchomiono ten sam opt-in `LiveApiLateReceiptTest`,
bez zmiany jego kodu, APK, SHA, guardów lub limitu gate10s.

**Wynik: 1 PASS / 0 FAIL / 0 SKIP**, runner `OK (1 test)`.
Run: `425b7ebe-bf51-4e6e-aa9d-861efb4fe303`.
Zatrzymany rzeczywisty GET `/api/v1/me`: HTTP200/no-store, UTC
`2026-10-19T06:47:27.985598Z`, request ID
`56db1ea4-ae7a-466d-bfd5-8c0c64140eec`.

| Zdarzenie z oryginalnego APK | UTC 19.10.2026 |
|---|---|
| held | 06:47:27.987493 |
| logout | 06:47:28.064846 |
| released | 06:47:28.066032 |
| dto_parsed | 06:47:28.096445 |
| stale_owner_rejected | 06:47:28.112245 |
| guest_preserved | 06:47:28.138190 |

To faktycznie odebrana odpowiedź po ograniczonym odczycie body, zatrzymana
na istniejącej granicy gateway. Po prawdziwym logout powstał DTO, a guard
odrzucił poprzedniego właściciela. Nie podstawiano fixture odpowiedzi/tokenów
i nie obchodzono cancellation. Wynik nie dowodzi opóźnienia samego strumienia
TCP. Driver porównał15tabel danych lokalnych i nie przywrócił prywatnego podglądu.

## Właściciele, dane i zamknięcie

Niezależnie od asercji drivera wykonano prywatny baseline23tabel przed próbą
oraz kopie po driverze, po loginie B i po powrocie do A. W każdym etapie
**15/15 tabel dziennika identycznych**: produkty, posiłki/pozycje, cele, outbox,
racje/składniki, profile, waga, dni, tabele katalogu i szkice zdjęć. Room9,
FK clean. Prywatne wiersze, Vault, formularze i surowy runner pozostały poza
repozytorium i OneDrive. Nie deklarujemy niezmienności metadanych logowania.

Po driverze faktycznie aktywny był gość. Przeprowadzono następnie realny PKCE
do B i ponownie do A, jawnie zmieniając użytkownika w przeglądarce. Każdy
login potwierdzono aktualnym „Sesja dostępna”. Kopie Room wykazały oddzielnego
właściciela B, powrót do pierwotnego właściciela A i rosnące generacje lease.
Restarty procesu pomiędzy etapami zachowały dane i sesję konta.

**PASS A→gość→B→A dotyczy PKCE, lokalnych właścicieli i zachowania danych.**
Świeże `/me` i `/me/motivation` osobno dla B oraz ponownie A: **NOT_RUN**.
Nie jest to pełny wielokontowy odbiór DTO/E3. Nie wykonano importu gościa,
push dziennika, zmian zgód, Nemesis lub nowego żądania Gemini.

O1 odłączył dokładnie własny lease/NAT/reverse i klienta o
`2026-10-19T06:56:47.7491121Z`, przed końcem R2. Zachowano APK i dane.
O3 potwierdził niezależnie automatyczne zamknięcie o08:58:41.931949 CEST,
16 przyjętych połączeń, brak listenera/połączeń18444 oraz poprawne
HTTPS/readiness/discovery, issuer/CA i wymagany monitoring. Źródło:
[O3-079/O3-080, commit f7c3c4f](https://github.com/Roseru/aplikacja-mobilna/blob/f7c3c4f/docs/KOMUNIKACJA_AGENTOW.md).
O3 odczytał też dokładny raport O1 z `cc0a058`; jego źródłowy wpis nie
przypisuje aktualizacji locka z main do używanej instalacji schema24.
Żaden etap nie wymagał restartu komputera.

## Wyniki wcześniejsze i granice

Pierwsze krótkie okno zachowuje **0 PASS / 1 FAIL / 0 SKIP**: timeout20s
na oczekiwaniu held, brak receipt zatrzymanego GET. R2SKIP również pozostaje
w historii. Końcowy PASS nie usuwa tych wyników ani nie ustala ich przyczyny.

Nowy Android0.8.23/Room14 był testowany osobno, na emulatorze bez sieci:
322/337 JVM, lint0błędów, focus22/22 i pełne320/320 PASS, 0fail/skip,
offline przed/po. To lokalny odbiór innego kandydata; nie użyto go w R2.
Nie kwalifikuje on rzeczywistego HTTP push E4, E7/provider ani KO32.
Publikacja źródeł/artefaktu tego kandydata i jego aktualizacja zwykłej aplikacji
pozostają odrębnym etapem.
