# Kontekst współpracy

- Użytkownik jest osobą 1 w zespole: odpowiada za aplikację Android (Kotlin, Android Studio), interfejs, pamięć lokalną i mobilną część synchronizacji.
- Podział pracy i wymagania: `WYMAGANIA_PROJEKTOWE.md`.
- Użytkownik zaakceptował oba warianty makiet: A (ciemny) i B (jasny). Aplikacja ma oferować oba jako motywy tego samego interfejsu.
- Obecny etap: pierwsza lokalna wersja Androida w `android/` jest zaimplementowana: dziennik, wybór produktu i gramatury, trwały zapis Room, edycja/usuwanie, cele i oba motywy. Kolejka zmian jest lokalna; rzeczywista synchronizacja i racje są kolejnymi etapami. Katalog zawiera 12 produktów demonstracyjnych.
- Plan implementacji wysłano na GitHub jako commit `74d3d1c` z autorem `agent 1`. Użytkownik poprosił o takie oznaczenie commita.
- Szczegółowa kolejność prac: `PLAN_IMPLEMENTACJI_ANDROID.md`.
- Repozytorium projektu: https://github.com/Roseru/aplikacja-mobilna
- Użytkownik chce aktualizacji GitHuba po ważnych, przetestowanych etapach; commity podpisujemy jako `agent 1`. Zgoda obejmuje publikację kodu projektu i dokumentacji, bez sekretów, lokalnych ścieżek, cache i danych dziennika.
- Wersja Androida 0.2.0 dodaje racje wieloskładnikowe: zaznaczanie zjedzonych części, gramatura, korekty/usuwanie pojedynczego składnika i całej racji. Room 2 ma sprawdzoną migrację 1 → 2. Katalog: 15 produktów i dwa zestawy DEMO, nie rzeczywiste S-R/S-RG. Przeszło 6 testów jednostkowych i 11 testów na API 35 (test migracji powtórzony po naprawie danych testowych).
- Po aktualizacji `origin/main` do `0b792d1` obowiązują dokumenty osoby 2: `docs/ARCHITEKTURA.md`, `docs/PLAN_PRAC.md`, `docs/WORKFLOW.md`. Publikujemy kod przez gałąź i PR. Docelowy importer gzip/manifest, identyfikatory UUID, generacje katalogu, Decimal/BigDecimal i sync wymagają integracji z formalnymi przykładami osoby 2; lokalny format 0.2.0 jest roboczy.
