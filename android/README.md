# Android — Racje i kalorie

Etap **0.8.28/code39/Room18**, Agent2/O2, dodaje [trwały push sześciu domen](DOMENY_SYNC.md):
profil, cele, kompletność dni i prywatne produkty korzystają ze wspólnej partii
i atomowego ACK obok posiłków/wagi. Kolejne edycje czekają na właściwą rewizję;
odmowy nie potwierdzają zależnych zmian. Migracja zachowuje wcześniejsze dane.
Lokalnie357/372JVM i73celowane nativeAPI35 PASS, lint0błędów; niezależnyreviewPASS.
Pełny CI dokładnego PR/head oraz odbiór koordynatora pozostają osobnymi warunkami.
Import i uzgadnianie (O2-B), WorkManager i archiwa (O2-C) są kolejnymi etapami.
Poniżej zachowano historyczne raporty; zwykła aplikacja i kandydat E4 O1 bez podmiany.

Etap **0.8.27/code38/Room17** na `codex/android-pobieranie-dziennika` dodaje
[pełną kopię serwera w lokalnym dzienniku](POBIERANIE_DZIENNIKA.md): posiłki,
wagę, profil, cele, kompletność dni i prywatne produkty. Cała kopia jest
sprawdzana przed atomowym zapisem; niewysłane zmiany pozostają zachowane.
Zapisaną kopię można zastosować offline z ekranu konta.

