# Android 0.8.0 — klient sesji i izolacja ekranów

Agent 1 / O1, 11 października 2026. Gałąź `codex/android-sesja` z main `f551ecc5072be93c93f8a03b68147138d4dfe0fe`, po scaleniu PR #25 / Android 0.7.3: osiem rzeczywistych success, brak reviews/uwag. Baza Room pozostaje 6; versionCode 11.

## Rezultat

Profil → Konto i logowanie. Klient AppAuth/PKCE, szyfrowany trwały request i sesja, lokalne wylogowanie oraz odnowienie. Przełączenie potwierdzonej tożsamości odbudowuje ekran i repozytorium według nowego lease. Gość pozostaje dostępny; nie importujemy jego danych po zalogowaniu. Konto z nieważnym tokenem nadal prowadzi lokalny dziennik. [Konfiguracja i granice](SESJA_OIDC.md).

Domyślne APK nie zawiera issuer ani sekretów: przycisk logowania jest wyłączony do podłączenia rzeczywistego środowiska. Jest to implementacja klienta i odbiór lokalnej izolacji, **nie ukończony odbiór APK/Keycloak/API**. Na tym komputerze Docker/uv nie były dostępne. Istniejąca dostawa lokalnego środowiska O3 pozostaje odebrana w swoim zakresie; brak runtime tutaj nie unieważnia jej ani nie potwierdza próby mobilnej.

## Wykonane kontrole

Końcowy pełny przebieg Gradle: assembleDebug, testDebugUnitTest, lintDebug i connectedValidationAndroidTest, offline, BUILD SUCCESSFUL 2 min 19 s.

- **73 JVM**, zero failures/errors: wcześniej 67 i 6 nowych metod dotyczących exact issuer/aud/azp, nonce/czasów, zmiany sub przy refresh, niejednoznacznego JWT i callbacku.
- **65/65 urządzenia**, zero failures/errors/skips, API 35 / Android 15, 1080×2400, density 420, font 1,0, tryb samolotowy. To wcześniejsze 56, 7 nowych prób sesji i 2 przepływy UI.
- **Lint: 0 błędów, 28 ostrzeżeń**, bez baseline, pomijania błędów ani suppress callbacku.
- Schemat Room bez migracji i bez zmian encji. Nowa metoda selectIfCurrent łączy kontrolę generacji i wybór w jednej transakcji.

Próby sesji używają **jawnego transportu zastępczego i syntetycznych tokenów**: trwały PKCE/S256 po restartcie kontrolera, błędny state/request, callback replay, wygaśnięcie i offline, refresh ze zmianą sub, A→B→A ze spóźnionym refresh, anulowanie w trakcie wymiany kodu, TTL/przeszła próba, losowy szyfrogram, tamper i utrata klucza, odrzucenie obcego endpointu. Nie dowodzą prawdziwej wymiany tokenów, podpisu Keycloak, systemowej przeglądarki lub TLS APK. Restart kontrolera nie jest zabiciem procesu Androida; ten scenariusz pozostaje w odbiorze rzeczywistym.

UI: gość i nieaktywne logowanie bez konfiguracji, nawigacja po recreation oraz zmiana generacji podczas edycji produktu — niezapisany prywatny formularz znika, dziennik pozostaje, po recreation pole nadal puste. Próba zmiany lease w UI dotyczy gość→gość; A/B wykonano w kontrolerze/Room, nie w przeglądarce.

Wcześniejsze próby: dodanie Java BuildConfig wykazało brak jlink w lokalnym JBR; konfiguracja publiczna trafiła do właściwego zasobu Androida, bez nowej zależności JDK. Lint wykazał ignorowany path bez hosta; wprowadzono dokładną kontrolę callbacku w dedykowanej aktywności. Pierwszy pełny device wykonał 59 przypadków, 57 PASS/2 FAIL: inicjalizacja klasy testów z powodu nie-Unit wyniku metody JUnit oraz porównanie etykiety TextField zamiast EditableText. Obie metody poprawiono; finalny przebieg wykonał wszystkie 65. Nie dodawano retry, skipów ani podwyższonego timeoutu.

## APK i dane użytkownika

Artefakt poza Git: `Racje-i-kalorie-0.8.0-debug.apk`, SHA-256:

```text
baadadc10afcf1057d70470fd1135703f4bd7b04f28570ab9b3005123ae7bf02
```

Rzeczywista instalacja `adb install -r` 0.7.3→0.8.0 zachowała wszystkie kolumny **18 tabel** Room 6, **2 istniejące posiłki**, profile, cele i outbox. Foreign key check pusty. Prywatne zrzuty i screenshot są ignorowane; nie publikowano zawartości dziennika. Zwykłe APK otwarto w widocznym emulatorze na Konto i logowanie, a screenshot obejrzano.

## Manualnie

1. Profil → Konto i logowanie: Gość poligonowy, wyjaśnienie oddzielnych danych, przycisk nieaktywny bez konfiguracji. Wróć do profilu i prowadź dziennik offline.
2. Sprawdź poprzednie wpisy, Postępy, wagę i cele; wybór trybu oraz ręczne kcal z 0.7.3 pozostają.
3. Po przygotowaniu wariantu środowiska O3: prawdziwa przeglądarka/logowanie A, własny wpis, B z pustym odrębnym dziennikiem, ponownie A z zachowanym wpisem. Logout otwiera wcześniejszego gościa. Sprawdź zamknięcie procesu w trakcie logowania oraz po logowaniu.

Bootstrap i chronione read API są następnym PR, synchronizacja E4/WorkManager kolejnym. Zdalny CI odczytujemy dla opublikowanego head osobno; powyższe wyniki nie stanowią jego potwierdzenia.
