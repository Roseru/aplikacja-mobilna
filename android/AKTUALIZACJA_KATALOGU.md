# Pobieranie bazy offline — implementacja O1 w toku

Gałąź `codex/android-katalog-do-pobrania`, baza main837343c.
To rozpoczęty kolejny etap, **bez kompilacji, testów, APK, publikacji lub PR**.
Nie zmienia zamrożonej dostawy0.8.29/Room20 dla O2/O3.

## Zachowanie

Moduł korzysta z publicznych `GET /api/v1/offline-package/manifest` oraz
`GET /api/v1/offline-package/base-pl.<release>.json.gz`. Nie używa sesji,
tokenu ani logowania. Official ma stałe ID
`c12631e2-1a02-547c-a7f9-ebf87bb42e55`;404 oznacza brak opublikowanej bazy,
a nie polecenie zastąpienia jej demonstracyjnymi danymi.

Sprawdzenie wersji i pobranie wymagają osobnych działań użytkownika.
Wybrany manifest przypina release, ścieżkę, rozmiary i SHA256. Transport
nie przekierowuje, nie przyjmuje dodatkowego Content-Encoding i ogranicza
czas/rozmiar odpowiedzi. Blokada sieci albo anulowanie rozłącza także socket.
429/503 ma trwały Retry-After bez automatycznej pętli ponowień.

Sprawdzenie manifestu i pakietu korzysta z tego samego CatalogPackageReader
co osadzone demo: tożsamość, wersje czytnika/schematu, gzip/CRC, hash,
rozmiary, graf referencji i wymagane dane official. Stage i aktywacja
CatalogStore są objęte jedną zewnętrzną transakcją Room. Błąd nie podmienia
aktywnej generacji, a starszy równoległy download nie cofa nowszego release.
Tymczasowy plik leży w prywatnym cache aplikacji i jest usuwany w finally.
Nie ma nowej migracji ani zapisu do dziennika/kolejki użytkowników.

Panel pokazuje zapisane wydania, DEMO/official, datę, liczby produktów,
racji/składników i źródeł, dostępną aktualizację, postęp i jawne anulowanie.
Źródła konkretnego zapisanego release można przeglądać **bez sieci**:
paginacja po5, data weryfikacji, producent/rynek/wariant, jednostka odniesienia,
uwagi i braki danych. Długie listy są renderowane lazily. URL jest tekstem
do skopiowania; podgląd nie otwiera strony internetowej.

## Granica integracji z O2-C

Nie powstaje drugi przełącznik trybu poligonowego. CatalogNetworkGate
otrzymuje wspólną politykę sieci; domyślnie jest zamknięty.
SharedCatalogNetworkGate potrafi odwzorować `Flow<Boolean>` z tej polityki.
Jego błąd zamyka sieć, a odczyt zapisanej bazy i jej źródeł nadal działa.

SettingsScreen przyjmuje opcjonalny CatalogUpdateViewModel. **Rzeczywisty
root/DI/nawigacja nie zostały jeszcze podłączone**: MainActivity,
CalorieApplication/App oraz Worker/Preferences pozostają u O2 w finalnym C.
O1 poprosił o przypięty port polityki i podał granice plików w istniejącym
[wątku146](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6374409593).
Kolejność B→C nie zależy od tego nowego modułu.

Po odbiorze właściwego main integracja ma tworzyć jeden model katalogu dla
urządzenia, poza kluczem właściciela dziennika. Przykładowe zależności:

```kotlin
val gate = SharedCatalogNetworkGate(applicationScope, sharedNetworkPermission)
val repository = CatalogUpdateFactory.repository(context, database, gate)
// W prawdziwym ViewModelStore i fabryce lifecycle, nie przy każdej rekompozycji:
val model = CatalogUpdateViewModel(repository)
SettingsScreen(diaryModel, catalogModel = model)
```

`sharedNetworkPermission` musi wynikać z trwałej polityki C, nie ze stałego
`true`, samej obecności Wi-Fi lub testowego zamiennika. To przykład zależności,
nie gotowy blok do wklejenia do composable.

## Odbiór po ukończeniu etapu

Jeden spójny build i celowane przypadki rzeczywistego Room/transportu/UI:
publiczne żądania bez sesji, niezgodny hash/rozmiar/identity,404 z zachowaniem
demo, Retry-After po restarcie, cancel/blokada w trakcie, atomowa aktywacja,
równoległy nowszy release, zachowanie dziennika/outbox i podgląd źródeł offline.
Bez seryjnego uruchamiania małych zestawów podczas pisania. Duży końcowy PR
dopiero po podłączeniu i odbiorze; te scenariusze nie mają jeszcze wyniku PASS.
