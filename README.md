# Wojskowy licznik kalorii - osoba 2

Projekt aplikacji Android z backendem Python i PostgreSQL, działającej również offline.

- [Wymagania projektowe i podział pracy](WYMAGANIA_PROJEKTOWE.md)
- [Decyzje backendu v1 — Osoba 2](WYMAGANIA_PROJEKTOWE.md#decyzje-osoba-2)
- [Architektura, bazy danych i pakiet racji offline](docs/ARCHITEKTURA.md)
- [Plan etapów, zależności i potrzebne zasoby](docs/PLAN_PRAC.md)
- [Workflow pracy, recenzji, CI i wdrożeń](docs/WORKFLOW.md)

W tym obszarze pracy realizujemy zadania **Osoby 2: backend, baza, API i integracje**. Przyjęty stos to FastAPI, SQLAlchemy, Alembic i PostgreSQL; logowanie przez Keycloak. Maksymalny wspierany okres synchronizacji przyrostowej po pracy offline wynosi **30 dni**. Dłuższa przerwa wymaga pełnego uzgodnienia stanu z zachowaniem lokalnych danych.

Przechowywanie: PostgreSQL z oddzielnymi bazami `keycloak` i `calorie_app`; produkty, racje i profile aplikacyjne w `calorie_app`. Na telefonie Room/SQLite. Katalog startowy i aktualizacje są dostarczane jako JSON gzip i importowane do Room; JSON nie zastępuje roboczej bazy dziennika.

Aktualny stan repozytorium: dokumentacja, architektura, plan etapów i workflow pracy. Kod backendu, migracje, katalog danych, testy oraz wykonywalne pipeline’y GitHub Actions są do zaimplementowania w opisanych etapach.
