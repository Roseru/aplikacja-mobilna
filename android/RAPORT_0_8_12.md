# Android 0.8.12 — lokalne zdjęcia posiłków

Dodaj posiłek → Zdjęcie posiłku pozwala wybrać obraz z galerii lub zrobić zdjęcie aparatem, zapisać jego prywatną kopię, obejrzeć ją po restarcie i jawnie usunąć. Funkcja działa bez konta i internetu. Ręczny wpis pozostaje dostępny; sam obraz nie tworzy posiłku i nie jest wysyłany.

Źródło: `9253b720559f96e404907aa57e580fafe6a13ed5`, `codex/android-zdjecia-posilkow`, versionCode23. Room8→9 dodaje wyłącznie tabelę meal_photo_drafts. Parent to dokładny head `2202f13255b0e8b79c21cdb526c1b618e8f0fc9e` / PR61; nowy etap nie jest scalany do oczekującej gałęzi. APK poza Git: Racje-i-kalorie-0.8.12-debug.apk, SHA256 `55ca0d0f00d89552e0ba978cf5f575ebb427766e9802d6902b5dc79d9f15721f`.

## Zachowanie i dane

- PhotoPicker udostępnia wybrany obraz, a TakePicture zapisuje plik w ograniczonym katalogu cache przez nieeksportowany FileProvider. Aplikacja nie wymaga dostępu do całej galerii lub uprawnienia CAMERA dla własnego procesu. Provider aparatu nie udostępnia trwałych kopii ani dziennika.
- Wejście ma limit20MiB/64mln pikseli/16000px na bok. Przygotowanie poprawia orientację EXIF, odrzuca animacje, skaluje dłuższy bok do1600px, daje białe tło i koduje JPEG90 bez źródłowych metadanych. Wynik ma najwyżej5MiB, utrwalony SHA256 i niezależną kopię bajtów. Backend ponownie przygotuje i zwaliduje obraz przy późniejszej wysyłce.
- Obraz jest atomowo zapisywany w prywatnych files, a metadata w transakcji Room pod aktywnym ownerScope. Data pochodzi z dnia wybranego przed uruchomieniem galerii/aparatu. Uri źródła nie trafia do Room; lokalna kopia nie zależy od dalszego dostępu do oryginału. Pamięć obrazu i odczyt pliku są ograniczone.
- Zmiana konta/lease/A→B→A blokuje stary import, podgląd i usuwanie. Kopie pozostają w pierwotnym profilu; nie ma automatycznego przypisania zdjęć gościa. Anulowany lub spóźniony callback nie tworzy drugiego wpisu. Pending wyboru można odtworzyć ze SavedStateHandle tego samego profilu albo anulować. Surowy plik aparatu jest usuwany po obsłużeniu wyniku; utrata właściciela VM usuwa jego pending capture i uprawnienie.
- Usunięcie kopii wymaga potwierdzenia. Nie usuwa oryginału z galerii, posiłków, celu lub kolejki. Nie wprowadzono operacji uploadu, zgody do modelu, produktów, posiłków lub sync z samego wyboru.
- Naprawiono odtworzony problem edycji gramatury: Done przenosi fokus do istniejącego przycisku Zapisz w tym samym dialogu i zamyka klawiaturę. Nie zapisuje danych bez kliknięcia przycisku. Wygląd Postępów, kompaktowych osiągnięć i rankingu pozostaje zachowany.

