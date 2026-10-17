# Automatyczne utrzymanie lokalnej instalacji

`maintenance.py` obsługuje istniejącą instalację O3. Nie tworzy kontenerów usług,
nie uruchamia migracji, nie buduje obrazów i nie aktywuje Nemesis ani AI.
Przed startem sprawdza etykiety projektu i usługi, a recovery również zapisane
identyfikatory kontenerów. Inna instalacja, brak usługi lub paused wymaga operatora.

## Instalacja i harmonogram

Zatwierdź źródła przed instalacją. Wskaż istniejący Python backendu, prywatny stan
i **nowy katalog kopii poza checkoutem**:

```powershell
infra/integration/install_maintenance.ps1 -Python backend/.venv/Scripts/python.exe -State .tools/local-integration -Backups "$env:LOCALAPPDATA/CalorieO3/scheduled-backups"
```

Instalator nadaje prywatne ACL użytkownika/SYSTEM, zapisuje marker właściciela
i projektu, archiwizuje zatwierdzone źródła w prywatnym runtime i rejestruje:

| Zadanie | Kiedy | Wynik |
|---|---|---|
| O3-Calorie-Integration-Startup | Po zalogowaniu | Docker Desktop i gotowość istniejących usług |
| O3-Calorie-Local-Backup | 03:00 i 15:00 oraz 3 min po zalogowaniu | Kopia, weryfikacja, wznowienie usług, odtworzenie na osobnym PG |
| O3-Calorie-Backup-Recovery | Co minutę | Wznowienie usług po przerwanym własnym backupie |

Backup jest pomijany po sukcesie w tym samym oknie kalendarzowym03:00–15:00
lub15:00–03:00. Następny termin jest nowym oknem, także przy zmianie czasu.
Liczymy okno startu, a nie12h od zakończenia kopii: jej czas wykonania nie może
spowodować pominięcia kolejnego terminu. Działa catch-up po pominiętym terminie.
Zadania wymagają zalogowanego użytkownika i włączonego
komputera, działają bez podwyższenia uprawnień i okien konsoli, także na baterii.
Startup nie wylogowuje ani nie restartuje komputera. Można sprawdzić tę samą
akcję przez `Start-ScheduledTask`; pełny test po rzeczywistym ponownym logowaniu
pozostaje osobnym wynikiem. Istniejący wpis autostartu Dockera jest zachowany.

Akcja startup wykonuje najwyżej trzy próby po błędzie dostępności silnika lub
gotowości usług, z odstępem jednej minuty. Ponowienia należą do procesu akcji,
również przy ręcznym uruchomieniu zadania. Nie zależą od interpretacji kodu
wyjścia przez harmonogram Windows. Poprawny start kończy sekwencję. Błąd
własności kontenera, niepoprawna konfiguracja lub ścieżka nie są ponawiane.
Receipt zachowuje liczbę prób; `RETRYING` i `FAIL` nie są sukcesem monitora.
Blokada instalacji pozostaje zajęta przez całą sekwencję, także w przerwie.
Backup i recovery zachowują własne harmonogramy, bez dodatkowych retry.

Instalator nie zmienia istniejącego monitora. Po pierwszym poprawnym backupie
dopisz do jego prywatnego settings.json `local_backup_receipt` wskazujące
`operations/backup-receipt.json` oraz `startup_receipt` wskazujące
`operations/startup-receipt.json`, a następnie przeinstaluj monitor zgodnie
z [instrukcją](MONITORING.md). Rozróżnia on kopię lokalną i offsite.

## Bezpieczeństwo kopii i odzyskiwania

Backup zatrzymuje na krótko gateway i wszystkich zapisujących klientów własnej
instalacji. Przed zatrzymaniem powstaje atomowy dziennik recovery z kompletem
identyfikatorów. Zwykły błąd w dowolnym kroku wznawia usługi w `finally` i sprawdza
ich gotowość. OS zwalnia blokadę po zabiciu procesu; osobne zadanie recovery
odczyta dziennik i wznowi wyłącznie te same kontenery. Nie usuwać dziennika
`resume_pending=true` jako sposobu naprawy. Brak Dockera lub usunięty/zastąpiony
kontener pozostawia błąd do jawnej interwencji operatora.

Kopia zawiera obie bazy, globals/również role SCRAM, konfigurację, TLS/realm
i katalog. To dane prywatne z sekretami; nie publikować katalogu ani manifestu.
Usługi wracają przed próbą restore. Rehearsal używa osobnego tymczasowego PG17
bez sieci i portów hosta; sprawdza tożsamości, epokę, schemat, katalog i fencing.
Nowa epoka i zamknięcie bramek dotyczą wyłącznie kopii. Oryginalna epoka,
sesje, konta i konfiguracja pozostają zachowane przez zwykłe zatrzymanie/start.

Retencja zachowuje14 ostatnich zweryfikowanych kopii automatycznych. Usuwa tylko
bezpośrednie podkatalogi o własnym formacie nazwy, markerze PASS i poprawnych
sumach, po sukcesie nowej kopii i rehearsal. Ręczne, niekompletne, zmienione lub
przekierowane katalogi są zachowane. Przy mniej niż2GiB/10% wolnego miejsca
backup przerywa przed zatrzymaniem usług. Retencja nie jest awaryjnym czyszczeniem
dysku; niepełne kopie wymagają przeglądu operatora.

Prywatny receipt PASS powstaje dopiero po capture/integrity/resume/rehearsal.
FAIL lub receipt starszy niż24h alarmuje przez sensor `local_backup` istniejącego
monitora. `backup` nadal pozostaje `not_configured` do rzeczywistej dostawy offsite.
`startup` sygnalizuje nieudany przebieg akcji startowej. Reguły deduplikacji
i potwierdzania issues pozostają z monitoringu; żaden alert nie zawiera sekretów.
RUNNING zachowuje minimalny dowód poprzedniej poprawnej kopii. Monitor pokazuje
running tylko gdy ta kopia nadal mieści się w24h i operacja nie przekroczyła45min;
nie zalicza nowej kopii ani nie zamyka wcześniej otwartego incydentu.

## Obsługa operatora

Przed jawnym rolloutem, ręcznym restore lub uzgodnionym testem O1 wyłącz czasowo
zadanie backupu i sprawdź, czy nie trwa operacja. Przywróć je po zakończeniu.
Nie uruchamiaj równolegle ręcznego `backup.py capture`: nie korzysta z blokady
automatyzacji i celowo pozostawia usługi zatrzymane. W przypadku przerwania
automatyzacji użyj akcji `recover` z tym samym prywatnym settings.

Wyłączenie automatyzacji: `Disable-ScheduledTask` dla każdego z trzech powyższych
zadań. Zachowaj runtime, dziennik i kopie do zakończenia ewentualnego recovery.
Aktualizacje wymagają ponownej instalacji z nowego zatwierdzonego commita.

Kopie na tym samym komputerze nie zapewniają odporności na jego utratę. Ten
zakres nie zamyka offsite, produkcyjnego RPO/RTO ani wspólnego KO17/32 z telefonem.
