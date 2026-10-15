# Zlecenie analizy zdjęcia — moduł Androida

Kod na `codex/android-analiza-zdjec` jest następną częścią klienta E7, zależną
od PR96 i zwykłego merge rodzica PR73. Normatywny kontrakt pochodzi z
[integracji O2](../docs/e7/INTEGRACJA_O1.md) i
[DTO backendu](../backend/src/calorie_app/modules/ai/schemas.py).
Pełna funkcja pozostaje w implementacji. Sam ten moduł nie dodaje przycisku
wysyłki, nie udziela zgody i nie uruchamia sieci przy starcie aplikacji.

## Implementacja

`PhotoHttpRequest.Create.prepare` wymaga jawnej zgody, dostępnego capabilities,
znanego notice/provider oraz kanonicznego UUID klucza i epoki. Przyjmuje bajty
już przygotowanego lokalnego obrazu, bez ponownego kodowania. Generuje dokładnie
dwie części: metadata JSON z consent oraz image JPEG/PNG/WebP. Filename jest
stały; nie zawiera nazwy pliku użytkownika, ścieżki ani właściciela.
Sprawdza rozmiar obrazu/całego body, zgodność sygnatury z MIME oraz brak
wstrzykniętej granicy multipart. Nie zastępuje pełnej walidacji dekodera
lokalnego magazynu ani backendu, w tym rozmiarów, klatek i metadanych EXIF.

Przygotowany request przechowuje własne niezmienne bajty. Mutacja tablicy
wejściowej lub zwróconego body nie zmienia kolejnego wysłania. Jawne ponowienie
tego samego requestu zachowuje klucz, zgodę, epokę i dokładny obraz; moduł nie
przeprowadza automatycznych ponowień po lost ACK. Redagowane toString nie ujawnia
obrazu, metadanych, ID ani danych sesji.

`HttpsPhotoAnalysisGateway` korzysta ze wspólnego transportu HTTPS oraz
przechwyconego ApiSession i callbacku kontroli właściciela przed wysyłką.
Adresy są budowane wyłącznie z walidowanej bazy i typed create/read/cancel;
analysis ID nie pozwala na zmianę ścieżki. Brak przekierowań i cache. Mutacje
otrzymują Idempotency-Key/X-Sync-Epoch, GET ich nie dostaje. Multipart używa
fixed length i części JSON z poprawnym Content-Type. Zapis większego body jest
dzielony na4KiB z kontrolą cancellation i istniejącego deadline między blokami.
Nie obiecujemy przerwania blokującego systemowego write w dowolnej chwili.
Wspólny transport zachowuje ograniczenia odpowiedzi, JSON/no-store i TLS.
Proxy429/503 zachowuje dotychczasową obsługę Retry-After bez odczytu HTML.

Ścisłe dekodery ACK create i cancel odrzucają nieznane/brakujące pola,
duplikaty, błędny UTF-8, błędne UUID/UTC/revision i niezgodnego providera.
Create jest potwierdzeniem przyjęcia; replay queued nie jest bieżącym stanem
zadania. Potrzebny będzie osobny GET z pełnym dekoderem propozycji.
Cancel sprawdza własne analysis ID, rewizję oraz failed/cancelled/analysis_cancelled.

## Następne części pełnej funkcji

1. Trwały owner-scoped zapis obrazu, consent/key/body/epoki przed POST,
   wznowienie po restart/lost ACK oraz fencing konta/generacji/rewizji/recovery.
2. Ekran notice dla wybranego zdjęcia, create i ograniczony polling/deadline,
   pełny ścisły decoder stanu/propozycji, cancel i ręczny fallback.
3. Korekta1–30 składników, Decimal/null/B/T/W/g/ml, exact refs i provenance.
4. Confirm ze stabilnymi ID, atomowy Room+outbox oraz jedyny zapis serwera
   przez kanoniczny E4 push; brak drugiego posiłku po replay.
5. Odbiór rzeczywistego APK/API, E7-R i pozostałe bramki wymagane przez O2/O3.

Zgody rankingu nie zastępują zgody na zdjęcie. Dostępność nie rezerwuje limitu.
Nie dodano sekretu, wywołania Google, migracji Room, zapisu dziennika,
automatycznej publikacji produktu lub workerów. Mock nie jest pomiarem Gemini.
Priorytet sieciowego odbioru PR61/64/73 pozostaje oddzielny od tego modułu.

## Wynik lokalnego sprawdzenia

Źródło `cb20e0dad2eaa12a6f2c3ddcf8bb4ba0e41e5df4`:186JVM debug/201JVM validation PASS,
lint0error, build obu wariantów/testAPK PASS. Native83/83 API35 bez pominięć PASS
na O1Tests35 (78sesji,2panelu,2zdjęć,1adaptacyjny). Szesnaście nowych testów JVM
obejmuje wire/ACK/HTTP; natywne sprawdzają integrację dotychczasowego klienta.
Pierwszy build zatrzymał błąd escapowania regexu; pełny wynik pochodzi z poprawki.
APK validation SHA256 `bfd53af49b1a57980ac2ca757bf8b3714f73dfac65c2c04e2b1a70558b34a0c5`.
Zwykły debug bez znaczników bramki, domyślny testAPK bez drivera live.
Rzeczywiste API/Gemini i pełny klient E7 nadal nieodebrane; nie aktualizowano
regularnej instalacji użytkownika. Zdalne CI/scalenie to oddzielne warunki.
