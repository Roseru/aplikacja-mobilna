# Kolejny zakres Androida — Agent 1

Stan odczytu: 11 października 2026, main `73860fa`. PR-y #1/#6/#7/#9 są scalone. Android 0.7.1 / Room 6 nadal działa lokalnie; 65 JVM i 52 testy urządzenia dotyczą tej wersji, nie przyszłej sieci. O3 dostarczył CI Androida (#10) i lokalny HTTPS/API/Keycloak (#19). Nie czekamy ponownie na już dostarczone środowisko.

[Potwierdzenie O2](https://github.com/Roseru/aplikacja-mobilna/pull/20#issuecomment-6108744684), [wspólny dziennik](../docs/KOMUNIKACJA_AGENTOW.md). PR #20 E6 i #21 retencji były otwarte podczas odczytu; ich późniejszy status sprawdzamy przed pracą. Odczyt opisu E6 nie jest niezależnym review runtime.

## Kolejność i mierzalne wyniki

| Krok | Zakres O1 | Warunek ukończenia |
|---|---|---|
| 1. Stabilność ekranów | Odtworzyć zgłoszenia O3-007/008: Pixel 2, brak `day-complete` i timeout przepływu importowanej racji; sprawdzić przewijanie i oczekiwanie na stan UI | Pełne testy na mniejszym ekranie i bazowym Pixel 6, bez maskowania awarii retry lub wyłączeniem asercji |
| 2. Sesja | Systemowa przeglądarka, OIDC Authorization Code + PKCE S256, dokładne callbacki obu applicationId, klient bez sekretu, tokeny w prywatnej pamięci chronionej przez Keystore; przełączenie repozytorium/ViewModel według potwierdzonego `(issuer, sub)` | Własny test APK z lokalnym HTTPS: A/B/gość, callback, wygaśnięcie, logout/restart, odrzucenie starego zadania A→B→A; dziennik offline nadal działa |
| 3. HTTP i E3 | Konfiguracja zgodnego issuer/API i ograniczonego zaufania lokalnemu publicznemu CA w testowym wariancie; trwały klucz bootstrapu; chronione read API po bootstrapie | Test rzeczywistego APK, replay/lost ACK i błędów 401/403/409/503; kontrola lease i kontekstu przed wysyłką oraz przy apply; brak automatycznego przypisania gościa |
| 4. Room i E4 | Oddzielne originals/wire/shadow/staging, pełne klucze właściciela, niezmienna materializacja operacji, atomowy pull/ACK, checkpoint i jawne recovery; WorkManager dopiero nad tym modelem | Migracja rzeczywistej bazy bez utraty historii; KO-31, zabicie procesu, prefix/lost ACK, restart, epoka/generacja, konta A/B i 30 dni offline; koperty do 100 operacji/1 MiB |
| 5. E5 | Wspólny resolver korekt celów i wektory statistics_v1; exact BigDecimal wire do 6 miejsc i computed do 12; osobny lokalny/pending oraz serwerowy wynik | Wektory Kotlin i Room: strefa profilu/as_of, północ/DST, null/zero, osie korekt, granice celu i waga; nie utożsamiać lokalnej sekwencji z rewizją serwera |
| 6. E6 | Publikacja dokładnej rewizji szkicu, matches/deduplikacja, feedback/głosy/reporty i oddzielny community cache | Implementować według odebranego kontraktu E6 po sprawdzeniu merge #20; lost ACK, epoch, hide/canonical i historyczne refs; brak promowania demo do official |

Każdy krok jest osobnym spójnym PR z aktualnego main. Nie deklarujemy całego E5/KO-31 po wdrożeniu samego logowania. Rzeczywiste wyniki APK i środowiska zapisujemy osobno od dowodów Python/CI O2/O3.

## Reguły zachowania danych

- Lokalne UUID, snapshoty, historia i obecna kolejka pozostają zachowane. Stary outbox nie jest gotowym Operation E4; materializujemy oddzielną wersję, bez zmiany wysłanego ID/body/hash.
- Wartości z 12 miejscami, których nie da się bezstratnie przedstawić jako Decimal6, oraz dawne cele bez czasu/strefy wymagają jawnego uzgodnienia; nie zaokrąglamy po cichu ani nie wymyślamy metadanych.
- Import gościa wymaga trwałej świadomej decyzji. Bootstrap nie jest importem ani potwierdzeniem tożsamości.
- Po rotacji wspólnego klucza tokenów podpisane checkpoint/page/read tracą ważność; zachowujemy originals/receipts/outbox i wykonujemy kontrolowany nowy pełny pull. Ponowny bootstrap nie kasuje `requiresRecovery`.
- TLS pozostaje weryfikowany; publiczny lokalny CA nie jest sekretem, lecz klucze, credentials i tokeny nie trafiają do APK/repo/logów. Nie zmieniamy issuer tylko po stronie emulatora.

## Dokumenty wykonawcze

[E3 / sesja i bootstrap](../docs/e3/INTEGRACJA_O1.md), [E4 / sync](../docs/e4/INTEGRACJA_O1.md), [E5 / odczyty i statystyki](../docs/e5/INTEGRACJA_O1.md), [środowisko O3](../infra/integration/README.md), [workflow](../docs/WORKFLOW.md).

Review jest opcjonalne według O3-005; wymagane CI oraz rozwiązanie istotnych uwag pozostają obowiązujące. Dostawa official, pełne etykiety ARPOL, publiczny VPS/SMTP oraz restore/RPO/RTO mają odrębnych właścicieli i dowody; nie są warunkiem rozpoczęcia niezależnej integracji lokalnego APK.
