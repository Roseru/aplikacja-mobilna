KALORIE - lokalna instalacja Docker

W tym prywatnym folderze operator zapisuje powiazanie z juz odebrana instalacja.
Zachowaj folder, dotychczasowy stan i wolumeny Docker. Nie usuwaj danych aplikacji
Android ani kont, aby ponownie uruchomic projekt.

1. Uruchom Docker Desktop, potem START.ps1.
2. STATUS.ps1 pokazuje stan API/HTTPS/issuer i istniejacych procesow.
3. STOP.ps1 zatrzymuje instalacje, zachowujac kontenery, dane, konta i klucze.
4. BACKUP.ps1 tworzy nowa prywatna pare kopii baz/katalogu/zdjec i konfiguracji.
   Najpierw START.ps1, potem BACKUP.ps1: PostgreSQL musi dzialac. Przy zatrzymanym
   PG BACKUP odmawia przed utworzeniem folderu kopii i nie uruchamia PG sam.
   Zamyka gateway i wszystkich writerow; PostgreSQL zostaje uruchomiony do dumpow
   i po kopii. STATUS pokazuje wtedy tylko PG running, dziewiec uslug stopped
   oraz brak gotowosci HTTPS/issuer. Wznow zwyklym START.ps1 albo zatrzymaj takze
   PG przez STOP.ps1. Kopie sa w podfolderze backups, chyba ze wskazano
   -Destination z nowa pelna sciezka.

Skrypty nie instaluja APK, nie czyszcza Room, nie importuja katalogu ponownie,
nie buduja obrazow, nie uruchamiaja migracji i nie aktywuja Nemesis lub Gemini.
Brak kontenera, zmiana obrazu/konfiguracji/CA lub niewlasciwy silnik powoduje
odmowe. Operator naprawia taka zmiane i dopiero potem wiaze nowy profil.
Nie kasuj pliku .operation.lock, zanim nie ustalisz, ze poprzedni proces i IO
faktycznie sie zakonczyly.

Kopia zawiera prywatne dane, hasla serwisowe i klucze. Nie publikuj tego folderu,
archiwow ani surowych logow. Do odtworzenia potrzebne sa takze wskazane immutable
obrazy (w tym wlasny backend i Keycloak z providerem) oraz odebrany adapter D2.
Odtwarzanie jest osobnym dzialaniem operatora do NOWEGO celu, z zamknietymi
zadaniami AI i kontrola sesji/epoki. START nie odtwarza kopii w miejscu.

Obecna konfiguracja AI uzywa MOCK. Pozniejsze Gemini konfiguruje sie wylacznie
na backendzie wedlug LOCAL_RELEASE.md i docs/e7/KONFIGURACJA_O3.md.
Plan dla Kamila i bramka EEA/Free Tier: docs/PRZEKAZANIE_GEMINI_KAMIL.md.
Klucz nigdy nie trafia do APK. Ten pakiet nie potwierdza realnego Gemini,
publicznego VPS, pelnego katalogu ARPOL ani calego wydania 1.0.
