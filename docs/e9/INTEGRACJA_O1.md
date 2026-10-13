# E9-O2 — kontrakt klienta O1

Stan wykonania i dowody: [raport](RAPORT_E9.md). Kontrakt generowany:
[energy.schema.json](../../contracts/schemas/energy.schema.json) i
[OpenAPI](../../backend/openapi.json). Backend pozostaje demo/PG/mock; ten dokument
nie potwierdza integracji APK, Room lub Google.

## E i cel

`GET /api/v1/me/energy/state` zwraca rewizję osi, bieżący ID, świadomy baseline,
requested/effective automatu, notice, epokę/generację i zegar zastosowania.
`GET /api/v1/me/energy/history?after_revision=0&limit=100` zwraca niezmienne wersje;
następną stronę pobieraj po `next_revision`. E jest oszacowaniem utrzymania.
Przyjęcie/revert nie zmienia celu kcal/B/T/W, goal_type ani activity_class.
Brak E pozostaje null. Sugestia klasy jest opisem; zmiana klasy ma osobną decyzję.

## Analiza i decyzje online

Każda mutacja wymaga świeżego UUID `Idempotency-Key`; przed siecią utrwal dokładny
klucz i body pod owner/lease/generation/epoch. Retry po utracie odpowiedzi/restart
wysyła identyczne bytes/semantykę. Nowy body pod tym samym kluczem daje409.
Nie generuj nowego klucza po niepewnym ACK, by odtworzyć tę samą czynność.

Przykład zlecenia, `POST /api/v1/me/energy/analyses`:

```json
{
  "sync_epoch": "00000000-0000-4000-8000-000000000001",
  "account_generation": 1,
  "axis_revision": 1,
  "notice": {
    "accepted": true,
    "qualified_for_v1": true,
    "notice_version": "energy-aggregates-notice-v1",
    "aggregate_scope": "energy_adjustment_v1_minimal_aggregates",
    "provider": "mock",
    "scope": "this_energy_analysis"
  }
}
```

Provider pochodzi z aktualnej konfiguracji/capabilities AI, nie z domysłu klienta.
Pokaż notice przed afirmacją: tylko daty okna, wersja reguł/werdykt, liczby
kompletnych dni i dni pomiarowych, dwie mediany masy, deterministyczna propozycja
i granice. Bez pełnego dziennika, source IDs, pseudonimu, diagnoz lub tokenów.
`qualified_for_v1` to jawne potwierdzenie zakresu11.5; nie zbieraj diagnoz.
PhotoConsent nie jest zgodą na energię. Checkbox nie może być zaznaczony przez
odczyt/cache, restore ani stary boolean automatu.

HTTP200 oznacza przyjętą odpowiedź, nie zastosowanie E. Przy braku minimum lub
historii E: `id=null`, jawny status, brak Gemini i brak admission analizy.
Dla joba: `queued/running`; odczyt
`GET /api/v1/me/energy/analyses/{id}`, lista `GET .../analyses?limit=100`.
Ready zawiera notice związany z serwerowym snapshotem oraz `source_context`
(fingerprint i rewizje), agregaty, explanation, created_at i expires_at.
Expiry24h liczymy od gotowej zwalidowanej propozycji, nie przyjęcia joba.
Zmiana kontekstu, w tym przesunięcie bieżącego okna na kolejny lokalny dzień,
unieważnia starą propozycję. Serwer nie odświeża snapshotu przy ready.

Przyjęcie: `POST .../analyses/accept`; odrzucenie/cofnięcie notice:
`POST .../analyses/reject`. Body: ten sam kontekst + `id` i aktualna `revision`.
Użyj rewizji osi z zamrożonego `source_context`; konflikt wymaga świeżego odczytu,
bez cichego podmiany body pierwotnej operacji. Reject podczas IO blokuje późny
wynik; niepewna rezerwacja pozostaje. `manual_review_required/no_change` nie
dają liczbowego accept. Dwa niezależne cooldowny336h dotyczą admission analizy
i zastosowania nowej propozycji. No_change/reject/błąd nie są zastosowaniem.

Revert: `POST .../revert`, kontekst + `id` wcześniejszego E i `replace_id`
(null albo aktualny ID planowanej wersji na następny dzień). Powstaje nowa decyzja
od następnego lokalnego dnia. Brak jawnego ID zastąpienia zajętej daty daje409.
Późniejsze plany pozostają. Revert nie wywołuje Gemini; przesuwa zegar zastosowania.

## Automat

Zachowaj dotychczasowy `PUT /me/consents` i ranking consent. Włączenie
`automatic_energy_adjustment=true` samo nie uruchamia E9.
`POST /me/energy/affirm` wymaga kontekstu, konkretnego aktualnego `id`,
`consent_revision` i osobnego notice jak wyżej, lecz
`scope=automatic_energy_adjustment`. Notice obejmuje przyszłe analizy/korekty
w granicach11.5. Numer E nie zmienia się przy afirmacji.

Manual accept/revert ustawia świadomy baseline. Automat go nie przesuwa.
Aktualna zgoda i aktualny automatyczny notice są niezależnie wymagane; bez notice
nie ma samoczynnego I/O. Każdy nowy PUT zgód unieważnia dotychczasową afirmację
i notice, także gdy zachowuje boolean. Off→on i retry/restore nie przywracają ich.
Odczyt state rozróżnia requested/effective. Wyłączanie zgody nie zmienia rankingu
inaczej niż przewiduje dotychczasowy kontrakt zgód.

## Sync i starsze klienty

E nie jest nowym wariantem GoalPayload. Default sync-v1 zwraca wcześniejsze sześć
typów. Klient implementujący nową encję wysyła
`X-Sync-Capability: energy_estimates_v1` przy pull i push.
Scope jest podpisany z checkpoint/snapshot/page. Zmiana zakresu na starym tokenie
daje422 invalid_sync_token; pobierz pełny snapshot w nowym scope, zachowując outbox,
UUID, body i odzyskiwane operacje. Nie kasuj danych lokalnych przed uzgodnieniem.

Oś E przychodzi jako `energy_estimate`. DTO ma metodę, źródło, rewizję,
effective_from, decided_at, supersedes i audyt. Kwoty E mają kanoniczne12 miejsc;
dokładne granice pomocnicze do14. B/T/W i klasa nadal należą do starego celu/profilu.
Stary klient/obraz pomija wewnętrzny marker ChangeLog i przesuwa checkpoint,
więc nie wpada w pętlę. Pierwsza opt-in strona to pełny snapshot całej osi E.

Najważniejsze odmowy:403 notice/provider mismatch,404 obce ID,409 stale/revision/
scheduled/receipt conflict,410 expiry,429 cooldown/quota,503 brak konfiguracji/
gate/puli. Nieznany błąd nie jest ACK. Globalny no-store i fencing sesji obowiązują
także dla tych odczytów. Migracja Room, UI i rzeczywisty odbiór APK należą do O1.
