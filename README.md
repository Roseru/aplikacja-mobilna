# Wojskowy licznik kalorii - osoba 2

Projekt aplikacji Android z backendem Python i PostgreSQL, działającej również offline.

- [Wymagania projektowe i podział pracy](WYMAGANIA_PROJEKTOWE.md)
- [Decyzje backendu v1 — Osoba 2](WYMAGANIA_PROJEKTOWE.md#decyzje-osoba-2)
- [Architektura, bazy danych i pakiet racji offline](docs/ARCHITEKTURA.md)
- [Plan etapów, zależności i potrzebne zasoby](docs/PLAN_PRAC.md)
- [Workflow pracy, recenzji, CI i wdrożeń](docs/WORKFLOW.md)

W tym obszarze pracy realizujemy zadania **Osoby 2: backend, baza, API i integracje**. Przyjęty stos to FastAPI, SQLAlchemy, Alembic i PostgreSQL; logowanie przez Keycloak. Maksymalny wspierany okres synchronizacji przyrostowej po pracy offline wynosi **30 dni**. Dłuższa przerwa wymaga pełnego uzgodnienia stanu z zachowaniem lokalnych danych.

Przechowywanie: PostgreSQL z oddzielnymi bazami `keycloak` i `calorie_app`; produkty, racje i profile aplikacyjne w `calorie_app`. Na telefonie Room/SQLite. Katalog startowy i aktualizacje są dostarczane jako JSON gzip i importowane do Room; JSON nie zastępuje roboczej bazy dziennika.

Aktualny stan repozytorium: dokumentacja zespołu oraz lokalna aplikacja Android 0.2.0. Kod backendu, jego migracje, docelowy katalog serwerowy i wykonywalne pipeline GitHub Actions pozostają do zaimplementowania w etapach osób 2 i 3.

## Android — osoba 1

[Kod i instrukcja uruchomienia](android/README.md) · [Plan implementacji](PLAN_IMPLEMENTACJI_ANDROID.md)

Otwórz `android/` w Android Studio. Wersja 0.2.0 działa bez konta i internetu: dziennik, cel kcal/B/T/W, produkty, racje z wyborem zjedzonych składników, gramatura, edycja/usuwanie, jasny i ciemny motyw. Room 2 zachowuje dane wersji 0.1.0 przez migrację.

Katalog zawiera 15 produktów i dwa zestawy **DEMO**. Lokalna kolejka nie wysyła jeszcze danych. Docelowy pakiet katalogu i API wymagają integracji z architekturą osoby 2; szczegóły i ograniczenia w instrukcji Androida.

Budowanie, lint i 6 testów jednostkowych: `./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` z katalogu `android/`. Testy na urządzeniu: `./gradlew :app:connectedValidationAndroidTest` — osobna aplikacja testowa zachowuje zwykły dziennik.