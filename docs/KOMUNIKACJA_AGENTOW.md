# Komunikacja agentów — osoby 1, 2 i 3

Wspólny dziennik przekazania prac między Androidem, backendem i DevOps. Pozwala ustalić, co się zmieniło, kto powinien to przeczytać, jakie są zależności i co wymaga odpowiedzi. Dzięki temu informacje z osobnych rozmów i gałęzi nie giną przy rozpoczynaniu kolejnego zadania.

## Jak korzystać

1. Na początku pracy pobierz aktualne zmiany i przeczytaj ten plik oraz wskazane dokumenty dotyczące swojej roli. Wpis z innej gałęzi czytaj na podanym commicie; jego obecność nie oznacza scalenia do `main`.
2. Po ważnym kroku dopisz wpis ze swoim autorem, datą, odbiorcą, identyfikatorem `O1-001` / `O2-001` / `O3-001`, źródłem i oczekiwaną odpowiedzią. Przy kolejnych wpisach zwiększaj numer w obrębie własnej roli.
3. Oddziel potwierdzone wykonanie od planu i obserwacji cudzej pracy. Podaj commit/PR, zakres testów oraz blokadę, jeżeli istnieje.
4. Odbiorca dopisuje potwierdzenie z datą i przeczytanym commitem, ewentualnie odpowiedź lub nowe pytanie. Autor nie potwierdza odczytu za inną osobę. Statusy: `DO ODCZYTU`, `ODCZYTANE`, `WYMAGA ODPOWIEDZI`, `ZAMKNIĘTE`.
5. Zachowuj wcześniejsze wpisy i odpowiedzi. Zmiana ustalenia dostaje nowy wpis z odniesieniem do poprzedniego; rozbieżność rozstrzygają wymagania, wersjonowane kontrakty i [workflow](WORKFLOW.md).
6. Publikuj aktualizacje przez własną gałąź i PR. Przy konflikcie zachowaj wpisy wszystkich autorów. Ten plik nie wysyła powiadomień automatycznie; wymaga odczytu przez agentów. Zmiany wymagające scalenia i recenzji nadal przechodzą zwykły workflow.

## Stan przekazania

Stan odczytany przez O1, 9 października 2026 r. Każda osoba aktualizuje swój wiersz po wykonaniu kolejnego kroku.

| Rola | Ostatni znany rezultat | Następny krok / zależność | Źródło |
|---|---|---|---|
| O1 — Android, Kotlin, Room | Android 0.3.0; lokalny dziennik, racje DEMO, prywatne produkty, profil, waga i kompletność dnia; Room 3. Kod w PR, jeszcze poza `main` | Import pakietu E2, BigDecimal i migracja zachowująca dane 0.3; następnie analityka 7/30/90 dni | [PR #1](https://github.com/Roseru/aplikacja-mobilna/pull/1), commit `a7bcda8` |
| O2 — Python, PostgreSQL, API | E1 na `main` (`a79b073`); E2 przekazane na gałęzi. Stan E2 pochodzi z odczytu O1, nie z potwierdzenia autora w tym dzienniku | Odbiór i publikacja E2 według workflow; osobna integracja Room/APK po stronie O1 | [Przekazanie E2](https://github.com/Roseru/aplikacja-mobilna/blob/229a2b8/docs/e2/INTEGRACJA_O1.md), commit `229a2b8` |
| O3 — DevOps, CI/CD, serwer | Brak bezpośredniego wpisu O3 w tym dzienniku. Repo zawiera workflow backendu | Potwierdzenie stanu CI Androida, środowiska integracyjnego i dostawy pakietów | [Workflow zespołu](WORKFLOW.md), [CI backendu](../.github/workflows/backend.yml) |

## Wpisy

### O1-001 — Android 0.3.0 przekazany do recenzji

- Data / autor: 2026-10-09, **agent 1 / O1**.
- Odbiorcy: O2, O3.
- Status: **DO ODCZYTU**.
- Źródło: [PR #1](https://github.com/Roseru/aplikacja-mobilna/pull/1), commit `a7bcda8`; [instrukcja Androida](https://github.com/Roseru/aplikacja-mobilna/blob/a7bcda8/android/README.md).
- Przekazanie: lokalny zapis bez konta i internetu, wybór zjedzonych części racji, własny produkt, profil, pomiary wagi i kompletność dnia. Room 3 ma migracje 1 → 2 → 3. Format katalogu/outbox i obliczenia Double pozostają robocze; brak rzeczywistej synchronizacji.
- Dowody O1: APK debug, 6 testów jednostkowych i 17 przypadków urządzenia API 35. Pełny przebieg zaliczył 16 przypadków; profil/wagę zaliczono osobno po poprawieniu obsługi klawiatury w teście. Lint: 0 błędów, 25 ostrzeżeń. Nie potwierdzono zdalnego CI Androida.
- Oczekiwana odpowiedź: O2 potwierdza odczyt aktualnego modelu; O3 potwierdza, czy komendy z instrukcji są podłączone do CI oraz jaki jest sposób udostępniania APK.
- Potwierdzenia / odpowiedzi: brak.

### O1-002 — Wczytanie E2 i różnica wersji Androida

- Data / autor: 2026-10-09, **agent 1 / O1**.
- Odbiorca: O2.
- Status: **WYMAGA ODPOWIEDZI**.
- Źródło: commit `229a2b8`; [instrukcja integracji O1](https://github.com/Roseru/aplikacja-mobilna/blob/229a2b8/docs/e2/INTEGRACJA_O1.md) i [raport E2](https://github.com/Roseru/aplikacja-mobilna/blob/229a2b8/docs/e2/RAPORT_E2.md).
- Potwierdzenie O1: wczytano instrukcję, manifest, raport, dokumentację danych i importera oraz zasady obliczeń. Demo E2 dostarcza 18 produktów, jedną rację i 18 komponentów. Integracja Kotlin/Room/APK jest do wykonania; testy referencyjnego SQLite jej nie zastępują.
- Rozbieżność: przekazanie E2 opisuje Android 0.2.0 / Room 2 (`f5aabfc`), a aktualny PR O1 zawiera 0.3.0 / Room 3 (`a7bcda8`). Nowa migracja musi zachować również prywatne produkty, profil, pomiary wagi i deklaracje dni.
- Następny krok O1: importer manifest/gzip z walidacją i atomową aktywacją generacji, dokładne UUID+revision, g/ml, BigDecimal i wspólne wektory; zachowanie historii, tombstones i całej kolejki. Demo pozostaje niezweryfikowane i jest osadzane w APK.
- Oczekiwana odpowiedź O2: potwierdzenie odczytu zmiany do Room 3 i uwzględnienie aktualnego commita w kolejnym przekazaniu. E2 nie zostało scalone przez O1.
- Potwierdzenia / odpowiedzi: brak.

## Wzór nowego wpisu

```markdown
### O2-001 — Krótki temat

- Data / autor: RRRR-MM-DD, agent / rola.
- Odbiorcy: O1 / O2 / O3.
- Status: DO ODCZYTU.
- Źródło: commit, PR, dokument lub kontrakt.
- Przekazanie: co wykonano i co zmienia się dla odbiorcy.
- Dowody / ograniczenia: wykonane testy i pozostające zależności.
- Oczekiwana odpowiedź / następny krok: konkretne działanie albo „informacyjnie”.
- Potwierdzenia / odpowiedzi: odbiorca dopisuje datę, przeczytany commit i wynik.
```
