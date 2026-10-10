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

Aktualny stan repozytorium: odebrane E0/E1 oraz implementacja części O2 etapu E2 — katalog, racje, kontrolowany import, eksport PostgreSQL do gzip/manifest, publiczne odczyty official i importer referencyjny. Wyniki testów, recenzji i CI opisuje raport E2. Adaptacja i odbiór Room/APK wymagają osobnej pracy O1. Demo nie jest oficjalnym katalogiem; etykiety official są bramką E5. E3 dostarcza OIDC/PKCE, bootstrap, profil/cele/zgody, kalkulator, modele prywatne i chronione produkty; [raport E3](docs/e3/RAPORT_E3.md) przedstawia dowody odbioru. Synchronizacja pozostaje E4.

Gemini: wyłącznie darmowe API (Free Tier), bez aktywnego billing; CI korzysta z mocka. Darmowe limity są wspólne dla projektu. Ograniczenie udostępniania funkcji Gemini użytkownikom w Polsce/EOG opisuje rozdział 11.6 wymagań; nie blokuje ono prac E0.

## Android — osoba 1

[Kod i instrukcja uruchomienia](android/README.md) · [Plan implementacji](PLAN_IMPLEMENTACJI_ANDROID.md)

Otwórz `android/` w Android Studio. Wersja 0.7.1 działa jako gość bez konta i internetu: dziennik, cele kcal/B/T/W, prywatne produkty, racje ze zjedzonymi składnikami, profil, waga i Postępy 7/30/90 dni.

Room 6 przygotowuje trwałe mapowanie bootstrapu E3 i niezmienne wersje celów. Zmiana celu zachowuje poprzednią decyzję; spóźniona odpowiedź bootstrapu i kolizja kont są odrzucane. Migracje zachowują wcześniejsze wartości, właścicieli i kolejkę. Bieżący dzień jest wstępny; średnie i liczniki obejmują zamknięte dni, z odświeżeniem po północy. Logowanie i HTTP pozostają kolejnym etapem. [Przekazanie E3](android/INTEGRACJA_E3.md) opisuje parametry klienta, [raport 0.7.1](android/RAPORT_0_7_1.md) — testy i granice.

Budowanie i testy jednostkowe: `./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` z katalogu `android/`. Testy urządzenia: `./gradlew :app:connectedValidationAndroidTest`; osobna instalacja testowa zachowuje zwykły dziennik.
