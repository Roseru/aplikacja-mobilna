# Interfejs Nemesis lifecycle E8.3 - osoba 2

12 października 2026 r. Kontrakt komponentu fazy C; router nie jest podłączony do produkcyjnego main. Public activation i statystyki pozostają zablokowane w DB do E8.4. Dokument ustala semantykę, nie deklaruje PASS HTTP/PG/CI.

## Żądania

Prefix docelowy to `/api/v1`. Mutacje wymagają aktualnego user JWT, kanonicznego UUID Idempotency-Key oraz X-Sync-Epoch. Accept/cancel wymagają cytowanego If-Match revision. Body jest ograniczone do 16 KiB rzeczywistych bajtów przed parsowaniem; odpowiedź do 1 MiB. DTO mają extra=forbid i walidują Unicode scalar, kanoniczne UUID/UTC timestamps oraz IANA. Caller nie przekazuje identyfikatorów participants, start_at ani wyniku.

| Metoda i ścieżka | Body / rezultat |
| --- | --- |
| POST /me/nemesis/share-code | Puste DTO; nowa operacja issue/rotate wydaje najwyżej jeden ważny kod właściciela. |
| DELETE /me/nemesis/share-code | Puste DTO; idempotentny revoke bieżącego kodu, bez cancel istniejących invite. |
| POST /nemesis | destination_code oraz wymagane terms; zgoda nadawcy na te warunki. |
| GET /me/nemesis | Limit 1..100 i opaque cursor powiązany z owner/generation/epoch/purpose/TTL; własna historia live bez globalnego cap. |
| GET /nemesis/{id} | Bezpieczne metadata dostępne tylko aktualnemu uczestnikowi. |
| POST /nemesis/{id}/accept | Wymagane terms powtarzające dokładną propozycję; tylko adresat. |
| POST /nemesis/{id}/cancel | Reason: withdrawn, declined albo sharing_revoked; zakres stosowny do roli/stanu. |
| GET /nemesis/{id}/statistics | 503 fail-closed do odebranego E8.4; brak obliczeń live lub fikcyjnego zera. |

Przykład create (kod ilustracyjny nie służy rzeczywistemu adresowaniu):

```json
{
  "destination_code": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
  "terms": {
    "rule_version": "regularity_v1",
    "duration_days": 30,
    "time_zone": "Europe/Warsaw",
    "scope": {
      "regularity": true,
      "weight_change": false,
      "mean_deficit": false
    }
  }
}
```

Accept zawiera wyłącznie te same terms. Duration_days i time_zone mają defaults 30/Europe/Warsaw, opcjonalne booleans false. Rule_version, scope oraz regularity są wymagane; regularity musi być dokładnie true. Nieznany scope, raw weight, meals, dowolna notatka, number/string boolean i client clock są odrzucane. Znormalizowane defaults stanowią tę samą semantykę hash; zmiana wartości wymaga nowego invite.

## Odpowiedź i błędy

Metadata zawierają: id UUID, revision, własną role inviter/invitee, status invited/active/finished/cancelled, terms, invited_at, expires_at, nullable accepted_at/start_date/end_date/start_at/end_at/deadline/result_status/cancel_reason i nullable partner_pseudonym. `end_date` jest wyłączną granicą dat okresu. Nie zawierają partner account UUID, issuer/sub/email, źródłowych UUID, rewizji, E, goal kcal, masy ani posiłków. Deletion/restore/cancel nie odtwarza dawnego profilu z receipt. Strona ma items i nullable next_cursor, najwyżej 100 pozycji.

Issuance receipt ujawnia destination_code tylko jego właścicielowi, razem z issued_at/expires_at. Raw kod nie trafia do URL/query, logów ani błędów; także walidacyjne błędy HTTP muszą usuwać input z odpowiedzi. W odpowiedziach sukcesu i błędu używamy Cache-Control: no-store. ETag reprezentuje cytowaną revision. Po retencji zwykłego receipt odpowiedź jest minimalnym already_applied lub jawnym idempotency_result_expired; nie uruchamia mutacji ponownie.

| HTTP | Znaczenie |
| --- | --- |
| 404 | Cudzy lub niedostępny prywatny challenge, bez ujawnienia participants. |
| 409 | Stale revision/terms/key reuse/epoch albo wymagane uzgodnienie, bez partner state. |
| 422 | Błędny ścisły payload, strefa lub format. |
| 429 | Wspólny limit; Retry-After i neutralne dane bez liczności partnera. |
| 503 | Niedostępna capability/E8.4 lub usługa; raw EXECUTE również sprawdza DB gate. |

Niepoprawny, wygasły i wycofany kod mają wspólną neutralną odmowę bez identity leak. Bezpośredni caller może wybrać tylko trzy cancel reasons; expired/deleted/restore są przyczynami serwerowymi. Nawet replay/cursor/read sprawdzają bieżący auth, epoch/generation i access. Admin/moderator nie otrzymuje dodatkowego dostępu bez własnego uczestnictwa.

## Python i integracja

`schemas.py` zawiera NemesisScope, NemesisTerms, CreateNemesis, AcceptNemesis, CancelNemesis, EmptyNemesisOperation, ShareCodeReceipt, NemesisMetadata oraz NemesisPage. Router sprawdza validate_body_size na rzeczywistym body i validate_response_size przed wysłaniem. `addressing.py` udostępnia generate_share_code, share_code_digest oraz canonical_request_hash(operation, body, epoch, if_match=None, entity_id=None). Hash jest SHA-256 kanonicznej JSON semantyki; kodek digest przechowuje tylko hex. Nie stanowi autoryzacji.

`rules.py` udostępnia frozen ChallengePeriod oraz challenge_period(accepted_at, duration_days, time_zone), next_local_day_start i first_real_day_start. Lifecycle clock musi pochodzić z DB po lockach. Start jest pierwszym rzeczywistym początkiem kolejnej lokalnej daty, a koniec obejmuje dokładnie 7/30/90 kolejnych istniejących dat. Nieistniejąca pełna data wewnątrz okresu odmawia przed mutacją. Gdy nie istnieje wyłącznie wyłączna end_date, end_at wskazuje pierwszą rzeczywistą granicę po ostatnim włączonym dniu, a end_date pozostaje start_date + N. Deadline to end_at UTC + 30 × 24 h. Warsaw DST zmienia liczbę godzin, a nie dat. Przed zapisem wszystkie daty oraz UTC/local roundtrip są sprawdzane względem wspieranego zakresu 0001–9999.

Source seam jest frozen SourceMutationContext na dokładnym freeze. Jeden aggregate projection wykonuje wszystkie locki challenges UUID ASC po account/counter, przed wspólną kwalifikacją. Guard E8.3 nie jest projector/finalizer E8.4, nie oblicza punktów i nie zakazuje poprawnej historycznej strefy wagi. W przyszłym adapterze masa używa occurred_at UTC i ostatniego żywego pomiaru dnia według (occurred_at, UUID); mean_deficit korzysta z dodatniego historycznego E. Hidden nie ujawnia partner counts; insufficient_data jest null z counts; pending nie jest zerem.

Produkcyjne main/health/sync/provision/purge/global schema są zarezerwowane autorowi E8.1+2 do finalnego odbioru PR #35. Faza C ma tylko prywatną factory/bootstrap w tests/support. Faza I podłącza zwolnione seams po zwykłym merge main i wymaga nowych dowodów runtime/nieautora/CI. O1 ma zachować świadomy wybór scope i cache isolation; O3 ma zapewnić minimalne LOGIN, bounded maintenance i restore cancellation. Te przekazania nie zaliczają wykonania O1/O3 ani E8.4.
