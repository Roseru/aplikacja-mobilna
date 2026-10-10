# Wojskowy licznik kalorii

- [Uruchomienie i weryfikacja backendu E1/E2](backend/README.md)
- [Raport E2 i przekazanie offline O1](docs/e2/RAPORT_E2.md)

Projekt aplikacji Android z backendem Python i PostgreSQL, działającej również offline.

- [Wymagania projektowe i podział pracy](WYMAGANIA_PROJEKTOWE.md)
- [Decyzje backendu v1 — Osoba 2](WYMAGANIA_PROJEKTOWE.md#decyzje-osoba-2)
- [Architektura, bazy danych i pakiet racji offline](docs/ARCHITEKTURA.md)
- [Plan etapów, zależności i potrzebne zasoby](docs/PLAN_PRAC.md)
- [Workflow pracy, recenzji, CI i wdrożeń](docs/WORKFLOW.md)
- [Komunikacja agentów: przekazania, pytania i blokady](docs/KOMUNIKACJA_AGENTOW.md)
- [Kontrakty E0 i komenda walidacji](contracts/README.md)
- [Raport odbioru E0](docs/e0/ODBIOR.md)

Wspólne repozytorium zespołu: **Osoba 1 — Android i Room; Osoba 2 — backend, baza i API; Osoba 3 — GitHub, CI/CD i wdrożenie**. Przyjęty stos backendu to FastAPI, SQLAlchemy, Alembic i PostgreSQL; logowanie przez Keycloak. Maksymalny wspierany okres synchronizacji przyrostowej po pracy offline wynosi **30 dni**. Dłuższa przerwa wymaga pełnego uzgodnienia stanu z zachowaniem lokalnych danych.

Przechowywanie: PostgreSQL z oddzielnymi bazami `keycloak` i `calorie_app`; produkty, racje i profile aplikacyjne w `calorie_app`. Na telefonie Room/SQLite. Katalog startowy i aktualizacje są dostarczane jako JSON gzip i importowane do Room; JSON nie zastępuje roboczej bazy dziennika.

Aktualny stan repozytorium: odebrane E0/E1 oraz implementacja części O2 etapu E2 — katalog, racje, kontrolowany import, eksport PostgreSQL do gzip/manifest, publiczne odczyty official i importer referencyjny. Wyniki testów, recenzji i CI opisuje raport E2. Adaptacja i odbiór Room/APK wymagają osobnej pracy O1. Demo nie jest oficjalnym katalogiem; etykiety official są bramką E5. OIDC i chronione produkty należą do E3, synchronizacja do E4; E3 nie rozpoczęto.

Gemini: wyłącznie darmowe API (Free Tier), bez aktywnego billing; CI korzysta z mocka. Darmowe limity są wspólne dla projektu. Ograniczenie udostępniania funkcji Gemini użytkownikom w Polsce/EOG opisuje rozdział 11.6 wymagań; nie blokuje ono prac E0.

## Android — osoba 1

[Kod i instrukcja uruchomienia](android/README.md) · [Plan implementacji](PLAN_IMPLEMENTACJI_ANDROID.md)

Otwórz `android/` w Android Studio. Wersja 0.5.0 działa bez konta i internetu: dziennik, cele kcal/B/T/W, produkty prywatne, racje ze zjedzonymi składnikami, profil i waga. Postępy pokazują historię i wykresy 7/30/90 dni, średnie z jawną liczbą kompletnych dni oraz realizację historycznych celów. Braki pozostają brakami, pomiary wagi nie są interpolowane. Room nadal 4, bez nowej migracji.

Importer E2, BigDecimal i pełne snapshoty zachowują wcześniejsze spożycia. Katalog ma 33 produkty / 3 racje DEMO. Kolejka i analityka są lokalne; synchronizacja pozostaje do wykonania. [Raport 0.5.0](android/RAPORT_0_5.md) opisuje reguły, rzeczywistą walidację i zależność nowej gałęzi od PR #1.

Budowanie i testy jednostkowe: `./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` z katalogu `android/`. Testy urządzenia: `./gradlew :app:connectedValidationAndroidTest`; osobna instalacja testowa zachowuje zwykły dziennik.
