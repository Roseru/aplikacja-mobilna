# E8.4: dokładna średnia deficytu — poprawka Agenta 3

W ramach bezpośredniego zlecenia właściciela „dokończ E8.4” Agent 3 odczytał
istniejącą dostawę Agenta 2 w [PR42](https://github.com/Roseru/aplikacja-mobilna/pull/42).
Nie opublikował konkurencyjnej implementacji ani drugiego PR. Alternatywna
lokalna implementacja została zachowana osobno; jej wyniki nie są dowodami PR42.
Nowa poprawka `da827ad` dotyczy wyłącznie średniej deficytu i własnego oracle.
Zwykły merge `582e687` zachowuje dostawę autora i main z Androidem0.8.6/PR41.

## Reprodukcja na legalnych danych

SQL dzielił każdy dzienny procent z ustaloną skalą60, potem liczył średnią
i HALF_UP do12miejsc. Utrata cyfr przy dziennym dzieleniu może zmienić stronę
granicy końcowego zaokrąglenia. Własny HTTP/PG oracle na frozen
`e38c6dc71973f15d509ee45a0d25a9ba153dfb31` wykazał rzeczywisty RED:
`"0.000000000001"` zamiast `"0"`. Punkty i outcome nie są dotknięte.

Dziesięć dojrzałych dat: dla i=0..8 używamy E_i=2700+i×0.000015 oraz
intake_i=E_i+(-1)^i×C(8,i)/100. E pochodzi z poprawnego Mifflin/PAL1.5,
weight82+i×0.000001. Ostatnia data ma E2700 oraz intake2699.999999999865.
To suma rzeczywistych pozycji2698.999994 przy100g i100.0015 przy0.999991g.
Wszystkie wejścia wire mają do6miejsc; dwie pozycje tworzą dokładną sumę
obliczoną o większej skali. Cel9999 nie jest zastępczym E.

Dokładny oracle `fractions.Fraction` potwierdza
0 < średnia < 0.0000000000005. HALF_UP do12miejsc musi więc dać"0".
Przypadek lustrzany sprawdza wartości ujemne i brak negative zero.
Pierwotny szkic z12miejscami w wejściu oszacowania został prawidłowo odrzucony
422; nie zaliczono go jako błędu produktu. Legalny poprawiony oracle dał
order6PASS/order8RED, XML `delivered-rounding2.xml`, SHA256
`f1e4f472e68bcebc23de3a7f48f8e66fc7dd44fdc7b161ca8e536cfbc9413e5c`.

## Poprawka i własne dowody

Migration-owned aggregate sumuje dokładne ułamki przez NUMERIC dodawanie
i mnożenie, bez dzielenia poszczególnych dni. Dopiero na końcu div/mod
wyznacza jednostki10^-12 i rozstrzyga HALF_UP. Współczynnik100 i liczba
eligible_days są częścią dokładnego ilorazu. Skala końcowego dzielnika
zachowuje12miejsc również przy większej części całkowitej. Nie dodano nowej
funkcji/grantu, nowego protokołu lub arbitralnej precyzji dziennych ilorazów.
Manifest świeżej migracji wiąże rzeczywiste poprawione body; gate nadal closed.
Opublikowane/scalone migracje0001–0020 nie zostały zmienione.0021 pozostaje
własną niescaloną migracją tego PR, bez wdrożenia lub aktywacji produkcyjnej.

- Własny prywatny proof poprawki:2PASS13,57s. Zastąpienie funkcji przez ownera
  w prywatnej bazie nie było deklaracją wdrożenia kodu repozytorium.
- Rzeczywisty poprawiony source/fresh migration oraz istniejący suite statistics/
  finalizer: **22PASS57,03s**, cztery nowe oracles sign±/order6/8 są częścią
  tej liczby. XML `delivered-fix-source2.xml`; bez failures/errors/skips.
- Osobne sześć własnych scenariuszy z ponownie podmienionym tylko prywatnym
  aggregate:6PASS18,33s. Obejmuje source proof denial, signed0/latestUUID,
  fizyczne source/account locks, rollback/restart/cancel/no-store i frozen
  DST7/30/90. Nie sumujemy go z22 jako pełnej regresji.
- Ruff/format/diff-check poprawki PASS. PostgreSQL17/SCRAM, własne bazy,
  porty i procesy; syntetyczne podpisane JWT nie oznaczają realnego Keycloak.

Przed poprawką Agent 3 wykonał dodatkowy niezależny odbiór PR42: sześć własnych
oracles oraz actual Docker migration0020→0021/hardened SCRAM provision/
trusted activation/installed finalizationCLI-I. Pierwszy calendar oracle miał
błędną nazwę parametru p_day zamiast istniejącego p_date; skorygowany failed-only
run potwierdził3PASS. Wszystkie RED pozostają w prywatnym manifeście, bez
publikowania credentials, raw logs lub SDK paths.

Nowy runtime wymaga ponownego nieautorskiego odbioru tej zmienionej granicy
oraz ośmiu aktualnych kontroli PR head/base i osobnego CI main. Stare zielone
joby i recenzje nie są automatycznym PASS nowego aggregate. Odbiory O1/O3,
rollout/schedule/RPO/RTO oraz całe E8/E8.5 pozostają osobne. Własne kontenery
PG zakończyły pracę; istniejących usług i historii użytkownika nie zmieniono.
