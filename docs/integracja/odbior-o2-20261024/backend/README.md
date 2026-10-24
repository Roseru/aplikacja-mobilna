# O2 — publiczny zestaw częściowego odbioru backendu, 24.10.2026

**BLOCKED / WAITING_EXTERNAL.** Kandydat: source `ef4bb4f91ab89abc20b44f3c41b7f8c163f8adfb`, image `sha256:e6e80d58e79194da0569fada30c2ad1260456f18c8390106548b6f37f2e8e6f2`, schema `0026_ledger_review`. To publikacja odebranej części pracy i konkretnych braków; nie zatwierdzenie wdrożenia.

- [backend_acceptance.json](backend_acceptance.json): nowa zredagowana wersja publikacyjna. Jawny original_receipt_sha256 wiąże ją z zachowanym prywatnym receiptca7; nie ma tego samego SHA co oryginał.
- [acceptance_matrix.json](acceptance_matrix.json): rzeczywisty wykonawca, zakres i ograniczenia każdej pozycji.
- [evidence-index.json](evidence-index.json): publiczne GitHub źródła i neutralne hashe; retained_private oznacza zachowane dowody poza Gitem, nie istniejącą ścieżkę repozytorium.
- [CI48.md](CI48.md) i [oryginalny receipt CI48](ci48/backend_acceptance.json): odrębny wariant z istniejącym scoped PASS; nie podmienia ef4/e6e ani nie nadaje nowego PASS.

Własne wykonania O2:118unitPASS;139PG=138PASS/1fixtureFAIL; po korekcie prywatnego bootstrapu3affectedPASS. Nie sumujemy nakładających się zakresów ani nie deklarujemy pełnego rerunu. Migracja24→26 i rzeczywisty app-only pg_dump/pg_restore24 zachowały85 wcześniejszych tabel; nowa epoka i nowe zapisy/replay przeszły. Dwie stare operacje odrzucono przez bezpośrednie preflight() z kodem SyncFailure.code=sync_epoch_changed; ten eksperyment nie obserwował odpowiedzi HTTP. Były to natywne źródła Python/PostgreSQL17 i syntetyczne Principal/TestClient, bez uruchomienia dokładnego OCI/Keycloak. Statyczny audyt dokładnego archiwum nie dowodzi wykonania obrazu.

Pierwszy FAIL i poprzednie JSON/SHA zachowano. Przyczyną FAIL był brak roli bazowej przed migracjami w prywatnym bootstrapie; retest3 potwierdził korektę przygotowania, bez zmiany produktu. Niezależny odbiór oddanej części nie wykazał materialnych P1/P2; nie oznacza to backend PASS.

Właściciel brakującego wejścia: O3 — istniejące zanonimizowane raw komendy/HTTP/porównania tabel i wiązanie exacte6e/schema z próbami. Następnie O2 wykonuje niezależny audyt. [Konkretna prośba](https://github.com/Roseru/aplikacja-mobilna/pull/138#issuecomment-6382347620). Własny Docker/Keycloak O2 nie jest obowiązkowy; lokalne ograniczenie narzędzi nie nakazuje instalacji globalnej ani powtarzania CI.

Surowe XML/logi, dane, kopie baz, konfiguracje i prywatne dzienniki nie są publikowane. Hash artefaktu nie zastępuje jego treści ani dowodu wykonania. Zestaw nie kwalifikuje Androida, telefonu, całegoKO32, produkcji ani niezależnego odzyskania klucza offsite.
