# Android 0.7.3 — tryby aktywności i cel kcal

Agent 1 / O1, 11 października 2026. Gałąź `codex/android-tryby-aktywnosci`; kod 1af9091; etap korzysta z Androida 0.7.2 / scalonego PR #23 (main 446ac0c). Przekazanie E7/O2-018/019 zachowano zwykłym merge bez zmiany testowanego kodu Androida. versionCode 10; Room nadal 6, bez migracji.

„Garnizon” ma nazwę „Etat biurowo-kawowy”. Trzy dekoracyjne ikony wektorowe pokazują żołnierza przy kawie, żołnierza w marszu z plecakiem i komandosa. Kolory mundurów odpowiadają motywowi aplikacji; tekst pozostaje nazwą dostępną dla czytnika ekranu. Identyfikatory GARRISON/LINE/COMMANDO nie zmieniły się.

Reguła `activity_goal_v1` przelicza bieżący cel kcal stosunkiem mnożników: etat ×1,00, Linia ×1,25, Komandos ×1,50. Przykład bez ręcznych zmian: 2800 → 3500 → 4200 → 2800 kcal. Jeśli użytkownik w Linii ręcznie ustawi 3000 kcal, przejście na Komandosa daje 3600 kcal. Zmiana klasy zaokrągla HALF_UP do 1 kcal; bez zmiany klasy wartość pozostaje dokładnie taka sama. Zakres zapisów pozostaje 0 < kcal ≤ 20 000; nieprawidłowy wynik blokuje zapis z komunikatem. To względna reguła celu, oddzielna od backendowego kalkulatora zapotrzebowania `mifflin_pal_v1`.

Profil pokazuje cel przed zatwierdzeniem. Samo wybranie klasy nie zapisuje niczego. „Zapisz profil” zapisuje profil i nową wersję celu od dzisiaj w jednej transakcji, razem z lokalnym outbox. Zachowuje poprzednie wersje, cele wcześniejszych dni i B/T/W. Edycja samego pseudonimu/wzrostu lub celu redukcja/utrzymanie/nadwyżka nie przelicza kcal. Ręczne Ustawienia nadal działają. Otwarcie aplikacji nie zmienia celu ani zapisanej klasy. Starszy niskopoziomowy zapis profilu pozostaje dostępny dla importu/fixture bez niejawnego przeliczania celu.

## Weryfikacja

- JVM: 67 testów, zero failures/errors; nowe przykłady przeliczników, ręcznej bazy, zaokrągleń i odrzuconych wartości.
- Urządzenie: pełne 56/56, zero failures/errors/skips; API 35, 1080×2400, density 420, font 1.0, airplane_mode_on=1.
- Lint: 0 błędów / 26 ostrzeżeń / 1 informacja.
- E0 i diff-check sprawdzane przed publikacją. Pierwsza próba urządzenia nie wykonała testów, ponieważ emulator był zamknięty (`No connected devices`); Dwa następne pełne przebiegi dały 55/56: najpierw nowa asercja porównywała fragment liczby z całym tekstem, potem szybkie drugie kliknięcie nakładało się na komunikat zapisu. Diagnostyka potwierdziła LINE/3500 zapisane i brak drugiego wywołania. Końcowy test porównuje dokładny podgląd i oczekuje pojawienia/zniknięcia komunikatu przed kolejnym rzeczywistym tapem. Nie zmienia to kodu przeliczników ani nie ponawia zapisu; pełny końcowy przebieg dał 56/56.
- Nowy test Room sprawdza cele historyczne, B/T/W, ręczną zmianę, ponowną inicjalizację i wersjonowanie. Drugi wymusza błąd w kolejce celu i sprawdza rollback profilu, celu i obu operacji. Test UI wybiera trzy klasy, sprawdza podgląd przed zapisem, rzeczywisty cel po zapisie oraz odtworzenie wybranego trybu.

APK poza Git: `Racje-i-kalorie-0.7.3-debug.apk`, SHA-256 `86029e183c5dbf27e379be78acd38aefc7ac07e6cb1e90bf80135227bbca4547`. Rzeczywista aktualizacja 0.7.2 → 0.7.3 zachowała wszystkie kolumny 18 tabel, w tym 2 istniejące posiłki, profile, cele i outbox; foreign_key_check pusty. Zdalne CI i merge są osobnymi krokami; wynik lokalny ich nie potwierdza.

## Test manualny

1. Profil → uzupełnij pseudonim i wzrost, jeśli jeszcze ich nie ma. Sprawdź trzy ikonki.
2. Wybierz Linię lub Komandosa i przeczytaj „Cel po zapisaniu”. Wróć bez zapisania — cel dziennika ma pozostać bez zmian.
3. Wybierz tryb ponownie i zapisz profil. Dziennik oraz Ustawienia mają pokazać nowy cel. Wcześniejszy dzień zachowuje wcześniejszą wartość.
4. Ustaw ręczne kcal w Ustawieniach. Edycja samego pseudonimu nie zmienia celu; zmiana klasy przelicza nową ręczną wartość.

Sesja OIDC, HTTP i synchronizacja pozostają następnym oddzielnym etapem; obecny APK nadal działa lokalnie jako gość.
