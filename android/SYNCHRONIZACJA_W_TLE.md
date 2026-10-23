# Synchronizacja w tle — etap C

Ten dokument opisuje moduł O2. Rzeczywisty transport i uwierzytelnienie należą
do wykonawcy sesji O1. Test z wstrzykniętym wykonawcą nie potwierdza integracji
sesji, HTTP, logowania ani wdrożenia.

## Trwały przepływ

`SyncCoordinator` współdzieli blokadę ręcznego wywołania i WorkManagera.
Room zapisuje zakres/generację właściciela, pełny kontekst konta, fazę
`pull_before → push → pull_after`, wersje zgłoszeń, liczniki i czas ponowienia.
Koordynator sprawdza lease/kontekst przed i po każdym wywołaniu typowanego
`SyncStepExecutor`. O1 nadal odpowiada za guard przed fizycznym wysłaniem oraz
commit odpowiedzi HTTP. Sama blokada koordynatora nie zastępuje tych guardów.

PULL wymaga identyfikatora kompletnej aktualnej kopii; jej pełna semantyka
jest sprawdzana przed publikacją aktywnego checkpointu. Następnie stosowany
jest idempotentny `ServerDiaryStore`. Po PUSH zawsze następuje PULL.
`Completed` PUSH nie oznacza pustej kolejki: po końcowym odczycie Room ponownie
sprawdza kolejkę i wersję zgłoszeń w tej samej transakcji. Ograniczony wycinek
pracy zapisuje następną fazę. Brak postępu po zakończonym PULL zachowuje
jego checkpoint i zapisuje wznowienie PUSH; nie zapętla kolejnych odczytów.
Nie zmienia fazy niepewnego wysłania ani cancellation.

`Retry-After` jest maksymalną z zapisanej granicy koordynatora i zamrożonych
paczek. Nowe kliknięcie, zmiana generacji ani restart jej nie skracają.
Worker ponownie sprawdza granicę także po przedwczesnym wybudzeniu schedulerem.
Retry-After0, teraz lub data przeszła także dostają trwały rosnący backoff
(10s,20s,…); termin jest maksimum tej granicy i przyszłego terminu serwera.
Login, uzgodnienie, brak konfiguracji i brak miejsca zatrzymują automatyczne
ponowienia do odpowiedniego jawnego zdarzenia. Cancellation propaguje się:
nie jest ACK, zmianą identyfikatora operacji ani usunięciem pending pages.

## Harmonogram

WorkManager 2.10.5 zachowuje zgodność z SDK35 projektu. Aktualizacja AGP,
Kotlina i SDK nie należy do tego etapu. [Dokumentacja WorkManagera](https://developer.android.com/jetpack/androidx/releases/work).

Jednorazowe zadania mają ograniczenie `CONNECTED`. Unikalny łańcuch wynika
z SHA-256 zakresu i generacji; `APPEND_OR_REPLACE` zachowuje sygnał przychodzący
podczas kończenia poprzedniej pracy. Następca czyta bieżący zapis Room,
więc nie powtarza zakończonego cyklu bez nowego zgłoszenia. WorkData zawiera
wyłącznie scope, generation i wire context; nie zawiera tokenów, payloadu,
poświadczeń ani informacji potrzebnych do interaktywnego logowania.

Obserwator łączy krótkie serie zapisów kolejki. Okresowa praca z warunkiem
sieciowym umożliwia powrót po zakończeniu procesu. Zatrzymany login lub
uzgodnienie nie wywołują transportu przy takim wybudzeniu. System Android
może wykonać pracę później niż wyznaczona granica; nie gwarantujemy punktualności.
[Ograniczenia i opóźnienia](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work).

## Archiwa i migracja

Addytywna migracja20→21 dodaje `sync_work_state` oraz append-only
`snapshot_archive_receipts`. Zachowuje wcześniejsze tabele i dane, bez wipe
lub destructive migration. Surowa retencja nadal wynosi8prób/128MiB na konto;
jedna próba ma maksymalnie64MiB/100000rekordów/2000stron. Liczymy rzeczywiste
UTF-8 zapytań i odpowiedzi. Nie zwiększamy tych limitów.

Kompaktowane są najstarsze bezpieczne zakończone/wygasłe próby. Chronione są
aktywna kopia, pending próby, ostatnie zastosowanie, zamrożone/niezamknięte
paczki, nierozstrzygnięte konflikty i projekcje oraz dowody/receipts/grupy
niedokończonych zatwierdzonych planów uzgodnienia. Jeśli wszystko jest
chronione, rezerwacja odmawia bez utraty dotychczasowej kopii i danych.

Przed usunięciem raw pages i indeksu tożsamości transakcja zapisuje niezmienny
manifest: oryginalny kontekst, checkpoint, tokeny, liczniki i SHA-256 każdego
query/response. Wiersz próby, jego liczniki i klucze obce pozostają zachowane.
Spóźnione identyczne zakończenie sprawdza receipt i nie publikuje starej kopii.
Odtworzenie zapisanego historycznego `ServerDiaryApplication` zwraca wynik
przed odczytem skompaktowanych stron; nie cofa późniejszej lokalnej edycji.
Stary receipt archiwum nie zastępuje świeżej kopii wymaganej po ACK recovery.

## Powtarzalna weryfikacja

Na własnym izolowanym emulatorze validation, z potwierdzoną tożsamością:

```powershell
.\gradlew.bat testDebugUnitTest testValidationUnitTest lintValidation
.\gradlew.bat connectedValidationAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=pl.roseru.kalorie.SnapshotArchiveStorageTest,pl.roseru.kalorie.SyncCoordinatorStorageTest,pl.roseru.kalorie.SyncWorkStorageTest,pl.roseru.kalorie.ImportOriginsMigrationTest,pl.roseru.kalorie.ServerSnapshotStorageTest,pl.roseru.kalorie.ServerDiaryStorageTest'
```

Testy używają syntetycznych danych i prawdziwych transakcji SQLite. Osobno
wymagane są końcowe podłączenie rzeczywistego executora O1, nawigacja/DI B,
testy integracyjne, review i CI dokładnego head/base. Lokalne wyniki oraz
odbiór publikujemy w jedynym dzienniku `docs/KOMUNIKACJA_AGENTOW.md`.
