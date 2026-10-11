# Integracja Androida z Nemesis lifecycle - osoba 2

12 października 2026. To przekazanie komponentu E8.3-C; nie potwierdza wykonania Androida. Produkcyjny router zostanie podłączony w E8.3-I, a wydanie kodu, tworzenie i akceptacja oraz statystyki pozostają niedostępne do odbioru E8.4. W tym etapie 503 jest właściwym stanem bramki.

Adresat świadomie wydaje jednorazowy kod i przekazuje go wybranej osobie poza aplikacją. Kod jest prywatny, ważny najwyżej 24 h, a rotacja unieważnia poprzedni. Nie wyszukujemy adresata po emailu, pseudonimie lub UUID. Kod przesyłamy w body POST /api/v1/nemesis i nie wpisujemy go do URL, logów lub analityki. Opaque code pozwala jedynie skierować propozycję; nie przyznaje dostępu do statystyk.

Ekran create i accept pokazuje tę samą wersję regularity_v1, okres 7/30/90 dat, uzgodnioną IANA zone oraz wymagany scope regularity. Dwa oddzielne opcjonalne przełączniki weight_change i mean_deficit domyślnie są wyłączone. Akceptacja powtarza pełne warunki. Ich zmiana wymaga cancel i nowego invite. Ranking opt-in jest niezależny.

Przykład pełnych terms:

```json
{"rule_version":"regularity_v1","duration_days":30,"time_zone":"Europe/Warsaw","scope":{"regularity":true,"weight_change":false,"mean_deficit":false}}
```

Mutacje mają kanoniczny UUID Idempotency-Key i aktualny X-Sync-Epoch. Accept/cancel wymagają If-Match w postaci cytowanej dodatniej rewizji, np. "1". Issue/revoke nie mają body. GET także wymaga aktualnego X-Sync-Epoch. Zmiana body, terms, target lub revision przy ponowieniu tego samego key daje 409. Lost ACK zachowuje dokładny key i żądanie; retry nie przesuwa startu lub ważności i nie odtwarza anulowanej zgody. Po wygaśnięciu pełnej odpowiedzi klient odczytuje bieżące metadata, a 409 idempotency_result_expired nie jest zachętą do ponownego create z tym samym kluczem.

Statusy to invited, active, finished, cancelled; expiry to cancelled/expired. Slot jest zajęty od accept także przed następną lokalną północą. End_date jest wyłączną granicą dat; deadline to end_at + 30 × 24 h w UTC. Finished/provisional w E8.3 nie ma finalnego wyniku. Statistics zwraca 503; nie wyświetlamy fikcyjnego zera ani lokalnego wyniku jako serwerowego. Przyszłe E8.4 rozróżni hidden, insufficient_data i dostępny wynik. Hidden nie pokazuje liczności lub dat partnera; null ma jawny powód i counts tylko w uzgodnionym scope.

Cancel reason zależy od roli i stanu: inviter wycofuje invited przez withdrawn, invitee odrzuca przez declined, a każdy uczestnik active/finished wycofuje sharing_revoked. Cancel jest terminalny. Zamknięta bramka nie blokuje własnego revoke/cancel i bezpiecznych metadata. 404 ukrywa cudzy zasób; moderator lub admin bez uczestnictwa nie otrzymuje dodatkowego dostępu. 429 respektuje Retry-After, 409 wymaga uzgodnienia, 422 poprawy żądania, 503 ponowienia po wskazanym czasie.

Lista GET /me/nemesis ma limit 1..100 i nieprzezroczysty cursor. Strony są live, nie stanowią snapshotu statystyk; zmiana danych może powodować powtórzenia lub pominięcia. Cursor wiąże requester, generation, epoch, purpose i TTL 15 min; pula ma najwyżej osiem tokenów na requester. Po 409 klient zaczyna od początku bez nadpisania innych danych. Każda chroniona odpowiedź ma no-store.

Po logout, zmianie konta lub epoki usuń prywatny cache, codes i cursor oraz unieważnij oczekujące odpowiedzi przez aktualny lease. Nie pokazuj partner UUID, issuer, subject, email, surowej masy, E, goal kcal, posiłków lub źródłowych rewizji. Usunięcie konta partnera odcina dostęp przed purge; po purge możliwy jest wyłącznie bezpieczny cancelled marker bez pseudonimu. Restore nie reaktywuje starego challenge. Wcześniej pobranych danych nie można zdalnie cofnąć, ale nowe odczyty muszą respektować aktualną zgodę.
