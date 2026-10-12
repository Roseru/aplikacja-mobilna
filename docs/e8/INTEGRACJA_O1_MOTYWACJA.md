# Integracja motywacji E8.1 + E8.2 - osoba 2

12 października 2026. Kontrakt normatywny: [FastAPI OpenAPI](../../backend/openapi.json), [wygenerowany schemat](../../contracts/schemas/motivation.schema.json), [przykłady](../../contracts/examples/e8/). Dokument jest przekazaniem backendu; nie zalicza APK/Room/O1.

## Odczyt i prezentacja

GET /api/v1/me/motivation jest prywatny. JWT ustala konto; dodatkowe query/body owner/points/rank/badge/status są odrzucane. Pole status ma pending_backfill (points/rank=null), pending_materialization (potwierdzone punkty czekają na należną maturację) lub final. Revisions/source_position nie są checkpointem sync. Punkty i nagrody offline pokazuj jako lokalny postęp, osobno od serwerowego potwierdzenia. Kandydat z bieżącej daty nie zwiększa rankingu przed zamknięciem daty w zachowanej strefie.

Cztery odznaki mają pending/final/revoked, progress/required, minimalny witness i first_awarded_at/activated_at/revoked_at. Korekta może obniżyć punkty i rangę lub cofnąć odznakę. Ponowne spełnienie reaktywuje tę samą tożsamość; nie pokazuj drugiej nagrody. Brak energii nie jest zerem, brak makr nie odbiera znanej energii. Brak celu może dać1 pkt, lecz in_goal pozostaje null. Legacy racja z dodatnim spożyciem i ration_component_position=null daje zwykłe punkty kompletności, ale nie świadectwo odznaki racji. Nie dopisuj historycznych markerów automatycznie.

## Świadoma zgoda

Jedyna źródłowa zgoda nadal UserConsent.ranking. Stare ConsentInput/Consent/ProfileRead.consents oraz response receipts są identyczne. GET motivation.ranking podaje requested/effective/pending_consent_refresh/consent_epoch/own_position. True bez bieżącego potwierdzenia jest pending_consent_refresh, nie fikcyjnym false. Wyjaśnij użytkownikowi pseudonim/punkty/rangę/liczbę odznak oraz możliwość obniżenia wyniku po korekcie.

Do świadomego potwierdzenia wyślij istniejący PUT /me/consents z poprawnym If-Match i NOWYM Idempotency-Key, pełnym body oraz X-Ranking-Consent-Epoch równym motivation.ranking.consent_epoch. Zachowaj automatic_energy_adjustment ze źródłowego odczytu; toggle rankingu nie może zmieniać tej zgody. Konflikt409 wymaga świeżego odczytu i decyzji, nie bezmyślnego replay. Body bez nowego nagłówka nadal zapisuje starą zgodę, ale nie przywraca brakującej świeżości publikacji. Energy-only/replay/backfill/read nie odnowią markeru po restore. Opt-out natychmiast po commit zamyka kolejne odczyty publiczne.

## Ranking i cache

GET /api/v1/ranking limit1..100, page_token losowy i nieprzezroczysty. RANK obejmuje cały ranking przed ograniczeniem strony:10,10,8 daje1,1,3. Pseudonim/UUID stabilizują tylko prezentację, UUID nie trafia do payloadu. Każda strona świeżo sprawdza opt-in/profile/state/epoch/backfill. Sortowanie jest po points DESC,pseudonym w kolacji C, wewnętrznym UUID.

To ranking live, bez zamrożonej kopii wyników: między stronami możliwe pominięcie lub powtórzenie. Token wiąże requester/generation/epoch/limit/purpose i wygasa po10min. Zachowane są dwa ostatnie input tokeny w sesji dla lost ACK; starszy/expired/purged anchor daje410 ranking_cursor_restart_required. Opt-out anchor nadal pozwala użyć seek tuple. Początkowych sesji jest najwyżej8/10min/requester;429 ranking_cursor_limit ma Retry-After600. Kontynuacja nie zużywa nowych sesji i nie obcina głębokich pozycji. Po odzyskaniu puli można rozpocząć od początku.

Wszystkie odpowiedzi, także błędy auth/parsera, mają no-store. Po logout, zmianie konta/generation/epoch usuń cache motywacji/rankingu i cursory oraz ignoruj spóźnione odpowiedzi starego kontekstu. Wcześniej pobranych cudzych danych nie obiecuj zdalnie cofnąć. Ten etap nie udostępnia adresowania Nemesis lub danych kontaktowych.
