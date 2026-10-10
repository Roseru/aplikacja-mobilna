# Wojskowy licznik kalorii - osoba 2

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

W tym obszarze pracy realizujemy zadania **Osoby 2: backend, baza, API i integracje**. Przyjęty stos to FastAPI, SQLAlchemy, Alembic i PostgreSQL; logowanie przez Keycloak. Maksymalny wspierany okres synchronizacji przyrostowej po pracy offline wynosi **30 dni**. Dłuższa przerwa wymaga pełnego uzgodnienia stanu z zachowaniem lokalnych danych.

Przechowywanie: PostgreSQL z oddzielnymi bazami `keycloak` i `calorie_app`; produkty, racje i profile aplikacyjne w `calorie_app`. Na telefonie Room/SQLite. Katalog startowy i aktualizacje są dostarczane jako JSON gzip i importowane do Room; JSON nie zastępuje roboczej bazy dziennika.

Aktualny stan repozytorium: odebrane E0/E1 oraz implementacja części O2 etapu E2 — katalog, racje, kontrolowany import, eksport PostgreSQL do gzip/manifest, publiczne odczyty official i importer referencyjny. Wyniki testów, recenzji i CI opisuje raport E2. Adaptacja i odbiór Room/APK wymagają osobnej pracy O1. Demo nie jest oficjalnym katalogiem; etykiety official są bramką E5. OIDC i chronione produkty należą do E3, synchronizacja do E4; E3 nie rozpoczęto.

Gemini: wyłącznie darmowe API (Free Tier), bez aktywnego billing; CI korzysta z mocka. Darmowe limity są wspólne dla projektu. Ograniczenie udostępniania funkcji Gemini użytkownikom w Polsce/EOG opisuje rozdział 11.6 wymagań; nie blokuje ono prac E0.
