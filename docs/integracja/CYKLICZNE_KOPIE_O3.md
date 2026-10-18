# Cykliczne kopie poza komputerem — O3

17.10.2026. Rozszerzenie PR123; źródło kopii pozostaje w istniejącym lokalnym
harmonogramie03/15, z restore każdej kopii i retencją14 poprawnych zestawów.
Nie zmieniamy danych, kont, issuer, epoki lub usług instalacji.

## Dostarczony mechanizm i granice odbioru

[offsite_delivery.py](../../infra/integration/offsite_delivery.py) wybiera
wyłącznie najnowszą odebraną automatyczną kopię własnej instalacji. Wymaga
PASS/integrity/restore/services_resumed, zgodnych markerów owner/project
i rzeczywistego czasu capture nie starszego niż24h. Używa tej samej blokady
utrzymania co lokalny backup i retencja. Nie zatrzymuje usług ani nie wykonuje
nowego capture. Symlink/junction lub źródło poza przypiętym katalogiem odmawia.

Szyfrogram ma nazwę `auto-<czas UTC capture>-<12 znaków SHA manifestu>.enc`
w zatwierdzonym katalogu `/Calorie O3 backups`. Ponowienie dla tego samego
manifestu weryfikuje i wykorzystuje identyczny szyfrogram, bez nadpisania
i bez tworzenia następnych losowych plików. Istniejący inny/uszkodzony plik
lub rotacja klucza bez migracji pozostawia FAIL. Klucz nie trafia do paczki.

`prepare` zwraca PREPARED i `offsite_verified=false`. Dopiero osobny operator
połączonego magazynu wykonuje upload/pobranie metadanych/niezależny download.
`accept-download` wymaga zgodnej ścieżki i ID z tego połączenia, całego SHA256,
uwierzytelnionego odszyfrowania, dokładnego manifestu i rzeczywistego restore
obu baz/globals/katalogu istniejącym narzędziem. Dopiero wtedy atomowo zapisuje
receipt PASS. Lokalny CLI nie twierdzi, że sam uwierzytelnia Dropbox; metadane
i pobrany plik muszą pochodzić z rzeczywistego połączenia.

Monitor sprawdza zarówno czas weryfikacji dostawy, jak i czas capture kopii.
Ponowne pobranie starej kopii nie odświeża jej wieku. Stare receipty bez pola
capture zachowują wcześniejszy kontrakt; nowy nadawca zawsze podaje oba czasy.
Awaria zostawia poprzedni receipt bez zmian; po upływie24h monitor alarmuje.

Prywatny settings.json zawiera `operations`, `backups`, `outgoing`, `key`,
`project`, `dropbox_folder` oraz ścieżkę końcowego `receipt`. Nie trafia do Git.
Początkowy i każdy nowy katalog odbioru muszą mieć prywatne ACL.

```text
python -I infra/integration/offsite_delivery.py prepare --settings <private-settings>
python -I infra/integration/offsite_delivery.py accept-download --settings <private-settings> --prepared <prepared-json> --downloaded <independently-downloaded-enc> --remote-metadata <connector-metadata-json>
python -I infra/integration/offsite_delivery.py recovery-kit --settings <private-settings> --output <new-private-directory>
```

## Harmonogram i klucz odzyskiwania

Docelowy transport przez połączony Dropbox wymaga potwierdzenia konkretnych
plików i schematu nazw. Przygotowano paczkę
`/Calorie O3 backups/auto-20261017T141200Z-8b989906e0ca.enc`, SHA256
`92eae461c68396a557385d25184c11a5b4a86d269b07da92df5619328c475996`.
Nie jest to ponowny odbiór wcześniej wysłanego pliku2026-10-17T141200Z.enc;
nowa paczka ma osobny losowy nonce, chociaż zawiera ten sam odebrany manifest.
Zlecenie stałej wysyłki pozostaje do wykonania po potwierdzeniu zakresu zapisu.
Lokalne przygotowanie ma pory03:50 i15:50; transport połączonego magazynu
proponuje04:00 i16:00 po istniejących kopiach; nie tworzymy drugiego
harmonogramu capture. Przygotowanie jest po45-minutowym limicie istniejącej
kopii, aby nie kolidować z jej blokadą podczas wolniejszego odtworzenia. Wykonawca używa niezmiennego, zatwierdzonego runtime,
pozostaje cichy przy braku nowej kopii i zgłasza błąd lub potrzebę działania.

