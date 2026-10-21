# Android 0.8.13 — odczyt dostępności analizy zdjęć

Etap O1 na `codex/android-zdjecia-dostepnosc`, oparty na konkretnym rodzicu
`9ef896becf7370c4f1f76257da9a2ffb9ae4b44b` z PR73. PR73 zależy od PR64 i PR61;
kolejność scalenia pozostaje 61 → 64 → 73 → ten etap. Nie scalaj do oczekującej
gałęzi rodzica. Dotychczasowy realny receipt oraz przygotowany driver late-read
pozostają dowodami swoich wersji, nie odbiorem nowej funkcji.

Na ekranie zdjęć można jawnie odczytać `GET /api/v1/ai/capabilities`, po loginie
i bootstrapie własnego konta. UI pokazuje rzeczywistego dostawcę/model, dostępność
i limity backendu. Mock jest opisany jako scenariusz testowy. Gość nadal zapisuje
zdjęcia lokalnie; dostępny jest aparat, galeria i przejście do ręcznego wpisu.

Gateway korzysta ze wspólnego HTTPS transportu: brak przekierowań, cache i
aplikacyjnego automatycznego ponawiania. Wymagane no-store, ograniczony JSON
i deadline. Parser odrzuca duplikaty, błędny UTF-8, nieznane pola, niewłaściwe
typy/provider/notice i nadmierne limity. Nie wyświetlamy surowych komunikatów
serwera. Jedno odnowienie po 401 i trwały Retry-After po 429/503 korzystają
z istniejącego zakresu sesji.

Wynik jest pamięciowy i ograniczony do przechwyconego konta, lease/generacji,
rewizji kontekstu, account generation i sync epoch. Zmiana konta, logout lub
recovery unieważniają podgląd. Odczyt nie zmienia profilu, celu, zdjęcia ani
outbox; nie przyznaje zgody na wysyłkę. Room pozostaje w wersji 9, bez migracji.

Ten etap nie implementuje jeszcze multipart/create/poll/cancel/confirm ani
zapisu szablonów do kanonicznego sync. Dostępność nie rezerwuje limitu lub miejsca.
Nie jest to pomiar jakości Gemini ani E7-R. Brak usług sieciowych nie blokuje
ręcznego dziennika i zdjęć offline.

## Dane Gemini dla O3

Właściciel podał numer projektu `181003336626` i potwierdził Free Tier w panelu
billing. Zrzut panelu limitów dla Gemini 3.5 Flash Lite pokazuje RPM15,
TPM250000, RPD500; wartości zapisano z tego źródła, bez używania limitów demo.
Nagłówków ani numeru projektu nie widać na wycinku; skojarzenie z projektem
wynika z rozmowy właściciela. Nie jest to automatyczny odczyt Cloud IAM/quotas.
Osobne potwierdzenie billing-disabled/development-only, environment ID jednego
wspólnego poolu E7/E9 oraz prywatny kanał przekazania pozostają do uzgodnienia O3.
Klucz testowy przechowywany poza Git/APK/OneDrive wymaga wymiany po ujawnieniu
w rozmowie. O1-043 zawiera rzeczywisty metadata GET200, bez generateContent.
Pełny manifest live oraz rollout Gemini nie są jeszcze odebrane.

## Walidacja

Końcowy build debug/validation/test APK PASS. **170 JVM debug / 179 JVM validation
PASS**, bez failures/errors/skips. Lint: **0 błędów**. Końcowe **81/81 native PASS**
na własnym O1Tests35/API35: 76 testów sesji (w tym 2 nowe), 2 nowego panelu,
2 dotychczasowego ekranu zdjęć i 1 adaptacyjny. Nie jest to pełny zestaw 192
przypadków ani rzeczywisty GET do API O3; gateway fixtures są deterministyczne.

