# Interfejs Nemesis lifecycle E8.3 - osoba 2

12 paĹşdziernika 2026 r. Kontrakt komponentu fazy C; router nie jest podĹ‚Ä…czony do produkcyjnego main. Public activation i statystyki pozostajÄ… zablokowane w DB do E8.4. Dokument ustala semantykÄ™, nie deklaruje PASS HTTP/PG/CI.

## Ĺ»Ä…dania

Prefix docelowy to `/api/v1`. Mutacje wymagajÄ… aktualnego user JWT, kanonicznego UUID Idempotency-Key oraz X-Sync-Epoch. Accept/cancel wymagajÄ… cytowanego If-Match revision. Body jest ograniczone do 16 KiB rzeczywistych bajtĂłw przed parsowaniem; odpowiedĹş do 1 MiB. DTO majÄ… extra=forbid i walidujÄ… Unicode scalar, kanoniczne UUID/UTC timestamps oraz IANA. Caller nie przekazuje identyfikatorĂłw participants, start_at ani wyniku.

| Metoda i Ĺ›cieĹĽka | Body / rezultat |
| --- | --- |
| POST /me/nemesis/share-code | Bez body; nowa operacja issue/rotate wydaje najwyĹĽej jeden waĹĽny kod wĹ‚aĹ›ciciela. |
| DELETE /me/nemesis/share-code | Bez body; idempotentny revoke bieĹĽÄ…cego kodu, bez cancel istniejÄ…cych invite. |
| POST /nemesis | destination_code oraz wymagane terms; zgoda nadawcy na te warunki. |
| GET /me/nemesis | Limit 1..100 i opaque cursor powiÄ…zany z owner/generation/epoch/purpose/TTL; wĹ‚asna historia live bez globalnego cap. |
| GET /nemesis/{id} | Bezpieczne metadata dostÄ™pne tylko aktualnemu uczestnikowi. |
| POST /nemesis/{id}/accept | Wymagane terms powtarzajÄ…ce dokĹ‚adnÄ… propozycjÄ™; tylko adresat. |
| POST /nemesis/{id}/cancel | Reason: withdrawn, declined albo sharing_revoked; zakres stosowny do roli/stanu. |
| GET /nemesis/{id}/statistics | 503 fail-closed do odebranego E8.4; brak obliczeĹ„ live lub fikcyjnego zera. |

PrzykĹ‚ad create (kod ilustracyjny nie sĹ‚uĹĽy rzeczywistemu adresowaniu):

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

Accept zawiera wyĹ‚Ä…cznie te same terms. Duration_days i time_zone majÄ… defaults 30/Europe/Warsaw, opcjonalne booleans false. Rule_version, scope oraz regularity sÄ… wymagane; regularity musi byÄ‡ dokĹ‚adnie true. Nieznany scope, raw weight, meals, dowolna notatka, number/string boolean i client clock sÄ… odrzucane. Znormalizowane defaults stanowiÄ… tÄ™ samÄ… semantykÄ™ hash; zmiana wartoĹ›ci wymaga nowego invite.

## OdpowiedĹş i bĹ‚Ä™dy

Metadata zawierajÄ…: id UUID, revision, wĹ‚asnÄ… role inviter/invitee, status invited/active/finished/cancelled, terms, invited_at, expires_at, nullable accepted_at/start_date/end_date/start_at/end_at/deadline/result_status/cancel_reason i nullable partner_pseudonym. `end_date` jest wyĹ‚Ä…cznÄ… granicÄ… dat okresu. Nie zawierajÄ… partner account UUID, issuer/sub/email, ĹşrĂłdĹ‚owych UUID, rewizji, E, goal kcal, masy ani posiĹ‚kĂłw. Deletion/restore/cancel nie odtwarza dawnego profilu z receipt. Strona ma items i nullable next_cursor, najwyĹĽej 100 pozycji.

Issuance receipt ujawnia destination_code tylko jego wĹ‚aĹ›cicielowi, razem z issued_at/expires_at. Raw kod nie trafia do URL/query, logĂłw ani bĹ‚Ä™dĂłw; takĹĽe walidacyjne bĹ‚Ä™dy HTTP muszÄ… usuwaÄ‡ input z odpowiedzi. W odpowiedziach sukcesu i bĹ‚Ä™du uĹĽywamy Cache-Control: no-store. ETag reprezentuje cytowanÄ… revision. Po retencji zwykĹ‚ego receipt odpowiedĹş jest minimalnym already_applied lub jawnym idempotency_result_expired; nie uruchamia mutacji ponownie.

