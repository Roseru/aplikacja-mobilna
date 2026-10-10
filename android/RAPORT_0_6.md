# Android 0.6.0 — fundament izolacji kont

Agent 1 / O1, 10 października 2026 r. Gałąź `codex/android-izolacja-kont` zależy od `2a73c74` w [PR #6](https://github.com/Roseru/aplikacja-mobilna/pull/6). Jej PR porównuje się z `codex/android-analityka`, aby pokazywać wyłącznie nowy etap. Kolejność odbioru: PR #1, potem #6, potem izolacja. Po scaleniu poprzedniego etapu należy skierować kolejny PR na aktualny main i sprawdzić integrację bez przepisywania opublikowanej historii. Nie scalono własnych PR-ów.

## Zakres

- Room 5 dodaje `local_owners` i `local_active_owner`. Trwały UUID gościa pozostaje związany z dawnym aliasem `guest`; wszystkie wcześniejsze kolumny, ID, snapshoty i payloady kolejki są zachowane. Nie ma kasujących migracji.
- Konta są lokalnie rozróżniane przez dokładne `(issuer, sub)`. Wystawca musi być HTTPS, z wyjątkiem HTTP loopback do rozwoju, bez credentials/query/fragment; podmiot jest niepusty, bez otaczających spacji i znaków sterujących, maksymalnie 255 znaków. Rejestracja jest idempotentna i sama nie wybiera konta.
- Wybór właściciela atomowo zmienia zakres i zwiększa generację. Powrót do tego samego konta również unieważnia poprzednie lease. Nie przenosi danych pomiędzy gościem a kontami.
- Repozytorium wiąże się z zakresem/generacją; każda mutacja sprawdza je w tej samej transakcji co encja i outbox. Nieaktualny zapis jest odrzucany przez `StaleOwnerException`, bez zapisu do poprzedniego lub nowego konta. Domyślne repozytorium gościa nie zapisuje, jeśli aktywny jest zakres konta.
- Dziennik, prywatne produkty, profil, cele, waga, kompletność, ostatnie produkty, analityka oraz kolejka są odczytywane według właściciela. Katalog jest współdzielony; zjedzone składniki tej samej racji mają prywatne snapshoty i ilości.
- Operacje na obcych posiłkach/składnikach/pomiarach są odrzucane. Dodatkowo kolizja ID pomiaru nie może wykorzystać `Upsert` do nadpisania innego właściciela. Kolizje globalnych ID posiłku/produktu kończą się rollbackiem.
- Konta nie otrzymują demonstracyjnego celu gościa. Zwykła aplikacja nadal uruchamia się jako gość; nie dodano UI logowania, sieci, tokenów ani wyboru kont.

## Walidacja

- `:app:assembleDebug :app:testDebugUnitTest :app:lintDebug`: zaliczone; 51 testów JVM, 0 błędów lint / 26 ostrzeżeń i 1 informacja. Nie dodano nowych ostrzeżeń kompilatora.
- Pełny końcowy `:app:connectedValidationAndroidTest`: 39/39, bez błędów i pominięć na API 35. Zawiera 31 wcześniejszych przypadków i osiem nowych przypadków właścicieli. Wcześniejszy pełny przebieg 38/38 także przeszedł; ostatni dodaje sprawdzenie prywatnego spożycia wspólnej racji.
- Nowe przypadki: dokładna tożsamość i walidacja bez aktywacji, gość + dwa konta, prywatna analityka/kolejka, obce ID i kolizje, identyczna racja z różnymi porcjami, opóźniony zapis po zmianie konta i powrocie do niego, rollback szkicu/posiłku po awarii zapisu outbox, restart aktywnego właściciela, migracja rzeczywistego schematu 4.
- Próba 4→5 tworzy bazę według wersjonowanego JSON schematu 4 i zasila wszystkie 14 dawnych tabel reprezentatywnymi danymi, w tym dokładnym E2, prywatnym produktem, wersjami celów, profilem, kompletnym dniem, wagą, tombstones oraz pending/acked outbox. Porównuje każdą wcześniejszą kolumnę i sprawdza klucze obce. Dotychczasowe próby aktualizacji 1/2/3 zostały rozszerzone do schematu 5 i również przeszły.
- APK zainstalowano jako aktualizację rzeczywistego 0.5.0 bez kasowania danych. Przed/po porównano wszystkie kolumny wszystkich 14 dawnych tabel; istniejący dziennik i kolejka zachowane. Uruchomiono dziennik w trybie samolotowym, potwierdzono versionCode 6 / 0.6.0. Testy mają osobne `pl.roseru.kalorie.validation`; nie kasują zwykłego dziennika.

Raporty lokalne: `app/build/test-results/`, `app/build/reports/`, `app/build/outputs/androidTest-results/`. Nie potwierdzono zdalnego CI. Lokalny APK poza Git: `output-apk/Racje-i-kalorie-0.6.0-debug.apk`, SHA-256 `5853d41c005119f9efe75c754b7760bc5eeae50b802138c1a452fdd47cc98809`.

## Granice i następny etap

Rejestr jest metadanymi lokalnymi, nie dowodem uwierzytelnienia. Nie ma jeszcze OIDC/PKCE, przełączania kont w UI, WorkManager, push/pull ani importu gościa. Próba opóźnienia obejmuje lokalną mutację, nie odpowiedź prawdziwego HTTP. Przy sesjach należy odtwarzać repozytorium/ViewModel dla aktualnego lease, anulować odczyty i czyścić stan ekranów; stary ViewModel pozostaje związany ze swoim zakresem do zakończenia jego cyklu życia.

Docelowa architektura O2 wymaga kluczy z właścicielem i zabezpieczeń zapisu/wysyłki workerów. Obecne tabele zachowują globalne ID; odrzucona kolizja nie obsługuje dwóch importowanych serwerowych rekordów z tym samym ID. Bieżący outbox pozostaje roboczy i nie jest wysyłany. Adapter E0 musi jawnie mapować właścicieli, identyfikatory i Decimal, zachowując oryginalną kolejkę oraz snapshoty. Przypisanie gościa wymaga jawnej zgody i trwałego potwierdzenia; nie dokonano go automatycznie.

O2: potrzebne endpointy E3/E4 i konfiguracja tożsamości; katalog E2 nie zastępuje kont ani sync. O3: potrzebne parametry środowiska mobilnego, workflow Androida i sposób dostawy APK. Osobny import materiałów MRE 2026 pozostaje zadaniem katalogu, bez sumowania wariantów lub zbiorczych dodatków.