Dokumentacja użytych kontraktów Androida: [PhotoPicker](https://developer.android.com/training/data-storage/shared/photo-picker), [TakePicture](https://developer.android.com/reference/androidx/activity/result/contract/ActivityResultContracts.TakePicture), [ExifInterface1.4.2](https://developer.android.com/jetpack/androidx/releases/exifinterface). Biblioteka jest przypięta w katalogu wersji; pozostałych zależności nie aktualizowano.

## Weryfikacja i historia błędów

Końcowy build/debug,165 JVM i lint0error/28warning/1info PASS.24 warning dotyczą dostępnych aktualizacji wcześniej przypiętych zależności, pozostałe dotyczą istniejących deklaracji/UI. Końcowe21 testów urządzenia API35 PASS, failures/errors/skipped0,186.94s urządzenie, pipeline7m37s:12DiaryFlow+6PhotoStorage+2PhotoScreen+1PhotoAdaptive. Sprawdzono prywatny plik, SHA/bounds, orientację/GPS/białe tło, oryginalny dzień, callback/restoration, brak nowego posiłku/outbox, izolację/ABA, preview/restart/delete, manual fallback oraz320dp/tekst150%.

Pełne188 przypadków uruchomiono wcześniej dwa razy; oba przebiegi miały186PASS/2RED. Pierwszy ujawnił dwa nowe błędne założenia fixture: domyślną wartość EXIF i ścieżkę schematu. Drugi wykazał opcjonalną nieobecność indices w niezmiennym JSON Room8 i problem fokusu dialogu edycji. Po poprawce fixture osobne6PhotoStorage przeszły, a pojedynczy DiaryFlow nadal odtworzył błąd. Poprawiono rzeczywistą obsługę Done i odebrano cały zmieniony zakres21 oraz JVM/lint. Wyników nie sumujemy ani nie opisujemy jako lokalnego final188. Pełny zdalny CI końcowego head otrzyma własny wynik.

Wcześniej kompilacja fixture EXIF, rename cache Gradle i brak podłączonego emulatora zatrzymały próby przed uruchomieniem testów. Nie zaliczono ich jako native PASS. Po potwierdzeniu braku procesu wznowiono ten sam AVD bez wipe; jednorazowy retry cache wystarczył, bez kasowania cache/danych. Raporty błędów zachowane prywatnie.

Migracja na niezmiennym schemacie8 i danych22tabel zachowuje wszystkie stare kolumny; nowa tabela pozostaje pusta. Install-r zwykłego APK naemulator-5554 oraz baseline po pierwszym i ponownym uruchomieniu potwierdziły identyczne22tabele/5posiłków i czyste FK; Room9/23tabele. Wersja/schema zmieniają się dopiero przy starcie, więc kontrola wykonana bezpośrednio po instalacji jeszcze przed uruchomieniem widziała8; nie była wynikiem migracji lub utratą danych. Bez clear/uninstall. Prywatny dziennik, baseline, logi i zrzut produkcyjny poza Git.

![Lokalne zdjęcia — syntetyczny obraz validation](../propozycje-ui/zdjecia-0.8.12/light.png)

Publiczny PNG przedstawia syntetyczny zielony obraz testowy, nie prawdziwe jedzenie lub zdjęcie użytkownika. Próba logicznego callbacku aparatu nie zastępuje ręcznego odbioru fizycznego aparatu/systemowej galerii.

## Następne odbiory i współpraca

O2-033 z PR62/d4f8657 przeczytany; własna odpowiedź O1-028 i kolejność są w dzienniku. Ten etap jest pierwszą częścią E7. Capabilities/provider/profile/notice, świadomy multipart z dokładną intencją/key/epoch, poll/cancel, edycja dopasowań i confirm/provenance/Room/outbox oraz standardowy push/ACK nadal wymagają implementacji i odbioru. Confirm nie będzie drugim zapisem dziennika lub publikacją produktu. E4/WorkManager/import/recovery i pełny klientE9 nadal są wymagane.

Przeczytano nowe O3-025/main `76fcdbf26a079691d258183f95c5f3e3418aeb43`/PR63 oraz ANDROID_TRANSPORT. O3 ma własny transport AVD5560 i VM TLS/discovery/readiness PASS z zachowaniem issuer; O1 nie przypisuje sobie tego wyniku. Na stanowisku O1 aktualnyadb5037 pokazuje wyłącznie5554, a wskazanego handoff nie ma w primary, clone lub dokładnym katalogu handoff istniejących Temp/codex* checkoutów. Potrzebny dostępny neutralny pakiet/publicCA/overlay/lease i aktualny AVD lub opis transportu między stanowiskami. To różnica rzeczywistego wejścia, nie diagnoza niedostępności środowiska O3.

Dokument O3 podaje też wcześniejszą odmowę automatycznej kontroli uruchomienia Chrome przez CLI; O1 nie obchodził jej inną formą launch. Rzeczywiste PKCE/bootstrap/me/motivation/B→A/baseline/late response pozostają NOT_RUN. Po udostępnieniu wejścia ten odbiór ma pierwszeństwo. Nie wykonano Gemini, uploadu corpus, zgód za człowieka lub zmiany usług/trust/issuer. Sama propozycja corpus, READY transportu lub test fixture nie zamyka pełnego E7/E9/KO32.