| HTTP | Znaczenie |
| --- | --- |
| 404 | Cudzy lub niedostÄ™pny prywatny challenge, bez ujawnienia participants. |
| 409 | Stale revision/terms/key reuse/epoch albo wymagane uzgodnienie, bez partner state. |
| 422 | BĹ‚Ä™dny Ĺ›cisĹ‚y payload, strefa lub format. |
| 429 | WspĂłlny limit; Retry-After i neutralne dane bez licznoĹ›ci partnera. |
| 503 | NiedostÄ™pna capability/E8.4 lub usĹ‚uga; raw EXECUTE rĂłwnieĹĽ sprawdza DB gate. |

Niepoprawny, wygasĹ‚y i wycofany kod majÄ… wspĂłlnÄ… neutralnÄ… odmowÄ™ bez identity leak. BezpoĹ›redni caller moĹĽe wybraÄ‡ tylko trzy cancel reasons; expired/deleted/restore sÄ… przyczynami serwerowymi. Nawet replay/cursor/read sprawdzajÄ… bieĹĽÄ…cy auth, epoch/generation i access. Admin/moderator nie otrzymuje dodatkowego dostÄ™pu bez wĹ‚asnego uczestnictwa.

## Python i integracja

`schemas.py` zawiera NemesisScope, NemesisTerms, CreateNemesis, AcceptNemesis, CancelNemesis, EmptyNemesisOperation, ShareCodeReceipt, NemesisMetadata oraz NemesisPage. Router sprawdza validate_body_size na rzeczywistym body i validate_response_size przed wysĹ‚aniem. `addressing.py` udostÄ™pnia generate_share_code, share_code_digest oraz canonical_request_hash(operation, body, epoch, if_match=None, entity_id=None). Python wyznacza checksum kanonicznej semantyki, a SQL niezależnie ponownie oblicza autorytatywny hash znormalizowanego JSONB payload i kontekstu; kodek digest przechowuje tylko hex. Nie stanowi autoryzacji.

`rules.py` udostÄ™pnia frozen ChallengePeriod oraz challenge_period(accepted_at, duration_days, time_zone), next_local_day_start i first_real_day_start. Lifecycle clock musi pochodziÄ‡ z DB po lockach. Start jest pierwszym rzeczywistym poczÄ…tkiem kolejnej lokalnej daty, a koniec obejmuje dokĹ‚adnie 7/30/90 kolejnych istniejÄ…cych dat. NieistniejÄ…ca peĹ‚na data wewnÄ…trz okresu odmawia przed mutacjÄ…. Gdy nie istnieje wyĹ‚Ä…cznie wyĹ‚Ä…czna end_date, end_at wskazuje pierwszÄ… rzeczywistÄ… granicÄ™ po ostatnim wĹ‚Ä…czonym dniu, a end_date pozostaje start_date + N. Deadline to end_at UTC + 30 Ă— 24 h. Warsaw DST zmienia liczbÄ™ godzin, a nie dat. Przed zapisem wszystkie daty oraz UTC/local roundtrip sÄ… sprawdzane wzglÄ™dem wspieranego zakresu 0001â€“9999.

Source seam jest frozen SourceMutationContext na dokĹ‚adnym freeze. Jeden aggregate projection wykonuje wszystkie locki challenges UUID ASC po account/counter, przed wspĂłlnÄ… kwalifikacjÄ…. Guard E8.3 nie jest projector/finalizer E8.4, nie oblicza punktĂłw i nie zakazuje poprawnej historycznej strefy wagi. W przyszĹ‚ym adapterze masa uĹĽywa occurred_at UTC i ostatniego ĹĽywego pomiaru dnia wedĹ‚ug (occurred_at, UUID); mean_deficit korzysta z dodatniego historycznego E. Hidden nie ujawnia partner counts; insufficient_data jest null z counts; pending nie jest zerem.

Produkcyjne main/health/sync/provision/purge/global schema sÄ… zarezerwowane autorowi E8.1+2 do finalnego odbioru PR #35. Faza C ma tylko prywatnÄ… factory/bootstrap w tests/support. Faza I podĹ‚Ä…cza zwolnione seams po zwykĹ‚ym merge main i wymaga nowych dowodĂłw runtime/nieautora/CI. O1 ma zachowaÄ‡ Ĺ›wiadomy wybĂłr scope i cache isolation; O3 ma zapewniÄ‡ minimalne LOGIN, bounded maintenance i restore cancellation. Te przekazania nie zaliczajÄ… wykonania O1/O3 ani E8.4.

Przyszłe E8.4 musi inicjalizować rzeczywiste projections także w transakcji DB accept przed przyznaniem capability, w tym przy raw EXECUTE. Pythonowy testowy initializer nie zastępuje tej zależności. Wydana 0017 pozostanie niezmienna; E8.4 zmieni potrzebną funkcję/schema przez kolejną migrację i dopiero po odbiorze zarejestruje zgodne rewizje.
