# Monitoring lokalnej integracji O3

`monitor.py` wykonuje wyłącznie odczyty. Nie uruchamia `verify`, nie tworzy kont,
nie zmienia zgód ani danych. HTTPS używa lokalnego TCP, własnego CA i oryginalnej
nazwy TLS/issuer. Wymagane są readiness200 i discovery200 z dokładnym issuer.
Weryfikacja certyfikatu pozostaje włączona. Monitor sprawdza zdrowie kontenerów
własnego projektu Compose, dysk stanu (minimum2GiB i10% wolnego miejsca) i TLS (14dni).

Jawne `finalizer_disabled=true` uwzględnia zamkniętą capability. Disabled/ready=false
jest poprawny tylko z last_attempt nie starszym niż180s. Failed, zatrzymany proces
lub stary pomiar nadal są awarią. AI ma `not_deployed` do rzeczywistego wdrożenia
z konfiguracji A1. Kopie offsite mają `not_configured` do osobnego odbioru zadania6.
Opcjonalne `backup_receipt` wskazuje prywatny receipt dostawy: `verified_at` ISO8601
i `offsite_verified=true`. Wiek ponad24h, brak lub błędny receipt alarmuje. Receipt
jest wejściem z procesu zweryfikowanej dostawy; monitor nie sprawdza ponownie magazynu.
Lokalny plik backupu nie jest dowodem offsite.

[Automatyczne utrzymanie](UTRZYMANIE_LOKALNE.md) dostarcza oddzielne sensory
`local_backup` i `startup`. Opcjonalne `local_backup_receipt` wskazuje prywatny
wynik kopii lokalnej: PASS, wiek do24h, integrity/restore_rehearsal/services_resumed
muszą być prawdziwe. Brak pliku, niekompletny lub nieudany przebieg alarmuje.
`startup_receipt` sprawdza wynik ostatniej akcji startowej. Te sensory nie zmieniają
statusu offsite/AI i nie uruchamiają samodzielnie napraw.

W trakcie kopii `local_backup=running` jest dopuszczalne wyłącznie przy świeżym,
poprawnym poprzednim receipt i wieku operacji do45min. Nie jest to PASS nowej
kopii i nie zamyka istniejącego alarmu. Stara poprzednia kopia, brak jej dowodu
lub przekroczony limit operacji nadal dają failed. Dopiero rzeczywisty nowy PASS
przywraca stan ok i zamyka incydent.

## Uruchomienie

Prywatne settings.json w katalogu monitoring pod chronionym katalogiem integracji
zawiera `checkout` lokalnego repozytorium i jawne `finalizer_disabled`. Instalator
dodaje bezwzględne ścieżki `git` i `docker`; nie zapisuje tokenu.

```json
{"checkout":"/private/repository","finalizer_disabled":true}
```

```powershell
python infra/integration/monitor.py once --state <private-state> --settings <private-settings>
infra/integration/install_monitor.ps1 -Python <python.exe> -State <private-state> -Settings <private-settings>
```

Windows wymaga `pythonw.exe` obok wskazanego Pythona i używa go w harmonogramie,
aby pomiar co minutę nie otwierał konsoli Minicondy. Procesy Git i Docker również
uruchamiają się bez okien konsoli. Brak `pythonw.exe` przerywa instalację przed
zmianą zadania. Windows kopiuje runtime do prywatnego stanu. Zadanie `O3-Calorie-Integration-Monitor`
działa dla bieżącego zalogowanego użytkownika bez podwyższenia uprawnień, co60s,
IgnoreNew, limit3min, również na baterii. Instalator nie nadpisuje zadania innego
właściciela. `LastTaskResult=0` i świeży heartbeat delivery=ok potwierdzają przebieg;
sam stan Ready nie wystarcza. Aktualizacja wymaga ponownej instalacji i sprawdzenia.
Wyłączenie: `Disable-ScheduledTask -TaskName O3-Calorie-Integration-Monitor`.

## Alerty

Właściciel wybrał issues repozytorium Roseru/aplikacja-mobilna. Dwie kolejne awarie
sensora tworzą lub ponownie otwierają jedno issue; pierwszy poprawny pomiar zamyka je.
Powtarzany failure nie mnoży issues. Przed POST monitor szuka istniejącego markera,
także po niepewnym wyniku sieci lub utracie lokalnego receipt. Po zapisie GET musi
potwierdzić marker i stan; niepotwierdzona dostawa jest ponawiana. Brak wdrożenia
AI/kopii nie jest zielonym wynikiem ani incydentem działającej usługi.

Git Credential Manager dostarcza istniejące uprawnienia tylko do pamięci, bez
interaktywnego logowania. Authorization trafia wyłącznie do api.github.com.
Publiczne issue ma allowlisted sensor, czas UTC i stan. Nie zawiera adresów,
tokenów, body odpowiedzi, kont, pełnych nagłówków ani logów kontenerów.
Measurements/incidents/heartbeat pozostają prywatne. Utrata dostępu do GitHuba daje
heartbeat delivery=failed. Nie potwierdzamy e-maila ani odczytania przez człowieka.

## Faktyczny odbiór 14.10.2026

API/Keycloak/PG/retention/motivation/lifecycle dostępne; finalizer celowo disabled
z aktualną próbą. Dysk18,86% wolnego miejsca, TLS około86,74dni do końca.
Kontrolowana próba wstrzymała jedynie własny kontener API: dwa rzeczywiste readiness
zawiodły, discovery działało. Zapis i odczyt [alertu83](https://github.com/Roseru/aplikacja-mobilna/issues/83)
potwierdzono. API przywrócono w finally; dodatkowy proces zabezpieczał unpause po40s.
Poprawny readiness i zamknięcie issue potwierdzono odrębnym GET z GitHuba.
DB/Keycloak i konta/epoka pozostały zachowane; wygasłego relay A1 nie otwierano.

Pierwszy przebieg harmonogramu nie znalazł narzędzi w swoim środowisku. Instalator
poprawiono o bezwzględne ścieżki i katalog roboczy. Faktyczne kolejne przebiegi
18:09:14 i18:10:13CEST miały LastTaskResult0, heartbeat delivery=ok i poprawne pomiary.
Wcześniejszy failed nie jest sukcesem. Testy regresji i zdalny CI PR/main są osobne.

Monitor wymaga włączonego komputera, Dockera i zalogowanego użytkownika. Awaria całego
komputera/harmonogramu wymaga zewnętrznego obserwatora. To lokalny odbiór; monitor VPS
i jego kopie wymagają istniejącego celu wdrożenia i nie są zaliczone tą próbą.
