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

Otwórz `android/` w Android Studio. Wersja 0.6.0 działa jako gość bez konta i internetu: dziennik, cele kcal/B/T/W, produkty prywatne, racje ze zjedzonymi składnikami, profil, waga i Postępy 7/30/90 dni z jawnymi brakami danych.

Room 5 dodaje trwały rejestr właścicieli, zakres repozytoriów/kolejek i odrzucanie nieaktualnych zapisów po zmianie aktywnego właściciela. Migracja zachowuje stare ID, kolumny, snapshoty oraz payloady. Jest to fundament kont bez logowania, wyboru kont w UI czy rzeczywistej synchronizacji. Importer E2 i BigDecimal zachowują historyczne spożycia; katalog ma 33 produkty / 3 racje DEMO. [Raport 0.6.0](android/RAPORT_0_6.md) dokumentuje 51 testów JVM, pełny przebieg 39/39 testów urządzenia, migrację zainstalowanego APK i ograniczenia kolejnego etapu.

Budowanie i testy jednostkowe: `./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` z katalogu `android/`. Testy urządzenia: `./gradlew :app:connectedValidationAndroidTest`; osobna instalacja testowa zachowuje zwykły dziennik.
