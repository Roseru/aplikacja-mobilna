# Obserwacja rzeczywistych odczytów APK — agent 1

Przygotowanie 14.10.2026 na `codex/android-odbior-api`. Zależność źródeł:
`4b4e8a3255f2b3c182954b7f83de9daa2ef7adc5`, niescalony PR64.
To osobny etap odbioru, nie nowe rozpoznawanie zdjęć ani zmiana backendu.
Normatywny scenariusz: [odbiór O2](ODBIOR_APK_API_O2.md), odpowiedź O3-035
w [dzienniku](../KOMUNIKACJA_AGENTOW.md).

## Co rejestruje wariant validation

`HttpsJsonTransport` przekazuje do obserwatora tylko metodę, ścieżkę, status
i dwa konkretne nagłówki. Validation dopuszcza wyłącznie GET `/api/v1/me`
i `/api/v1/me/motivation`. Zapis `O1ApiReadReceipt` zawiera czas UTC, status,
boolean obecności dyrektywy no-store oraz kanoniczny UUID X-Request-ID.
Brak identyfikatora jest oznaczony `missing`, niepoprawny — `invalid`, bez jego
surowej wartości. Nie zapisujemy URL/query, tokenu, cookies, ownera, body lub mapy
wszystkich nagłówków. Obserwacja nie zastępuje istniejących kontroli TLS,
limitu odpowiedzi, deadline, parserów DTO, ownera ani cancellation.

Debug/release używają innego pliku źródłowego: stała ENABLED=false i no-op.
Validation używa własnego źródła; nie ma mechanizmu zdalnego włączania obserwacji
w zwykłym APK. To samo versionCode23/Room9 umożliwia install-r testowej aplikacji
z zachowaniem istniejących dzienników; SHA/source każdego artefaktu są odrębne.
Zwykłego APK użytkownika nie instalujemy w ramach tego odbioru.

## Punkt zatrzymania rzeczywistej odpowiedzi — propozycja dla O2

O3-035 proponuje zatrzymanie pojedynczego rzeczywistego wyniku200 GET A po
odebraniu ograniczonego body, a przed zwrotem z gateway do istniejącego kontrolera.
O2 ma potwierdzić, czy spełnia to punkt8, czy wymagane jest opóźnienie strumienia
HTTP. **Bramka opóźnienia nie jest zaimplementowana ani zaliczona w tym etapie.**

Jeżeli O2 zaakceptuje granicę gateway, kolejne wykonanie powinno zachować:

1. Rzeczywisty GET A oraz odebrany wynik200 i neutralne metadane.
2. Jednorazowe zatrzymanie wyniku poza mutexem i transakcją Room, maksymalnie10s
   w ramach dotychczasowego całkowitego deadline.
3. Rzeczywisty logout do gościa przed uwolnieniem tego samego wyniku.
4. Uwolnienie bez NonCancellable, bez sztucznego DTO i bez obejścia sprawdzania
   sesji/ownera. Cancellation może odciąć dostawę; receipt określa dokładny punkt.
5. Dowód nieprzywrócenia A oraz prywatne porównanie Room/Vault/podglądu gościa.

Jeżeli wymagane jest opóźnienie strumienia, osobny transport przygotowuje O3;
O1 nie podmienia usług wspólnej instalacji. Sam fixture, anulowany request bez
odebranego wyniku lub log szyfrowanego TCP nie jest tym dowodem.

## Odbiór i publikacja

Weryfikacja obejmuje formatowanie/redakcję/allowlist nagłówków, zbudowanie obu
implementacji wariantowych i rzeczywiste GET z aktualnego APK. Build/test/HTTP
mają osobne wyniki. Po install-r porównujemy pełne23tabele przed/po, a po GET
dziennik, cel i outbox pozostają bez zmian. Nie wykonujemy PUT zgód/importu/push.

Własny odbiór obserwacji **PASS**, 14.10.2026. Build debug/validation i lint
(0 błędów) zakończone; 165 JVM debug i 168 JVM validation bez błędów/pominięć.
Pierwsza próba validation miała 3 błędy stubu android.util.Log; opcjonalny logger
teraz nie przerywa GET, asercji nie zmieniano. Wcześniejszy wynik zachowano.
Tag loggera występuje w DEX validation, nie występuje w DEX zwykłego debug.
Nie wykonano nowego pełnego native188 na tych źródłach; wynik188 z O1-038 jest
oddzielnym dowodem poprzedniego źródła.

Aktualny APK validation: 0.8.12/code23/Room9, SHA256
`4bad317a5115482d5319e12bb1f18a1ec83ae36d40dbda6e698d8a260933a628`.
Wszystkie23tabele przed/po install-r są identyczne. Ponowne rzeczywiste logowanie
A przez Chrome/PKCE i oba GET przyjęte przez istniejący parser/controller;
wszystkie23tabele przed/po GET są identyczne. Niepusty dziennik gościa, cel i jego
pending outbox zachowane. Prywatne snapshoty/identity/tokeny poza Git.

| Faktyczny GET | Czas UTC 14.10.2026 | Status | no-store | X-Request-ID |
|---|---|---|---|---|
| `/api/v1/me` | 15:20:28.666258Z | 200 | true | `6ca4fbd6-5089-4d16-9299-c6bdeac8b231` |
| `/api/v1/me/motivation` | 15:22:36.401192Z | 200 | true | `9ae26b4e-9f2b-4464-87a3-74054f59065a` |

To receipt własnego APK, nie operatorskiego curl lub fixture. Logger został
odebrany na dedykowanym O1Api35/5558 w oknie O3-034; oryginalny issuer i CA
zachowane. Po próbie zamknięto wyłącznie własny lease/klienta przed17:25 CEST.

Pełny rozszerzony odbiór kont nadal **PARTIAL**: rzeczywista spóźniona odpowiedź
pozostaje NOT_RUN do uzgodnienia oracle O2. Kolejność merge: PR61 → PR64 →
ten zależny PR po retarget do aktualnego main i wymaganych kontrolach.
