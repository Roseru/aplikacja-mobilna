# Wojskowy licznik kalorii
Aplikacja Android prowadzi dziennik posiłków, produktów, racji i masy ciała
również offline. Konto oraz synchronizację obsługują FastAPI, PostgreSQL
oraz Keycloak. Telefon używa Room/SQLite; źródłowy katalog JSON jest
importowany do bazy i zachowuje pochodzenie danych.

## Od czego zacząć

Decyzja właściciela z31.10.2026: bieżącą dostawą jest działająca instalacja
**lokalna, MRE/DEMO, ręczne ścieżki i MOCK**. ARPOL, VPS/domena i rzeczywiste
Gemini są odłożone; obecnie nie podłączamy Gemini ani billing. Prosta obsługa
odebranego zestawu Docker i zachowanie danych są opisane w
[instrukcji lokalnego wydania](infra/integration/LOCAL_RELEASE.md).

- **Gość offline:** otwórz `android/` w Android Studio według
  [instrukcji Androida](android/README.md#uruchomienie-w-android-studio).
  Bez adresów API/OIDC działa lokalny dziennik.
- **Własne środowisko APK/API:** użyj istniejących komend z
  [instrukcji integracji](infra/local/integration/README.md).
  Inicjalizacja nowego środowiska i wznowienie istniejących danych mają
  osobne ścieżki; zachowaj wskazane tam kontrole i kopie.
- **Budowa i odbiór:** [komendy CI i APK](android/README.md#komendy-dla-osoby-3--ci),
  [workflow](docs/WORKFLOW.md) oraz
  [jedyny dziennik zespołu](docs/KOMUNIKACJA_AGENTOW.md).

Bieżące źródło Androida to **0.8.45 / code56 / Room27**; oddzielny wariant
validation ma code1056. Pierwszy zapis domyślnego profilu zachowuje istniejący
cel i jego audyt. Pełny i przyrostowy PULL oddzielają oś E od dotychczasowych
domen dziennika, więc cel i wyprowadzone z niego początkowe E mogą mieć ten sam identyfikator.
Zapisane strony i potwierdzenia Room27 pozostają zachowane.
Klient porównuje też równoważne zapisy czasu UTC przy
projekcji potwierdzonego posiłku i rzetelnie opisuje lokalną kopię zdjęcia.
[PR193](https://github.com/Roseru/aplikacja-mobilna/pull/193)
łączy poprawkę zimnego startu, odczyty synchronizacji i własne środowisko
integracyjne. Odebrano w nim rzeczywistą ścieżkę APK/API: przerwanie po
otrzymaniu ACK przed jego lokalnym zapisem, ponowienie bez duplikatu,
PULL i restart offline. CI tego PR przeszedł
8/8 kontroli. Techniczny przepływ zdjęcia MOCK ma osobny odbiór po naprawie
klienta 0.8.42, obejmujący zapis, PULL i odczyt offline. Nie oznacza to
odbioru całego wydania 1.0: rzeczywiste Gemini, pełne E9, odtwarzanie
i warunki wydania mają osobne dowody i bramki
opisane w dzienniku. Osobny [provider rejestracji](infra/keycloak-email-proof/README.md)
wymaga potwierdzenia e-mail przed sprawdzaniem konta; jego instalacja i odbiór
istniejącego realm są świadomym krokiem operatora.

Przed testem zdjęć przygotuj prywatny katalog z wymaganymi prawami,
osobny minimalny login workera i zgodny profil oraz pulę MOCK według
[instrukcji E7](docs/e7/KONFIGURACJA_O3.md#prywatny-mount-i-worker).
Na Windows katalog zdjęć wymaga własnego chronionego DACL; samo utworzenie
podfolderu nie spełnia tej kontroli. API pokazuje dostępność dopiero po
poprawnej konfiguracji.

## Historia wybranych dostaw Androida

Poniższe wersje i liczby testów opisują ich własne historyczne zakresy.
Aktualne polecenia uruchomienia znajdują się w instrukcjach powyżej.

Android **0.8.39** dodaje trwałe podglądy osiągnięć, rankingu i Nemesis z datą pobrania i usuwaniem własnej kopii. Osobne stany historyczne nie nadają uprawnień do zgód, decyzji lub kolejnych stron. [Raport](android/RAPORT_0_8_39.md): Room26→27 zachował wszystkie54 poprzednie tabele/rowid/treści; dziewięć unikalnych native PASS w zakresach4+5, sześć testów zmienionego guardu JVM i lint0Error/0Fatal. Wcześniejsze błędy fixture i ograniczenia rzeczywistego API pozostają opisane osobno.

Android **0.8.12** dodaje lokalne zdjęcia z aparatu i galerii, trwały podgląd/usuwanie w aktywnym profilu oraz ręczny fallback. Poprawia Done w edycji gramatury. [Raport](android/RAPORT_0_8_12.md):165 JVM/21 końcowych zmienionych testów PASS; wcześniejsze188/186PASS+2RED zachowane osobno. Room8→9 zachował wszystkie stare kolumny22tabel/5posiłków. Upload/Gemini/confirm/sync i rzeczywisty APK/API nadal mają dalsze odbiory.

Android **0.8.11** dodaje kody i zaproszenia Nemesis, świadomą akceptację zakresów oraz zakończenie udostępniania. Dokładna decyzja jest zapisana przed HTTP i ponawiana ręcznie tym samym kluczem po utracie odpowiedzi. [Raport i podglądy](android/RAPORT_0_8_11.md):165 JVM/179 pełny device dla pierwszego źródła, końcowe4 formularze po poprawce klawiatury osobno; Room8 bez migracji,22tabele/5posiłków zachowane. Gęstszy ranking, osiągnięcia i Postępy pozostają zachowane. Rzeczywisty pairing APK/API, E4/recovery i klientE9 wymagają dalszych odbiorów.

Android **0.8.10** dodaje odczyt Nemesis: listę rywalizacji, uzgodnione zasady, punkty oraz dozwolone porównania. Pending/hidden/null/zero są oddzielne, a powrót na ekran ponownie sprawdza udostępnianie. [Raport i podglądy](android/RAPORT_0_8_10.md):155 JVM/168 pełny device i końcowe72 affected osobno; Room8 bez migracji,5posiłków zachowane. Zaproszenia/accept/cancel i realny API mają dalsze odbiory.

Android **0.8.9** zagęszcza ranking zgodnie z feedbackiem: wspólny wiersz pozycji/punktów i mniejsze odstępy, z czytelnym układem przy dużym tekście. Poprawia rozróżnienie deklaracji zgody i aktywnego automatu po przekazaniu E9. [Raport i podglądy](android/RAPORT_0_8_9.md):144 JVM i18 zmienionych testów urządzenia PASS, Room8 bez migracji,22tabele/5posiłków zachowane. Nemesis, klientE9 i rzeczywisty API mają dalsze etapy.

Android **0.8.8** dodaje listę rankingu: pozycje serwerowe i remisy, punkty, rangi, liczba odznak i kolejne live pages. Odczyt nie wyraża zgody, a osoby/cursory są usuwane po wyjściu, zmianie konta lub kontekstu. [Raport i podglądy](android/RAPORT_0_8_8.md):144JVM/156device pełnyPASS, końcowe14UI+nawigacji i3QA mierzonego320dp rozdzielone. Room8 bez migracji;22tabele/5posiłków zachowane. Rzeczywisty API/OIDC/TLS, Nemesis i pełne E4 mają dalsze odbiory.

Android **0.8.7** dodaje świadome zarządzanie udziałem w rankingu. Odczyt nie włącza zgody; utrata odpowiedzi pozwala ponowić tę samą zatwierdzoną decyzję. Mniejsze podsumowanie i więcej widocznych odznak z 0.8.6 pozostają zachowane. [Raport i podglądy](android/RAPORT_0_8_7.md): 135 JVM i nowy pełny147device PASS po poprawkach testu, historyczne146/147 i11/11 rozdzielone. Room8 bez migracji; aktualizacja zachowała wszystkie 22 tabele. Rzeczywisty odbiór API, publiczna lista rankingu, E4 i Nemesis mają dalsze etapy.

Android **0.8.6** zmniejsza podsumowanie osiągnięć i pokazuje odznaki przed panelem serwera. Dodaje prywatne, ręczne pobranie potwierdzenia własnych punktów/rangi/odznak po logowaniu i bootstrapie. [Raport i podglądy](android/RAPORT_0_8_6.md): pełny126JVM/129device dla odczytu/sesji oraz końcowe18UI po feedbacku; Room8 bez migracji, wszystkie dane22tabel/5posiłków zachowane. Postępy bez zmian; zgody rankingu, E4 i Nemesis mają dalsze etapy.

Android **0.8.5** dodaje cztery lokalne osiągnięcia w „Profil → Osiągnięcia”, z najlepszym postępem całej historii, datami spełnienia i osobnym stanem potwierdzenia serwerowego. Zachowuje zaakceptowany wygląd Postępów7/30/90. [Raport i podglądy](android/RAPORT_0_8_5.md):115JVM/117device PASS, Room8; aktualizacja zachowała wszystkie dotychczasowe kolumny22tabel/5posiłków. [Aktualny plan O1](PLAN_IMPLEMENTACJI_ANDROID.md) obejmuje potwierdzenie serwerowe, NEMESIS i dalszą synchronizację.

## Projekt i dokumentacja

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

Historyczny opis dostawy backendu E2: odebrane E0/E1 oraz implementacja części O2 etapu E2 — katalog, racje, kontrolowany import, eksport PostgreSQL do gzip/manifest, publiczne odczyty official i importer referencyjny. Wyniki testów, recenzji i CI opisuje raport E2. Adaptacja i odbiór Room/APK wymagają osobnej pracy O1. Demo nie jest oficjalnym katalogiem; etykiety official są bramką E5. E3 dostarcza OIDC/PKCE, bootstrap, profil/cele/zgody, kalkulator, modele prywatne i chronione produkty; [raport E3](docs/e3/RAPORT_E3.md) przedstawia dowody odbioru. Synchronizacja pozostaje E4.

Gemini: wyłącznie darmowe API (Free Tier), bez aktywnego billing; CI korzysta z mocka. Darmowe limity są wspólne dla projektu. Ograniczenie udostępniania funkcji Gemini użytkownikom w Polsce/EOG opisuje rozdział 11.6 wymagań; nie blokuje ono prac E0.

## Android — osoba 1

[Kod i instrukcja uruchomienia](android/README.md) · [Plan implementacji](PLAN_IMPLEMENTACJI_ANDROID.md)

Historyczny fundament klienta: wersja 0.8.5 łączy sesję AppAuth/PKCE i trwały bootstrap HTTP z [podglądem profilu serwerowego](android/ODCZYT_PROFILU.md), zachowując lokalny profil i cel kcal. [Konfiguracja i granice odbioru](android/BOOTSTRAP_HTTP.md). Domyślnie bez issuer i adresu API nadal działa jako gość offline: dziennik, cele kcal/B/T/W, prywatne produkty, racje ze zjedzonymi składnikami, profil, waga i Postępy 7/30/90 dni.

Historyczny Room8 przechowuje zapisane pochodzenie nowych składników racji oraz trwałe mapowanie bootstrapu E3, niezmienne wersje celów i osobne archiwum stron sync/pull. Zmiana celu zachowuje poprzednią decyzję; spóźniona odpowiedź bootstrapu i kolizja kont są odrzucane. Migracje zachowują wcześniejsze wartości, właścicieli i kolejkę. Bieżący dzień jest wstępny; średnie i liczniki obejmują zamknięte dni, z odświeżeniem po północy. [Raport 0.8.2](android/RAPORT_0_8_2.md) opisuje lokalny odbiór; prawdziwy test APK/HTTPS/Keycloak i synchronizacja nadal wymagają integracji. Bootstrap nie przenosi gościa ani nie potwierdza wysłania dziennika. [Konfiguracja OIDC](android/SESJA_OIDC.md). [Przekazanie E3](android/INTEGRACJA_E3.md) opisuje parametry klienta, [raport 0.7.1](android/RAPORT_0_7_1.md) — testy i granice.

Budowanie i testy jednostkowe: `./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` z katalogu `android/`. Testy urządzenia: `./gradlew :app:connectedValidationAndroidTest`; osobna instalacja testowa zachowuje zwykły dziennik.

[Android 0.7.2 — przewijanie, klawiatura i testy manualne](android/RAPORT_0_7_2.md).