Przygotowano prywatny lokalny zestaw `recovery-kit` z dokładnym kluczem
i instrukcją. **Nie jest niezależną kopią**, dopóki właściciel nie przeniesie
go na osobny chroniony nośnik i nie odbierze odzyskania na drugim komputerze.
Nie publikujemy klucza w Git, logach, APK ani w Dropbox z zaszyfrowanymi kopiami.
Osobny magazyn/nośnik wymaga wskazania właściciela. Rotacja ma własny odbiór.
Nie usuwano historycznych kopii Dropbox; polityka zdalnej retencji jest osobna.
[Instalator przygotowania](../../infra/integration/install_offsite_prepare.ps1)
używa pythonw/limited/current-user i niezmiennego prywatnego runtime z commita;
nie instaluje tokenów Dropbox ani harmonogramu capture. Zadanie O3-Calorie-Offsite-Prepare z commita16d678b rzeczywiście zainstalowano;
przebieg17.10/23:44:49 ma LastTaskResult0/Ready, pythonw i Limited.
To odbiór przygotowania lokalnego, cloud_upload=false.

### Niezależny interpreter instalowanego runtime

Instalatory przygotowania offsite i lokalnego utrzymania archiwizują również
pełny backend z tego samego commita. Narzędzie
[`runtime_environment.py`](../../infra/integration/runtime_environment.py)
buduje jego własne środowisko z `uv.lock`, offline, bez instalacji edytowalnej
i bez współdzielenia plików zależności przez hardlinki. Wymaga dostępnego `uv`
oraz kompletu zależności w lokalnym cache. Nie pobiera nowego Pythona ani
zależności z sieci. Parametr `-Python` wskazuje interpreter do przygotowania;
zarejestrowane akcje korzystają już z własnego `backend/.venv/Scripts/pythonw.exe`.

Przed rejestracją uruchamia izolowany import i porównuje rzeczywiste
`sys.prefix`, położenie modułu oraz `EXPECTED_REVISION` z archiwalnym źródłem.
Ustawienia `PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV` i konfiguracja `UV_*`
wywołującego nie mogą przekierować instalacji. Nieudana kwalifikacja przerywa
instalację przed rejestracją zadań; lokalny `runtime-install-error.log` zachowuje
diagnostykę błędu instalacji zależności. Dowód środowiska nie jest receipt kopii.
Fizyczna ścieżka kopii jest przekazywana przez JSON, także z polskimi znakami.
Na Windows kwalifikacja i zadania używają pełnych ścieżek rozszerzonych,
aby nie przekroczyć limitu dawnych API plikowych. Wheel jest budowany z
tymczasowej krótkiej kopii archiwalnych źródeł; kopia jest usuwana po instalacji.
Pozostaje zwykły zainstalowany pakiet, bez odwołania importu do tej kopii.

Próba obu instalatorów na źródłach schema26 i syntetycznym stanie dała cztery
poprawne akcje, przy przechwyconej rejestracji zamiast zmiany istniejących zadań.
Osobne rzeczywiste zadanie Windows/Limited/pythonw zaimportowało własny backend26
i zakończyło się wynikiem0; zadanie testowe usunięto. Wcześniejsze błędy długiej
ścieżki zatrzymywały instalację przed rejestracją; ich diagnostyka pozostała
prywatna. Archiwalny backend24 działa również niezależnie od roboczego26.

To zabezpiecza następne instalacje przed importem backendu z roboczej gałęzi.
Nie aktualizuje automatycznie działającej instalacji, schematu bazy ani
istniejących harmonogramów. Utrzymanie źródła schema24 wymaga runtime schema24;
scalenie źródeł schema26 samo nie uprawnia do podmiany tego runtime.

## Walidacja i gotowość wydania

16nowych testów dostawy PASS,5nowych regresji monitora PASS. Cała lokalna
infrastruktura **216PASS** na Windows, Ruff/format PASS. Obejmuje odmowę starego
lub przyszłego capture pomimo świeżej weryfikacji, braków lokalnego odbioru,
złego właściciela, zmienionego szyfrogramu, fałszywego źródła download/ścieżki/ID,
zmiany manifestu, nieudanego restore, zachowanie poprzedniego receipt i odmowę
nadpisania zestawu klucza. Fixture restore w testach jednostkowych jest jawnie
syntetyczne; rzeczywista dostawa wymaga pełnego `backup.py rehearse`.
Nowa rzeczywista lokalna paczka i dokładny klucz z zestawu USB przeszły pełne
odtworzenie obu baz w12,151s; nie jest to nowy upload lub niezależny nośnik.
CLI `python -I ... prepare` rzeczywiście PASS; składnia instalatora Windows PASS.

Checker rzeczywistego kandydata C2/schema24 ponownie potwierdził spójność
APK/obrazu/katalogu, a cały kandydat pozostaje BLOCKED: brakuje
`android_acceptance` O1. Nie dodano fikcyjnego PASS. Produkcyjne KO32 dodatkowo
wymaga telefonu/Room/UI, ciągłego rejestru na drugim hoście, fizycznego fencing
i końcowego cutoff/reconciliation O2, niezależnego klucza, RPO/RTO oraz celu
hostingu/HTTPS/SMTP. Lokalne źródło nie jest przenoszone na nowy serwer.
Próba Android–API jest pozostawiona na poniedziałek19.10 zgodnie z poleceniem.