Końcowy build/lint PASS (0 błędów, 4 ostrzeżenia), 13/13 celowanych testów
urządzenia offline PASS oraz 6 JVM zmienionego helpera PASS; wcześniejsze
35 niezmienionych JVM zachowuje swój wynik. To odbiór celowany, nie pełna
regresja. [Manifest](ODBIOR_0_8_27.json) odróżnia wcześniejszy błąd asercji UI,
końcowe poprawki i dokładne SHA APK. Zwykły emulator zaktualizowany0.8.25→0.8.27:
wszystkie wartości i rowid28starych tabel zachowane, FK czyste. Dziennik otwarty
do prób ręcznych. Zdalny CI [PR144](https://github.com/Roseru/aplikacja-mobilna/pull/144) pozostaje osobnym odbiorem.

Rodzic [PR142](https://github.com/Roseru/aplikacja-mobilna/pull/142) jest scalony
jako b434754. Własny CI39767329100 i osobny CI main39772774959: oba 8/8 SUCCESS.
Dołączono aktualny main a034f66 z instrukcją O3-085 do kolejnego E4;
nie zmienia ona kwalifikowanych źródeł Androida. Poniżej historyczne opisy etapów.

Etap **0.8.26/code37/Room16** na `codex/android-konflikty-sync` dodaje
[porównanie i świadome rozwiązywanie konfliktów posiłków i wagi](KONFLIKTY_SYNC.md):
wersja lokalna/serwerowa, nowa operacja po decyzji, odtwarzanie pod nowym UUID
i trwała historia decyzji. Starsze kolejki, pełne uzgadnianie i WorkManager
pozostają kolejnymi etapami. Lokalnie35JVM i41native PASS, po końcowej
poprawce10native PASS bez ponownego JVM; źródło lokalnych APK9a041bd.
CI publikowanego head oraz aktualizacja zwykłego emulatora są osobnymi odbiorami.

Poprzedni etap141 scalono jako8d67936; własny CI39736449922 i osobny
push CI main39739653358 przeszły wszystkie8kontroli. Poniżej jego wcześniejszy opis.

Etap **0.8.25/code36/Room15** na `codex/android-waga-sync` dodaje
[kanoniczne pomiary wagi i wspólny ACK z posiłkami](WAGA_SYNC.md).
Odbiór lokalny:30wybranychJVM i336/336native PASS. Aktualizacja0.8.24→0.8.25
zachowała27starszych tabel, wszystkie wartości i rowid; aplikacja otwarta
do prób ręcznych. [Metadane odbioru](ODBIOR_0_8_25.json) zawierają źródła/SHA.
Dołączono main e1e28df po scaleniu140; własny CI integracji141 jest osobnym odbiorem.

Historyczny wstęp main po integracji140:

Integracja140 z22.10.2026: zwykły merge25f7e4c i rzeczywistego main34d7cb2
po scaleniu139. Całe android/app i Gradle bez zmian,0.8.24/code35/Room14.
PR140 przechodzi na main; własny pełny CI nowego head/base jest wymagany.
Waga141 pozostaje oddzielnym etapem. Starsze opisy zależności poniżej są historyczne.

Aktualizacja zależności140/21.10: `codex/android-integracja-pr140` dołącza
dokładny rodzic139/afb6a0a. PR140 pozostaje zależnym draftem. Produkcja,
schemat14 i wersja0.8.24/code35 bez zmiany; istniejący lokalny odbiór poniżej
nie zastępuje własnego przyszłego CI po integracji rodziców.

Nowy etap **0.8.24/code35/Room14** na `codex/android-posilki-katalogowe-sync`
rozszerza [kolejkę o produkty katalogowe i wybrane składniki racji](POSILKI_KATALOGOWE_SYNC.md).
Odbiór lokalny:13 wybranych JVM i11 native PASS, lint0error. APK0.8.24
uruchomiono jako aktualizację zachowującą dziennik; pełny CI integracji
i rzeczywisty katalogowy APK/API pozostają osobno.

Rodzic139/a1f547a dostarcza [ręczne posiłki w sync-v1](POSILEK_RECZNY_SYNC.md):
prywatny produkt pozostaje lokalny, a spożycie ma osobną operację Meal.
Jego330/345JVM i328native PASS dotyczą wcześniejszego źródła c24583b,
nie zastępują sprawdzenia obecnego etapu. Starsze wpisy legacy są osobno.

Stan rodzica139 przy aktualizacji zależności:

Gałąź `codex/android-integracja-pr139` dołącza dokładny rodzic129/3155d84.
PR139 pozostaje zależnym draftem, dopóki129 nie przejdzie własnego CI i merge.

Historyczny wstęp rodzica139 przed merge:

Gałąź `codex/android-integracja-pr139` zawiera rzeczywisty main167152a po
scaleniu priorytetowego137, z zachowaniem O2-049. Istniejący PR139 przechodzi na main i wymaga własnego pełnego CI.
Produkcja139/0.8.23/Room14 bez zmiany; lokalny odbiór330/345JVM i328native
jest historyczny. Zwykły emulator zachowuje nowszy APK0.8.24/code35 z PR140.

Historyczny wstęp139 (pełny późniejszy odbiór w POSILEK_RECZNY_SYNC.md):

Na niezależnej gałęzi `codex/android-posilek-reczny-sync` przygotowano
[nowe ręczne posiłki w sync-v1](POSILEK_RECZNY_SYNC.md): prywatny produkt
pozostaje lokalny, a jego spożycie po bootstrapie ma osobną operację Meal.
18 JVM PASS; repozytorium i8 testów Room skompilowane, wykonanie urządzenia
i nowy APK jeszcze NOT_RUN. Starsze wpisy/katalog/racje są osobno.
Kod [drivera E4](https://github.com/Roseru/aplikacja-mobilna/pull/138) jest
w oddzielnym PR; nie jest zależnością kodu tego etapu ani odebranym testem live.

Stan rodzica129 przy aktualizacji zależności:

Gałąź `codex/android-integracja-pr129` zawiera aktualny main e651fea po scaleniu
PR122. Istniejący PR129 przechodzi na main i wymaga własnego pełnego CI.
Zwykły emulator zachowuje późniejszy APK0.8.24/code35/Room14 z PR140.

Poniżej historyczny odbiór źródła129/9a3a9a9; nie jest wynikiem nowego merge:

Kandydat **0.8.23/code34/Room14** na `codex/android-wysylanie-kolejki`
łączy [transport trwałych partii](WYSYLANIE_KOLEJKI.md) z sesją i
[przyciskiem wysyłania posiłków](SYNCHRONIZACJA_INTERFEJS.md).
Zapisana partia przetrwa utratę odpowiedzi, a termin Retry-After również
wylogowanie. Lokalny odbiór: 322/337 JVM, 22 celowane i 320 pełnych testów
urządzenia PASS, lint 0 błędów; [manifest dowodów](ODBIOR_0_8_23.json).
To domyślny wariant offline, bez konfiguracji rzeczywistego E4. Aktualizacji
zwykłej aplikacji i próby push z serwerem jeszcze nie wykonano. R2/R3 na
starszym APK nie potwierdzają nowego push. Kandydat nie ma drivera POST.

Etap PR122 **0.8.22/code33/Room13** pozwala jawnie wrócić do poprawek po
odrzuconej decyzji i poprawnym odczycie stanu serwera. Zachowuje stare body,
klucz i pochodzenie w historii, a nowa zgoda ma osobny klucz i te same UUID
posiłku/składników. Niepewna wysyłka nadal wymaga identycznego replay.
[Raport](POWROT_DO_POPRAWEK.md):313/328JVM,17 celowanych i299 pełnych testów
urządzenia PASS, lint0error. Migracja12→13 zachowała26 starszych tabel i rowid;
to historyczny odbiór tego źródła. Integracja z main6069dc7 wymaga własnego
CI; lokalnych jednostkowych nie powtarzano. Zwykły emulator ma późniejszy
APK0.8.24/code35 z PR140. Rzeczywisty APK/API, push/pull, legacy, pełne recovery
i retencja pozostają osobnymi etapami.

Wydanie **0.8.21/code32/Room12** pozwala zatwierdzić poprawiony wynik zdjęcia
przyciskiem „Dodaj do dziennika”. Zachowuje tę samą decyzję po utracie odpowiedzi
i restarcie; pełny ACK zapisuje atomowo posiłek, pochodzenie i kanoniczną kolejkę.
[Raport](POTWIERDZENIE_INTERFEJS.md):310/325JVM,14 celowanych i286 pełnych testów
urządzenia PASS, lint0error. Aktualizacja zachowała wszystkie26 tabel i rowid;
aplikacja jest otwarta do testów. To lokalny odbiór syntetyczny; rzeczywisty
APK/API, transport push, legacy/recovery i nowa decyzja po odrzuceniu były wtedy osobno.

Wydanie **0.8.20/code31/Room12** ma trwałe partie kanonicznych Meal i atomowy
odbiór ACK, który zachowuje nowsze porcje oraz nadaje właściwą rewizję kolejnej
intencji. [Raport](SYNCHRONIZACJA_PUSH.md):308/323JVM,273native API35 i lint0error
PASS;25 wcześniejszych tabel/rowid zachowane po aktualizacji, aplikacja otwarta.
Był to odbiór lokalnego zapisu na fixture. Na tym etapie transport, kontrola sesji, przycisk confirm,
konwersja legacy i pełne recovery pozostają do podłączenia.

Poniższe konkretne wydania zachowują własne historyczne źródła i receipty.

Android **0.8.19/code30/Room11** dodaje atomowy zapis zweryfikowanego wyniku
confirm jako Meal/Items, provenance i kanonicznej kolejki E4, ze stabilnym replay
po edycji/usunięciu i odzyskaniem przy błędzie transakcji. Dziennik pokazuje
nieokreślony typ posiłku i dokładne ilości g/ml; brak energii pozostaje niepełny.
[Raport i ograniczenia](POTWIERDZENIE_POSILKU.md):291/306JVM,260native API35,
lint0error PASS,24 stare tabele i rowid zachowane po aktualizacji. HTTP confirm,
przycisk zatwierdzania i standardowy push nadal wymagają podłączenia; to nie
odbiór pełnego E4/E7. [Podglądy](../propozycje-ui/analiza-0.8.19/README.md).
Kolejny etap ma [bibliotekę paczek i odpowiedzi push E4](SYNCHRONIZACJA_PUSH.md):
308/323 JVM i lint0error PASS, bez podmiany zainstalowanego APK. Trwały odbiór
ACK w Room, transport i uruchomienie oczekujących intencji są do podłączenia.
Poniższe opisy konkretnych wcześniejszych wydań zachowują ich historyczny zakres.


Android **0.8.16** dodaje świadomą wysyłkę zdjęcia, trwałe ponowienie i pobieranie wyniku z lokalnym podglądem składników/kcal/B/T/W. Wejście na ekran odtwarza zapis bez sieci; GET wymaga przycisku, działa w ograniczonym budżecie i respektuje sesję oraz wspólny backoff. [Stan i dowody](ZLECENIE_ANALIZY.md):235/250 JVM,223 native API35 i lint0error PASS. Room9→10 dodaje kolejkę analizy. Anulowanie serwerowe, korekty/confirm/E4 i rzeczywisty Gemini nadal wymagają dalszych etapów. PR105 jest draft zależnym od PR96, bez własnego pełnego zdalnego CI.

Android **0.8.13** dodaje jawne sprawdzanie dostępności analizy zdjęć dla własnego konta: dostawcę/model, limity i stan usługi, z obsługą utraty sesji i czasu ponowienia. Zdjęcia nadal pozostają lokalne; odczyt nie przyznaje zgody i nie wysyła obrazu. [Raport](RAPORT_0_8_13.md) opisuje walidację, zachowanie danych i zależność od PR73. Room9 bez migracji. Multipart/Gemini/confirm i zapis przez E4 wymagają dalszych etapów.

Android **0.8.12** dodaje lokalne zdjęcia z aparatu i galerii, trwały podgląd/usuwanie w aktywnym profilu oraz ręczny fallback. Poprawia Done w edycji gramatury. [Raport](RAPORT_0_8_12.md):165 JVM/21 końcowych zmienionych testów PASS; wcześniejsze188/186PASS+2RED zachowane osobno. Room8→9 zachował wszystkie stare kolumny22tabel/5posiłków. Upload/Gemini/confirm/sync i rzeczywisty APK/API nadal mają dalsze odbiory.

Android **0.8.11** dodaje kody i zaproszenia Nemesis, świadomą akceptację zakresów oraz zakończenie udostępniania. Dokładna decyzja jest zapisana przed HTTP i ponawiana ręcznie tym samym kluczem po utracie odpowiedzi. [Raport i podglądy](RAPORT_0_8_11.md):165 JVM/179 pełny device dla pierwszego źródła, końcowe4 formularze po poprawce klawiatury osobno; Room8 bez migracji,22tabele/5posiłków zachowane. Gęstszy ranking, osiągnięcia i Postępy pozostają zachowane. Rzeczywisty pairing APK/API, E4/recovery i klientE9 wymagają dalszych odbiorów.

Android **0.8.10** dodaje odczyt Nemesis: listę rywalizacji, uzgodnione zasady, punkty oraz dozwolone porównania. Pending/hidden/null/zero są oddzielne, a powrót na ekran ponownie sprawdza udostępnianie. [Raport i podglądy](RAPORT_0_8_10.md):155 JVM/168 pełny device i końcowe72 affected osobno; Room8 bez migracji,5posiłków zachowane. Zaproszenia/accept/cancel i realny API mają dalsze odbiory.

Android **0.8.9** zagęszcza ranking zgodnie z feedbackiem: wspólny wiersz pozycji/punktów i mniejsze odstępy, z czytelnym układem przy dużym tekście. Poprawia rozróżnienie deklaracji zgody i aktywnego automatu po przekazaniu E9. [Raport i podglądy](RAPORT_0_8_9.md):144 JVM i18 zmienionych testów urządzenia PASS, Room8 bez migracji,22tabele/5posiłków zachowane. Nemesis, klientE9 i rzeczywisty API mają dalsze etapy.

**0.8.8/code19/Room8**: Profil→Osiągnięcia→Udział w rankingu→Zobacz ranking. Ręczne pobieranie25osób, timestamp, serwerowe remisy, next/retry/restart, odcięcie peer/cursor przy zmianie sesji/kontekstu lub wyjściu. [Raport](RAPORT_0_8_8.md) rozdziela144JVM/156device od ostatnich14UI i3QA. Domyślny APK offline/gość, bez fikcyjnych uczestników. Mniejsze podsumowanie i odznaki przed serwerem oraz Postępy zachowane.

Wersja **0.8.7**, code18, Room8: Profil → Osiągnięcia → Udział w rankingu. Jawny odczyt zgód, afirmacja checkboxem, osobny opt-out, zachowanie zgody korekty zapotrzebowania oraz trwałe ponowienie identycznego PUT po utracie odpowiedzi. [Raport i podglądy](RAPORT_0_8_7.md) rozdzielają historyczne146/147,11/11 oraz nowy pełny135JVM/147device PASS po selektorze; oryginalne RED zachowane. Domyślny APK pozostaje offline, rzeczywisty API/OIDC/TLS nie jest potwierdzony fixtures.

Wersja **0.8.6** pokazuje mniejsze podsumowanie i więcej lokalnych odznak, a pod nimi prywatny panel GET `/api/v1/me/motivation`: punkty, ranga, pending/final/revoked i data potwierdzenia. Pobranie na żądanie po zalogowaniu/bootstrapie, bez odnawiania zgody rankingu. [Raport i podglądy](RAPORT_0_8_6.md) rozdzielają pełny126JVM/129device od końcowych18UI; lint0error. Room8 bez migracji; install-r/launch zachował wszystkie kolumny22tabel/5posiłków. Domyślny APK nadal działa jako gość offline; rzeczywiste API czeka na własny odbiór.

Wersja **0.8.5** dodaje „Profil → Osiągnięcia”: cztery lokalne warunki v1, postęp całej historii i daty spełnienia, wstępne dzisiaj, przeliczenie po korekcie oraz osobny stan niepobranego potwierdzenia serwera. [Raport i syntetyczne podglądy](RAPORT_0_8_5.md):115JVM/117device PASS, lint0błędów; Room7→8 zachował wszystkie stare kolumny22tabel/5posiłków. Wygląd Postępów0.8.4 został zaakceptowany i pozostaje zachowany. GET motywacji, ranking i Nemesis mają osobną integrację.

Wersja **0.8.4** odświeża analitykę7/30/90 i układ na wąskich ekranach/powiększonej czcionce, bez zmiany obliczeń lub Room7. [Raport, podglądy i próba manualna](RAPORT_0_8_4.md):103JVM/107device oraz końcowe3UI PASS, lint0błędów; aktualizacja zachowała22tabele/5posiłków. Backend osiągnięć/rankingu E8.1+2 jest scalony, jego połączenie z Androidem pozostaje kolejnym etapem.

Wersja `0.8.3` dodaje [trwałe pobieranie kopii danych serwera](SYNCHRONIZACJA_PULL.md), wznowienie stron i atomowy checkpoint w Room 7. Lokalny dziennik oraz outbox pozostają osobno. Semantyczne projekcje, push, inkrementalny pull, import gościa i WorkManager są kolejnymi etapami E4. Domyślny APK nadal działa offline bez skonfigurowanego API.

Wersja `0.8.2` dodaje [podgląd profilu na serwerze](ODCZYT_PROFILU.md) po bootstrapie: pseudonim, wzrost, klasa, strefa i zgody. Odczyt nie nadpisuje lokalnego profilu, celu kcal ani kolejki. [Raport 0.8.2](RAPORT_0_8_2.md) rozdziela testy zastępcze od wymaganego odbioru rzeczywistego API. PR26 i PR31 są scalone na main; pełny sync pozostaje kolejnym zadaniem.

Wersja `0.8.1` dodaje połączenie konta z API przez trwały bootstrap HTTP, odnowienie sesji przed żądaniem i bezpieczne ponawianie bez utraty klucza. [Raport](RAPORT_0_8_1.md), [konfiguracja HTTP](BOOTSTRAP_HTTP.md) i [sesja OIDC](SESJA_OIDC.md) rozdzielają testy lokalne od pozostającego odbioru prawdziwego APK/HTTPS/Keycloak. Domyślne APK bez issuer i adresu API działa jako gość offline. Bootstrap nie wysyła dziennika ani nie importuje gościa; synchronizacja pozostaje kolejnym etapem. Room 6 zachowuje dotychczasowe wartości i kolejkę.

[Raport 0.7.2 i scenariusze manualne](RAPORT_0_7_2.md) opisują odbiór poprzedniego etapu. Tryby 0.7.3: etat biurowo-kawowy ×1,00, Linia ×1,25, Komandos ×1,50; zmiana przelicza bieżący cel przez stosunek mnożników. Podgląd poprzedza zapis. Ręczne kcal, B/T/W i wcześniejsze dni pozostają zachowane; to przelicznik celu, osobny od kalkulatora zapotrzebowania backendu.

## Co zawiera

- Cztery lokalne osiągnięcia: serie10dni kompletności/celu, pomiary4różnych dni w14dniach, racje5różnych dni; korekty mogą usunąć spełnienie warunku. Odczyt nie publikuje punktów/rankingu.
- Jasny i ciemny motyw oraz wybór zgodny z systemem, zapisany w DataStore.
- Dziennik według dni, wybór daty, suma kcal i B/T/W oraz realizacja celu.
- Wbudowany katalog: 15 dawnych produktów oraz 18 produktów pakietu E2; wyszukiwanie także bez polskich znaków, aliasy E2 i ostatnio używane produkty.
- Dwa zestawy demonstracyjne dostępne w „Dodaj posiłek → Racje”. Zaznaczanie tylko zjedzonych składników, gramatura części opakowania, skróty ¼/½/całość oraz wspólny bilans zaznaczenia. Początkowo nic nie jest zaznaczone.
- Racja jest jednym wpisem z wieloma składnikami. Można poprawić lub usunąć jeden składnik albo usunąć całą rację; usunięcie ostatniego składnika usuwa wpis z dziennika.
- Wybór grupy posiłku, gramatury, podgląd kcal, zapis, edycja i usunięcie wpisu.
- Własny produkt z nazwą, źródłem i wartościami na 100 g, opcjonalnymi makrami oraz gramaturą spożycia. Produkt jest prywatny i dostępny do ponownego wyboru; zapis szkicu i pierwszego posiłku jest transakcją.
- Lokalny profil: pseudonim, wzrost, Etat biurowo-kawowy/Linia/Komandos i cel redukcja/utrzymanie/nadwyżka. Zmiana klasy przelicza bieżący cel kcal po podglądzie i zapisaniu; B/T/W i wcześniejsze dni pozostają. Ręczne cele są dostępne w ustawieniach.
- Pomiary wagi z datą, historią, korektą i usunięciem. Kilka pomiarów jednego dnia jest dozwolone. Po poprawnym zapisie pole masy jest czyszczone, aby ponowny przypadkowy klik nie zapisał kolejnego pomiaru.
- Deklaracja kompletności dnia. Efektywna kompletność wymaga deklaracji, nieusuniętych składników, dodatniej sumy kcal i znanej energii wszystkich pozycji. Brak makr pozostaje brakiem danych. Usunięcie ostatniego posiłku lub dodanie pozycji bez kcal cofa efektywną kompletność; wcześniejsza deklaracja pozostaje w historii i można ją wyłączyć.
- Postępy dla 7/30/90 dni: wykresy kcal/B/T/W i rzeczywistych pomiarów wagi, średnie, kompletność oraz realizacja celu obowiązującego każdego dnia. Historia pozwala otworzyć dziennik wybranej daty, także pustego dnia.
- Cele kcal/B/T/W obowiązujące od dnia zmiany; każda decyzja zachowuje wcześniejszą wersję, także przy kolejnej zmianie tego samego dnia. Korekta wskazuje poprzedni cel tego właściciela. Brak makr nie jest traktowany jak zero.
- Room z wersjonowanym schematem, identyfikatorami UUID, odżywczymi wartościami zapisanymi przy spożyciu i transakcyjną kolejką zmian.
- Zapis lokalnej daty, strefy czasowej i czasu UTC. Ponowienie lokalnego zapisu z tym samym ID nie tworzy drugiego posiłku.

Katalog i początkowy cel 2800 kcal są **danymi demonstracyjnymi**, nie zweryfikowaną bazą żywieniową ani wyliczonym zapotrzebowaniem użytkownika. Dawne zestawy A/B nie odwzorowują specyfikacji S-R/S-RG ani żadnego producenta. Nowy pakiet E2 dodaje osobną niezweryfikowaną, niepełną rację S-RG-1 z 18 policzalnymi komponentami i informacją o pozycjach poza obliczeniami. Nie łączymy zestawów po nazwie lub kalorii. Dawne napoje pozostają w gramach; nowy katalog obsługuje g/ml, bez założenia, że 1 ml = 1 g.

Schemat Room 8 zawiera migracje 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 zachowujące posiłki, racje, cele, prywatne produkty, profil, pomiary, deklaracje dni, właścicieli i całą kolejkę. Migracja7→8 dodaje nullable pozycję składnika zapisaną przy nowym spożyciu racji, bez backfill wcześniejszych wpisów. Migracja 6→7 dodaje cztery osobne tabele kopii serwera. Migracja 5→6 przebudowuje tabelę celów z zachowaniem wszystkich wcześniejszych kolumn i ID, dodaje metadane wersji/złożony FK korekty oraz dwie tabele bootstrapu. Nie zmienia wartości REAL ani dawnych payloadów outbox. Prywatne dane mają zakres właściciela. Usuwanie spożycia pozostawia znacznik i operację kolejki; wersje celów są niezmienne.

## Przygotowanie E3 i niezmienne cele

`AccountBootstrapStore` utrwala klucz niezakończonego żądania, powiązanie lokalnego właściciela z `account_id` oraz niezależne `account_generation`/`sync_epoch`. Sprawdza właściciela, generację lease i żądanie przy przyjmowaniu odpowiedzi; powiązanie i potwierdzenie zapisują się atomowo. Restart nie zmienia klucza ponowienia. Zmiana kontekstu serwera ustawia trwałą blokadę wymagającą uzgodnienia E4; nie resetuje dziennika lub kolejki. Klient sesji i bootstrap HTTP są dostępne od 0.8.0/0.8.1; realny odbiór API nadal jest osobny.

Zmiana celu tworzy nowy UUID zamiast nadpisania poprzedniego wiersza. Wersja ma lokalną sekwencję, czas/strefę decyzji i referencję korekty z własnością wymuszoną w SQLite. Odczyty dziennika i analityki wybierają najnowszą wersję dla daty. Callback `DATABASE_GUARDS` chroni treść przed UPDATE/DELETE oraz zmieniającym INSERT OR REPLACE, także po ponownym otwarciu bazy; przy tworzeniu bazy poza aplikacją należy go dołączyć. Lokalne sekwencje i kolejka wymagają osobnego adaptera serwerowej osi/Decimal.

[Przekazanie E3 dla O2/O3](INTEGRACJA_E3.md) podaje dokładne przyszłe callbacki APK, reguły bootstrapu, granice i kolejne kroki. [Raport 0.7.0](RAPORT_0_7.md) opisuje pierwszy odbiór; [raport 0.7.1](RAPORT_0_7_1.md) dokumentuje końcowe 65 JVM / 52 urządzenia i połączone poprawki recenzji.

## Fundament kont i izolacji

`LocalOwnerStore` utrwala UUID gościa, rejestruje dokładną parę wystawcy i podmiotu oraz przechowuje aktywny zakres wraz z generacją. Rejestracja metadanych nie zmienia aktywnego właściciela. Każdy wybór, także ponowny wybór tego samego konta, unieważnia stare `OwnerLease`.

`DiaryRepository` wiąże się z jednym właścicielem. Wszystkie jego mutacje sprawdzają zakres i generację wewnątrz tej samej transakcji co zapis danych oraz outbox. ViewModel przekazuje zakres repozytorium także do odczytów i analityki. Katalog pozostaje wspólny; prywatne produkty, spożycia, profile, cele, waga, kompletność i operacje pozostają osobne. Obce ID nie pozwala nadpisać pomiaru wagi ani zmienić cudzego posiłku. Kolizje istniejących globalnych ID kończą się błędem bez przeniesienia rekordu.

Stare rekordy i payloady nadal mają `ownerScope=guest`; nowy UUID gościa jest związany z tym aliasem w rejestrze. Nie zmieniamy identyfikatorów ani treści zaległych operacji. Konto ma zakres równy swojemu lokalnemu UUID, odrębny od `sub` i serwerowego identyfikatora użytkownika. Żadne przełączenie nie przypisuje ani nie wysyła danych gościa.

To wewnętrzny fundament, bez logowania lub wyboru konta w UI. Rejestr metadanych nie uwierzytelnia użytkownika. Przy integracji trzeba utworzyć go z potwierdzonej sesji OIDC, odtworzyć ViewModel i wyczyścić pamięć ekranów po zmianie konta oraz dodać analogiczne kontrole przed wysyłką i zapisem odpowiedzi HTTP. Aktualne klucze tabel pozostają globalnymi UUID; docelowe klucze z właścicielem, jawne przypisanie gościa i adapter E0 wymagają kolejnego etapu. [Raport 0.6.0](RAPORT_0_6.md) podaje odbiór oraz te granice.

## Import katalogu i dokładność

Pakiet E2 pochodzi z rzeczywistego eksportu PostgreSQL osoby 2, commit [`229a2b8`](https://github.com/Roseru/aplikacja-mobilna/tree/229a2b8/backend/data/demo/export). Artefakty i normatywne schematy E0 są osadzone w `app/src/main/assets/catalog/e2/`; wektory w zasobach testowych. SHA-256 gzip: `65f4aae8002fd5522d0edb4689e05682103b80fbe3e6dbc68f4bf02c645b2bef`; gzip 3099 B, JSON 15691 B. To eksport E2, a nie starszy fixture E0. Fizyczny asset APK ma nazwę `base-pl.1.json.gz.bin`, ponieważ etap MergeAssets automatycznie rozpakowywał rozszerzenie `.gz`. Sufiks `.bin` zachowuje oryginalne skompresowane bajty; manifest nadal ma kontraktowy logiczny path `base-pl.1.json.gz`.

- `CatalogPackageReader` sprawdza zaufaną tożsamość demo `47bdff67-e58b-5437-919b-ec00159afbc5`, kind/release/schema/reader, dokładne bajty i rozmiary, CRC i pojedynczy strumień gzip, ścisły UTF-8/JSON, schemat oraz graf referencji. Limity: manifest 1 MiB, gzip 10 MiB, JSON 50 MiB. Czytnik schematów obsługuje słowa kluczowe użyte w przypiętych dwóch schematach; nie jest ogólnym silnikiem JSON Schema.
- Hash jest liczony przed rozpakowaniem. Daty `published_at` z 1–6 cyframi ułamka sekund pozostają w oryginalnej pisowni zgodnie z poprawką E2 z 10 października. SHA nie uwierzytelnia pakietu; obecny kanał dostawy to APK, a pobieranie przez HTTPS będzie osobnym etapem.
- `CatalogStore.stage()` zapisuje nieaktywną generację w transakcji; `activate()` przełącza ją krótką transakcją tylko na nowszy kompletny release. Ponowienie jest no-op; inna treść pod tym samym release albo UUID+revision jest błędem. Ekrany czytają aktywne członkostwo, a stare wersje pozostają dla historii. Sprzątanie generacji nie jest zaimplementowane.
- Dokładne wartości, metadane produktów/racji/źródeł i ilości komponentów są przechowywane jako TEXT. Wewnętrzne klucze zawierają typ, dokładny UUID i rewizję; pozycje składników E2 wynoszą 1..N. Kolumny REAL pozostają projekcjami dla zgodności wcześniejszych ekranów, nie źródłem nowych obliczeń.
- Nowe spożycie z E2 zapisuje pełny produkt z rewizją, jednostkę i tekst ilości, źródła/gęstość oraz `nutrition_v1` w snapshot i lokalnej kolejce. Edycja zmienia ilość snapshotu, zachowując jego produkt; aktualizacja katalogu nie przelicza historii.
- `NutritionV1` liczy przez BigDecimal: per100 × ilość / 100; dzielenie przy g→ml ma skalę 12 HALF_UP, konwersja wymaga udokumentowanej gęstości. Sumowanie następuje przed zaokrągleniem wyświetlania (0 miejsc kcal / 1 miejsce makr HALF_UP); energia nie jest wyliczana z 4/4/9. Każde pole ma known_sum, missing_count i complete. Niepełne sumy pokazują `≥` oraz liczbę braków.

Stare dane REAL są odczytywane przez `BigDecimal.valueOf` bez nadpisania oryginału i bez twierdzenia, że odzyskano utraconą dokładność. Prywatne produkty, cele, profil i pomiary nadal mają dawną reprezentację zapisu. Ich pełny adapter Decimal do API pozostaje do wykonania. Formy porcji dopuszczają lokalnie do 12 miejsc, aby nie obcinać wyliczonych ułamków opakowania; przyszły adapter synchronizacji musi jawnie obsłużyć ograniczenie Quantity E0 do 6 miejsc. Nie obcinamy kolejki w miejscu ani nie wysyłamy jej w obecnym formacie.

## Postępy i historia

Dolna zakładka **Postępy** pokazuje ostatnie 7, 30 lub 90 dat kalendarzowych włącznie z dzisiaj. Dzisiejszy wynik jest wstępny; średnie i liczniki oceny obejmują zamknięte dni. Odczyt odświeża się po lokalnej północy bez nowego wpisu, z uwzględnieniem DST. Domyślne okno podąża za dzisiaj; wybrane historyczne okno pozostaje stałe po odtworzeniu. Strzałki przesuwają okno o wybrany okres; „Do dzisiaj” przywraca bieżący zakres. Okres i wybrany wykres pozostają po odtworzeniu aktywności.

- Cel pobieramy z ostatniej wersji obowiązującej w danym dniu, również sprzed początku okna. Przyszłe cele nie wpływają na wcześniejsze dni. `goal_band_v1` stosuje granice ±10% włącznie, przed zaokrągleniem wyświetlania. Do oceny potrzebny jest kompletny dzień i dodatni cel; brak celu oznacza brak oceny.
- Dni bez wpisów pozostają bez danych. Dni niepotwierdzone lub z nieznaną energią pozostają niekompletne. Ich znane wartości są widoczne w historii i na wykresie jako niepełne, ale nie sugerujemy deficytu ani nie dodajemy ich do średniej.
- Średnia każdego pola obejmuje zamknięte, kompletne dni ze znaną wartością tego pola; obok wyniku pokazujemy własny mianownik. Dzień z brakującym białkiem może mieć znane kcal, a białko nie trafia do jego średniej. Znane zero pozostaje zerem. Sumy są dokładne; średnia jest dzielona w skali 12 HALF_UP i zaokrąglana dopiero do prezentacji.
- Wykres wagi i zmiana masy używają ostatniego rzeczywistego pomiaru każdej daty w oknie; czas UTC i ID rozstrzygają kolejność. Licznik obejmuje wszystkie nieusunięte pomiary. Do zmiany masy potrzebne są co najmniej dwie daty z pomiarem. Nie interpolujemy ani nie przenosimy pomiarów z innych dni lub spoza okna.
- Odczyty Room są ograniczone do właściciela i zakresu; pomijają znaczniki usunięcia. Edycje, usunięcia, nowe cele, pomiary i deklaracje aktualizują obserwowany wynik. Analityka nie zapisuje operacji outbox ani nie modyfikuje dziennika. Aktualność dotyczy wyłącznie danych na urządzeniu; synchronizacja nadal nie jest podłączona.

## Co pozostaje na następne etapy

Do pełnego odbioru pozostają: synchronizacja starszych wpisów i pozostałych
typów danych (profil, cele, waga, kompletność), zastosowanie kopii serwera
w lokalnym dzienniku, import gościa za zgodą, konflikty, recovery po 30 dniach,
retencja i WorkManager. Kandydat 0.8.23 ma ręczne wysyłanie kanonicznych Meal,
ale nie ma jeszcze dowodu rzeczywistego push APK/API. R2/R3 potwierdziły
konkretne odczyty/logowanie starszego APK; pełna macierz kont pozostaje osobno.
Następne funkcje to katalog społeczności, kalkulator i korekty zapotrzebowania,
zweryfikowane pakiety racji/MRE oraz pełne próby Gemini, rankingu i Nemesis.
Prywatne produkty nie są publikowane; pakiet demo nie jest katalogiem official.

## Uruchomienie w Android Studio

1. Otwórz katalog `android/` jako projekt.
2. Użyj JDK 17 lub 21 i zainstalowanego SDK Platform 35 / Build Tools 35.0.0. Minimalna wersja urządzenia: Android 8.0 (API 26).
3. Poczekaj na synchronizację Gradle. Wrapper i wersje bibliotek są przypięte w repozytorium.
4. Uruchom moduł `app` na emulatorze lub telefonie. Pierwszy dziennik jest pusty, bez fikcyjnie zjedzonych posiłków.

Android Studio zwykle tworzy ignorowany `local.properties` z własną ścieżką SDK. Nie kopiuj do repozytorium konfiguracji ścieżek innego komputera.

## Komendy dla osoby 3 / CI

Uruchom z katalogu `android/`, przy ustawionym `JAVA_HOME` i dostępnym SDK:

```powershell
.\gradlew.bat :app:assembleDebug :app:testDebugUnitTest :app:testValidationUnitTest :app:lintDebug
.\gradlew.bat :app:connectedValidationAndroidTest
```

Na Linuxie: `./gradlew` z tymi samymi zadaniami. Druga komenda wymaga uruchomionego emulatora lub podłączonego urządzenia. Testy urządzenia działają w osobnej aplikacji `pl.roseru.kalorie.validation`; instalacja i sprzątanie testów nie usuwa zwykłego dziennika `pl.roseru.kalorie`. Pierwsza kompilacja pobiera zależności; gotowa aplikacja do działania nie wymaga sieci.

APK debug: `app/build/outputs/apk/debug/app-debug.apk`. Raporty: `app/build/reports/`. Schemat Room: `app/schemas/` (należy wersjonować, nie stosować migracji kasujących dane).

## GitHub Actions i pobieranie APK

Workflow [Project CI](../.github/workflows/backend.yml) uruchamia na każdym PR do `main` i zmianie `main` dwa zadania Androida. `android-build` buduje debug APK, wykonuje wszystkie testy JVM i lint; `android-device` wykonuje wszystkie testy instalacji validation na emulatorze Pixel 6 / API 35 / Google APIs / x86_64, z trybem samolotowym oraz wyłączonym Wi-Fi i transmisją danych przed testami. Efemeryczny emulator ma politykę trybu samolotowego niedopuszczającą ponownego włączenia Wi-Fi oraz wyzerowaną zapamiętaną zgodę na Wi-Fi w tym trybie. Stan bez aktywnego połączenia jest sprawdzany przed testami i po nich oraz zapisany w raportach. Profil Pixel 6 odpowiada wcześniejszemu lokalnemu odbiorowi O3 (1080 × 2400, density 420); ten przebieg nie potwierdza wszystkich rozmiarów ekranu ani wersji od minimalnego API 26. Oba wyniki są wymagane przez `ci-required`, razem z backendem i kontraktami. Brak raportów, pominięte testy, błąd albo anulowanie obowiązkowego zadania nie dają zaliczenia. Ostrzeżenia lint pozostają w raporcie; błędy blokują odbiór.

Po zakończeniu przebiegu otwórz jego stronę w GitHub **Actions → Project CI → Artifacts**. Artefakt `android-debug-<commit>` zawiera `Racje-i-kalorie-<wersja>-debug.apk`, `manifest.json` oraz `SHA256SUMS`. Manifest podaje rzeczywisty applicationId, versionName/versionCode sprawdzone także wewnątrz APK, wariant debug, dokładny commit checkoutu i SHA-256 samego APK. Dla PR commit oznacza testowaną integrację z bazą (`refs/pull/.../merge`); commit źródłowej gałęzi znajdziesz na stronie PR. Artefakt powstaje po zaliczeniu JVM/lint; dopiero zielone całe `ci-required` potwierdza również odbiór urządzenia i backendu.

Raporty są w osobnych artefaktach `android-jvm-lint-<commit>` i `android-api35-<commit>`; upload jest podejmowany także po nieudanym teście. APK i raporty mają retencję 14 dni i pozostają poza Git. To dostawa debug do testowania, nie podpisane wydanie produkcyjne ani wdrożenie API. APK nie pojawi się, jeśli jego budowa lub wcześniejsze kontrole nie powiodły się. Pobranie artefaktów może wymagać zalogowania do GitHuba.

Testy JVM są wykonywane i sprawdzane oddzielnie dla debug oraz validation.
Wariant validation obejmuje także testy receipt/gate/proof z `src/testValidation`;
sam wynik debug ich nie potwierdza. Każdy katalog JUnit musi mieć wykonane testy
bez błędów i pominięć. `jvm-summary.json` opisuje debug, a
`jvm-validation-summary.json` validation. Wspólne przypadki uruchamiają się
w obu wariantach, więc ich sumy nie są liczbą unikalnych scenariuszy.

## Kontrole odbioru

1. W trybie samolotowym dodaj produkt z ilością `120,5 g`. Sprawdź kcal i pozycję w wybranej grupie.
2. Zamknij aplikację i otwórz ponownie. Wpis pozostaje.
3. Edytuj ilość, a potem usuń wpis. Bilans i kolejka reagują na obie zmiany.
4. Zmień motyw i uruchom aplikację ponownie. Ustawienie pozostaje.
5. Ustaw nowy cel. Wczorajszy cel pozostaje wcześniejszy.
6. Dodaj produkt bez makr. Kalorie są policzone, a B/T/W pokazują brak danych.
7. Dodaj rację A z 50 g konserwy i 22,5 g sucharów. Pozostałe składniki pozostają niezaznaczone. Wpis ma 222 kcal.
8. Przed zapisem obróć ekran lub odtwórz aktywność: wybór i gramatura pozostają. Pusta lista zaznaczeń i ilość ponad masę opakowania blokują zapis.
9. Edytuj jeden składnik zapisanej racji. Pozostałe nie zmieniają się. Usuń składnik i sprawdź bilans; usuń całą rację po potwierdzeniu.
10. Zainstaluj aktualizację na wersji 0.1.0: stare posiłki, cele i kolejka pozostają.
11. Własny produkt: podaj 100 kcal/100 g, źródło i 150,5 g spożycia, pozostaw makra puste. Dziennik zwiększa sumę o 150,5 kcal, pokazuje brak makr i zachowuje produkt do ponownego wyboru.
12. Zapisz profil, a potem dwa pomiary z tą samą datą. Wpisy pozostają osobne, korekta zachowuje datę, a usunięcie jednego nie usuwa drugiego ani nie zmienia celu kalorii.
13. Oznacz niepusty dzień jako kompletny, zamknij aplikację i otwórz ponownie. Następnie usuń wszystkie jego posiłki: pusty dzień nie jest kompletny mimo wcześniejszej deklaracji.
14. Zainstaluj aktualizację na wersji 0.2.0: składniki racji i wartości historyczne pozostają.
15. W Postępach przełącz 7/30/90 dni i kcal/B/T/W, sprawdź mianowniki średnich, wcześniejsze cele oraz niepełne/puste dni. Otwórz dzień z historii i popraw wpis: wynik po powrocie się aktualizuje.
16. Zapisz kilka pomiarów tej samej daty, popraw lub usuń ostatni. Wykres używa ostatniego dostępnego pomiaru i zachowuje przerwy. Przesuń okres strzałkami i odtwórz aktywność.

Szczegółowy wynik walidacji 0.4.0, zakres prób awarii i ograniczenia odbioru E2: [raport Androida](RAPORT_0_4.md). Testy urządzenia obejmują migracje 1/2/3 → 4, zachowanie historii/kolejki, generacje, niezmienność wersji, rzeczywisty SQLITE_FULL oraz przepływy UI z odtworzeniem aktywności. Pełny odbiór zespołowy KO-30 wymaga również środowiska i dostawy O2/O3; raport lokalny go nie zastępuje.

Wynik etapu analityki i zasady zależnego PR: [raport 0.5.0](RAPORT_0_5.md). Bieżąca migracja i izolacja: [raport 0.6.0](RAPORT_0_6.md); testy obejmują ścieżki 1/2/3/4 → 5.

## Architektura

`MainActivity` tworzy ViewModel i uruchamia Compose. `DiaryViewModel` udostępnia obserwowalny stan. `DiaryRepository` realizuje transakcyjne operacje zapisu, `data/LocalOwners.kt` utrwala właścicieli i chroni zapis przed zmianą aktywnego zakresu. `CalorieDao` jest lokalnym źródłem ekranów. `core/NutritionV1.kt` zawiera dokładne obliczenia, `core/catalog/` walidację pakietu, `data/CatalogStore.kt` staging i aktywację. `ui/` zawiera wspólne motywy i ekrany.

Nie ma uprawnienia INTERNET, kluczy API ani danych konta w APK pierwszej wersji. Dodamy warstwę sieciową wraz z etapem synchronizacji.

[Raport 0.7.3 i testy trybów](RAPORT_0_7_3.md).
