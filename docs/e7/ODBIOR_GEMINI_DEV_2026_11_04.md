# Gemini dev — odbiór backendu 04.11.2026, Agent 1

Rzeczywisty test przypiętego `gemini-3.5-flash-lite` przeszedł: zdjęcie →
kolejka → worker → propozycja → jawna korekta → confirm → zwykły PUSH/PULL.
To odbiór developerskiej ścieżki backendu, oddzielny od APK i dokładności E7-R.
Baza źródeł: main `63777a5`; gałąź `codex/android-gemini-odbior`.

## Zgoda i środowisko

Właściciel jawnie zezwolił na metadata GET i analizę niewrażliwego zdjęcia,
wyłącznie w Free Tier, oraz potwierdził projekt, brak billing i limity
15 RPM / 250000 TPM / 500 RPD. To datowane potwierdzenie właściciela;
HTTP200 modelu sam nie dowodzi stanu billing lub limitów. Klucz istnieje
wyłącznie w prywatnej konfiguracji backendu, poza Git/OneDrive/APK/CI.

Użyto osobnej instalacji developerskiej z prawdziwym Keycloak PKCE,
PostgreSQL 17, minimalną rolą AI, prywatnym mount zdjęć, normalnym API,
workerem i trwałą pulą. Nie zastąpiono odebranej instalacji MOCK ani danych
Androida. W obrębie próby zachowano ten sam scope, bazę i wszystkie
rezerwacje; nie resetowano ledger ani epoki. Tego izolowanego środowiska
nie należy uruchamiać równolegle z inną pulą tego samego projektu ani
traktować jako automatycznego przeniesienia historycznego scope E7/E9 O3.
Koordynacja takiego przełączenia i zachowanie historii pozostają wymagane.

## Znaleziony błąd i poprawka

`countTokens` działał, lecz `generateContent` dla schematu v1 zwracał
HTTP400 `INVALID_ARGUMENT`, bez wskazania pola. Kontrolowana prywatna próba
usunęła wyłącznie trzy `maxItems` ze schematu dostawcy; reszta żądania i zdjęcie
pozostały takie same. Wynik tej próby był poprawny. Nie ustalono, który
pojedynczy limit lub ich kombinacja wywołuje odmowę Google.

Normalny profil Gemini używa teraz `food-photo-schema-v2`, bez tych ograniczeń
w schemacie dekodowania. Backend nadal odrzuca ponad 30 składników,
ponad 5 notatek składnika i ponad 10 notatek posiłku. Zachowano walidację
JSON, jednostek, wartości, tożsamości, rozmiaru i tokenów. Count i generate
otrzymują ten sam pełny request. MOCK zachowuje schema-v1; dawnych analiz
i ich profili nie przepisano. Stary aktywny job nie przełącza się po cichu
na nowy profil. E9, publiczne DTO, migracje i Android nie zmieniły się.

Diagnostyka workera przechowuje wyłącznie HTTP status i dozwolony enum
Google RPC status. Nie loguje message/details dostawcy, kluczy, obrazu lub
danych użytkownika. Nie zmienia klasyfikacji quota, retry, unknown ani fencing.
Jednorazowy prywatny observer był użyty tylko do diagnozy; końcowy odbiór
wykonano zwykłym obrazem, identycznym dla API i workera.

## Rzeczywisty wynik

Wejście: publiczne zdjęcie jednego jabłka, USDA/public domain,
[źródło i licencja](https://commons.wikimedia.org/wiki/File:USDA_Eat_Healthy_Food_Group_Gallery_serving_size_small_apple_(cropped).jpg).
Oryginał 78617 B, SHA256
`3f44aff8e3dde9092f2541461b1a177d4bf7602bc94b8a927cf3a76291bce678`.
Oczekiwanie „jedno jabłko” zapisano przed analizą. Do Google trafił przygotowany
JPEG, zgodnie z istniejącym pipeline, bez EXIF/nazwy/pełnego dziennika.

- Normalny profil v2: `queued → running → succeeded`, modelVersion zgodny.
- Rozpoznanie: `Apple`, szacowane 180 g i 52 kcal/100 g, B 0.3 / T 0.2 / W 14 na 100 g.
- Jawnie wybrana porcja **testowa 100 g**, zachowane szacowane wartości na 100 g.
  Ani 180 g, ani 100 g nie są dowodem zważonej masy tego zdjęcia.
- Confirm i powtórzenie tej samej decyzji: identyczny wynik/provenance v2.
  Sam confirm nie utworzył Meal w dzienniku.
- Zwykły PUSH: jeden zaakceptowany Meal revision 1. Replay tej samej operacji:
  `already_applied`, nadal revision 1. PULL zwrócił dokładnie poprawiony payload.
- Końcowy PG witness: pięć analiz, trzy failed i dwie succeeded; pięć
  preflightów OK, trzy generate denied, dwa generate OK. Jeden sukces był
  prywatną próbą diagnostyczną, drugi właściwym odbiorem v2. Jedna decyzja,
  jeden Meal, zero niedomkniętych IO i zero zajętych permits. Błędne próby zachowano.

Receipt końcowego witness SHA256:
`8881193543ad63d8cd4b8761442535a8f9e36c30524f184135a5f1ef904cfd09`.
Prywatne receipt/sekrety/identyfikatory kont i operacji pozostają poza repozytorium.

## Weryfikacja i dalszy zakres

171 celowanych testów transportu, parsera i multipart PASS w jednym końcowym
uruchomieniu; lint/format oraz diff-check PASS. Wcześniejsze dwa uruchomienia
w ograniczonym środowisku Windows przerwano po zawieszeniu; nie są zaliczone.
Prawidłowy końcowy run wykorzystywał lokalne atrapy HTTP, bez Google.
Zdalny PR/main CI mają własne wyniki; test lokalny nie jest ich zastępstwem.

Nie wykonano nowego odbioru APK na Gemini ani 30-zdjęciowego E7-R. To zdjęcie
bez zmierzonej porcji nie ocenia dokładności kalorii. Domyślny lokalny MOCK,
odłożony ARPOL, hosting i opcjonalne powtarzanie posiłków pozostają osobnymi
zakresami. Brak deklaracji wydania AI lub ukończenia całej wersji 1.0.
