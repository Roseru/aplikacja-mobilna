# Android — przygotowanie paczki i walidacja odpowiedzi E4

Etap kontynuowany w [PR122](https://github.com/Roseru/aplikacja-mobilna/pull/122),
`codex/android-potwierdzenie-posilku`. Wymagania:
[integracja E4](../docs/e4/INTEGRACJA_O1.md),
[decyzje v1](../docs/e4/DECYZJE_V1.md),
[normatywny schema](../contracts/schemas/sync.schema.json).

## Dostarczony kod protokołu

`PushProtocol` przygotowuje kanoniczną kopertę zwykłego push z istniejących
operacji wire i otrzymanego checkpointu. Nie tworzy tokenu ani nie przekształca
historycznych wpisów legacy. Wybiera ciągły prefiks kolejki: najwyżej 100 operacji,
1 048 576 bajtów UTF-8 całego żądania oraz 262 144 bajty pojedynczego payloadu.
Druga zmiana tej samej encji kończy paczkę; nie pomijamy jej, aby wysłać późniejsze
zależności. Regrouping koperty nie zmienia operacji. Dla Meal sprawdzane są także
reguły daty/strefy, jednostek, odżywiania i tożsamości składników.

`PushBatch` przechowuje niezmienny JSON i SHA-256 dokładnych bajtów wysyłki.
Zwraca kopie; zmiana wejściowego JSONObject lub otrzymanego ByteArray nie zmienia
żądania. Restore wymaga identycznego kanonicznego zapisu. Baza ma go utrwalić przed
HTTP; ta biblioteka sama nie zapisuje partii ani nie zmienia outbox.

`PushReceipt` powstaje wyłącznie dla kompletnego HTTP200. Walidacja obejmuje
schema, epokę, liczbę i kolejność wszystkich wyników oraz operation_id/entity_id.
Sukces ma pierwotną rewizję base+1, również po replay już wykonanego żądania.
Niepełny ACK lub zły późniejszy wynik nie daje częściowego potwierdzenia.
accepted→already_applied może zachować tę samą decyzję; zmieniona rewizja nie jest
replay. Wynik wiąże hash konkretnej koperty. Odpowiedź nie wydaje checkpointu.

Konflikt/odrzucenie pozostaje pełnym wynikiem wymagającym obsługi; protokół nie
nadpisuje lokalnego posiłku. RecoverySource i mapowania są jawnie niedopuszczone
w tej ścieżce zwykłego push. Mają osobny proces świadomego uzgodnienia.
Diagnostyka nie wypisuje body, checkpointu, prywatnych błędów lub ich przyczyn.

## Poprawka Unicode

Test paczki z maksymalnym checkpointem Unicode wykrył przepełnienie stosu w
rekurencyjnym wzorcu UnicodeText silnika regex JVM. `SyncWireSchema` rozpoznaje
wyłącznie dokładny, przypięty wzorzec z common.schema i sprawdza ten sam język
iteracyjnie: bez NUL i samotnych surrogate, z poprawnymi parami UTF-16/emoji.
Pozostałe wzorce, limity długości liczone w code points i normatywne schematy
pozostają zachowane. Nie zmieniono kontraktu serwera.

## Dowody

Kod `fd1ceaf3206a97a2efc9ca538993a6a217b21f95`. Pełne zadania Gradle testDebugUnitTest,
testValidationUnitTest i lintDebug **PASS**: **308/323 JVM**, bez błędów lub
pominięć, lint0error. Przebieg 5m28s; wszystkie 244 wejścia źródłowe porównano
przed/po. Nowe 16 testów push i 1 regresja walidatora. Lekki zestaw push/schema/
snapshot/MealWire: 41 PASS. Pierwsza próba Gradle nie połączyła się z lokalnym
daemonem w sandboxie; zakończyła się exit1 przed zadaniami. Ponowny przebieg
na tych samych źródłach, z dostępem do loopback, zakończył się exit0.

Nie wykonywano assemble nowego APK ani nowych testów urządzenia dla tego
commita. Pełne 260 native i APK 0.8.19 opisane w raporcie materializacji należą
do wcześniejszego kodu 97fff24. Nie przepisujemy ich na bibliotekę push.

Niezależny fixture PushResponse przeszedł również Python jsonschema przeciw
normatywnemu kontraktowi; mutacja revision=0 została odrzucona. To weryfikacja
pliku, nie wykonane wywołanie API.

## Kolejny krok w tym samym rezultacie

Potrzebny jest trwały rejestr paczek/odpowiedzi w Room, przechwycenie pełnego
kontekstu i lease oraz transakcyjny CAS przy wysyłce i odbiorze. ACK ma zachować
nowszą lokalną porcję, nadać serverRevision i uaktywnić waiting_revision z nowym
base_revision. Konflikt zachowuje obie wersje do świadomego uzgodnienia. Replay
po ponownym otwarciu bazy nie może ponownie uruchamiać późniejszej intencji.

Następnie transport, kontrola sesji/retry/backoff, świadome confirm w UI,
konwersja legacy, recovery i retencja. Biblioteka nie oznacza jeszcze działającej
synchronizacji ani kompletnego E4/E7/KO32. [Atomowy zapis potwierdzenia i APK](POTWIERDZENIE_POSILKU.md)
pozostaje odebrany dla kodu 97fff24 / 0.8.19; zainstalowanego APK użytkownika
nie podmieniono przy pracy nad tą biblioteką.