Historia zachowana: pierwszy build test APK miał kolizje po dołączeniu zbyt
szerokiego katalogu unit resources; wydzielono wyłącznie photo. Dwa pierwsze
przebiegi urządzenia: 79 PASS + 2 RED. Poprawiono fixture kind/storageScope,
potem oczekiwanie fragmentu zastąpiono ścisłymi pełnymi tekstami. Osobne 2/2 UI
następnie PASS. Startup ANR bez rozpoczęcia testów zdiagnozowano przez exit-info
i stos main: Room budowane inline przez Main.immediate wewnątrz Application.onCreate.
Start inicjalizacji jest teraz zakolejkowany przez Dispatchers.Main, aby proces
najpierw zakończył attach. Bez zmian limitów ANR, czasu testów i danych emulatora.
Naprawa dotyczy obu wariantów, nie jest przełącznikiem tylko dla testów.

Końcowy przegląd diffu wykrył dodatkowo omyłkowe odczytanie UTF-8 jako CP1250
przez prywatny helper formatowania. Przywrócono komunikaty sesji i jawne UTF-8,
bez zmian warunków/identyfikatorów/operacji danych. Przebudowano oba APK,
powtórzono 170/179 JVM, lint oraz cały dobrany zestaw 81 native na poprawionym
artefakcie, również po naprawie uruchomienia. Końcowy PASS dotyczy tego źródła.

Porównano 14 plików źródła/testów build i publikacji: identyczne bajty.
Testowy fixture nie jest w APK aplikacji; live API driver nie jest w domyślnym
APK testów. Zwykły APK nie zawiera validation receipt/loggera. Przed publikacją
sprawdzono brak wartości klucza Gemini w źródłach tego etapu.

Regularny APK zaktualizowano install-r na CodexCalories. Prywatny baseline
Room9/FK clean: **wszystkie 23 tabele przed/po instalacji identyczne**, bez
clear/uninstall. Końcową aktualizację po poprawkach objęto nowym osobnym
baseline. Ekran zdjęć otwarto przez kontrolki z bieżącego UI; obejrzany zrzut
gościa ma aparat, galerię, manual i nową kartę bez ucięć. Prywatne DB/wiersze/XML
przechowywane poza Git/OneDrive. O1Api35/5558 zachowany i zamknięty; brak nowego
relay, loginu i rzeczywistego GET capabilities.

| Artefakt 0.8.13/code24/Room9 po korekcie UTF-8 | SHA-256 |
|---|---|
| debug | `604ea22ae103e9f8aea2517f59e33f06777d6ac8a6fa03e016facd88057e91f3` |
| validation | `00cd4f4ad87578347abf7b435f4e29c494aa3d279799c268436ebbe2b2f9a869` |
| końcowy test APK | `d65b9731e84552a77e64c3a5b1f32c0918b1f87fbdf8d734b0decb7b60847e35` |

Lokalny zwykły APK: `output-apk/Racje-i-kalorie-0.8.13-debug.apk` (poza Git). Zdalne CI, merge, E7-R i fizyczny telefon wymagają osobnych odbiorów.


## O1-087 — integracja na aktualnym main, 20.10.2026

PR73 scalony jako ec70a5a po pełnym8/8CI39440066617/head1874550:
165JVM debug/180JVM validation oraz190API35 offline, bez błędów i pominięć.
To odrębne warianty z powtarzającymi się testami wspólnymi.
Drzewo merge zgodne z faktycznie przetestowanym21b4b1e.
PR96/head8d96aa7 dołącza ten main zwykłym merge bez konfliktów.
Kod Android/app identyczny ze źródłem96; narzędzia/CI/backend/infra
ze scalonym main, w tym wymagane testy obu wariantów JVM. Room9 bez migracji.
Historyczne wyniki powyżej pozostają dowodami dawnych APK; nowa integracja
otrzyma własny Project CI po skierowaniu istniejącego PR96 na main.
Nie uruchomiono live capabilities/Gemini/nowego okna O3. Bieżący zwykły
profil ma nowszy code33; nie instalujemy na nim starszego code24.
Szczegóły i ograniczenia: O1-087 we wspólnym dzienniku.
