# Przekazanie wyników O2 — osoba 2

Stan na 24 października 2026 r. To wspólny punkt wejścia do opublikowanych wyników. A/B/C są już scalone; nowy konsument polityki sieci pozostaje WIP, a pełny odbiór kandydata backendu czeka na konkretne wejście O3. Publikacja raportów nie zmienia tych decyzji.

| Obszar | Stan i źródło | Następne działanie |
|---|---|---|
| Android A/B/C | A [PR148](https://github.com/Roseru/aplikacja-mobilna/pull/148), B [PR156](https://github.com/Roseru/aplikacja-mobilna/pull/156), C [PR157](https://github.com/Roseru/aplikacja-mobilna/pull/157) scalone; C merge `b2450778e731620f5719c0f114f351a36bcfd439`, osobny FULL main CI40033329352 attempt2: 8 success | O1 integruje dalszy katalog/provider; te wyniki nie kwalifikują nowej polityki sieci ani pełnego E4/v1 |
| Konsument wspólnej polityki sieci | Źródła wypchnięte jako WIP: `codex/android-o2-polityka-runtime`, [be6c4230](https://github.com/Roseru/aplikacja-mobilna/commit/be6c42303b5af5c6e62cafb804b38b558a5ddb09); 11 plików względem bazy O1 `4f6bb841818daa5b0823132a2120106dd97c3c61`; dwa P2 nadal otwarte | O1 dostarcza dwa porty poniżej; O2 integruje i ponawia odpowiednie kontrpróby przed PR/merge kodu |
| Backend ef4/e6e/schema26 | [Częściowy raport](backend/README.md), [receipt BLOCKED](backend/backend_acceptance.json), [macierz](backend/acceptance_matrix.json) | O3 udostępnia istniejący raw łańcuch obrazu/wykonania i pokrycie prób; O2 audytuje |
| Osobny CI48/config020b/import817 | [Istniejący wąski PASS i granice](backend/CI48.md), [oryginalny receipt](backend/ci48/backend_acceptance.json) | O3/root potwierdzają docelowy wariant oraz wiązanie archive/config/layers/runtime i dodatkowe próby używanej0024 |

## Co O1 otrzymuje do integracji

[runtime.json](runtime.json) zawiera dokładne Git blob SHA-256 11 plików, kontrakty konstruktorów, oddzielne zakresy testów i ograniczenia. Ta gałąź jest źródłem do przeglądu; ma znane błędy i nie została scalona do main ani do O1. Nowe CI publikacji dokumentów nie zastępuje odbioru tego kodu.

Potrzebne wejścia O1, zgłoszone w [istniejącym wątku PR146](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6382259951):

1. Typowany adapter sesji `SavedSyncEvidenceDrainer.drainSavedSyncEvidence(expectedLease: OwnerLease, expectedContext: AccountBindingEntity)`, który stosuje zapisane ACK/raw wyłącznie lokalnie, z dotychczasowymi kontrolami właściciela/kontekstu, bez refresh/HTTP. Zwykły PULL może wykonać GET/refresh i nie spełnia tej granicy. Wynik `APPLIED` oznacza zastosowane lokalne dowody, a nie świeży PULL ani ukończenie cyklu.
2. Obserwowalna generacja/instancja każdego wydania i cofnięcia zgody na jednym współdzielonym gate. Sama rewizja i `StateFlow` mogą zgubić przejście `Allowed(7) → Blocked → Allowed(7)`. Ticket, wykonanie i reschedule muszą pozostać związane z pierwotną instancją zgody. Obecne dwa P2 to ponowna autoryzacja starego ticketu i brak anulowania zawieszonego executora/mutexu po takim ABA.

O1 przypina dostawę commitem lub jawnie deleguje ograniczoną zmianę. O2 nie zmienia sam zarezerwowanych provider/core/session/root/Room23. Po dostawie O2 domyka konsumenta, sprawdza kontrpróby i rzeczywistą ścieżkę adaptera. Historyczne serie 3 (0 PASS/3 FAIL), 33 (29/4), 12 (11/1) i finalna poprawiona próba restartu 1/1 mają różne, częściowo wspólne zakresy; nie sumujemy ich ani nie deklarujemy pełnego PASS. Surowe XML/logi zachowano poza Gitem; publiczne hashe jawnie oznaczają tę dostępność.

## Co O3 otrzymuje do odbioru backendu

O2 potwierdził dokładne źródła/warstwy archiwum ef4/e6e, wykonał 118 unit PASS oraz 139 PG = 138 PASS/1 FAIL prywatnego bootstrapu; trzy dotknięte testy po jego korekcie przeszły. Próba natywna PG17 zachowała 85 tabel przy migracji24→26 i app-only restore24, sprawdziła nową epokę oraz dwa nowe zapisy/replay. Dwie stare operacje odrzucono bezpośrednio w `preflight()` z `SyncFailure.code=sync_epoch_changed`; nie obserwowano w tej próbie odpowiedzi HTTP. Wyniki nie potwierdzają uruchomienia dokładnego OCI ani paired Keycloak/PKCE.

O3 przekazuje istniejące zanonimizowane raw komendy, HTTP i porównania tabel powiązane z immutable image/config/layers/runtime/schema oraz brakującym zakresem API/sync/migration/paired restore/session fence/rollback. [Prośba o dowody](https://github.com/Roseru/aplikacja-mobilna/pull/138#issuecomment-6382347620) i [wybór ef4/e6e albo następcy CI48](https://github.com/Roseru/aplikacja-mobilna/pull/138#issuecomment-6382524766) pozostają otwarte. Własna instalacja Docker/Keycloak przez O2 nie jest wymagana, jeśli można niezależnie odebrać rzeczywiste wykonanie O3. Małe podsumowania i sam hash nie zastępują raw dowodu.

## Integralność i granice publikacji

[FILES.json](FILES.json) wylicza dokładne bajty UTF-8/LF tego zestawu; [manifest backendu](backend/PUBLIC_FILES.json) wylicza jego sześć plików. Oryginalny receipt CI48 pozostaje identyczny: 364 B / `8c4db21735d6c1985f494e0826c383f8db947607c99a3e942ab6c8c2442b753e`. Zredagowana wersja ef4/e6e jest nowym plikiem, z jawnym SHA zachowanego oryginału. Pierwszych FAIL i starych receiptów nie nadpisano.

Nie publikujemy sekretów, lokalnych ścieżek/tożsamości, danych i kopii baz, buildów/APK, surowych logów ani prywatnego dziennika. Brak pełnego odbioru backendu, nowej polityki sieci, telefonu i KO32 pozostaje jawny. Jedyny wspólny dziennik i odpowiedzi zespołu: [KOMUNIKACJA_AGENTOW](../../KOMUNIKACJA_AGENTOW.md), wpis O2-061.
