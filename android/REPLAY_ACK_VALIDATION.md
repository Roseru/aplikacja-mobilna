# Bariera przed zapisem ACK — przygotowanie testu E4

Agent 1, 19.10.2026. Gałąź `codex/android-replay-ack` zależy od dokładnego
`9a3a9a9c0cd03817f95cf6f504237288c8998d0c` / [PR129](https://github.com/Roseru/aplikacja-mobilna/pull/129).
To przygotowanie obserwacji, nie nowy APK ani wynik wspólnej próby.
Aktualizacja: [kod trzech faz drivera i neutralny receipt POST](DRIVER_REPLAY_E4.md)
mają osobny lekki odbiór 24 JVM i kompilacji; nadal bez próby urządzenia/API.
[Manifest 0.8.23](ODBIOR_0_8_23.json) opisuje wcześniejsze niezmienne APK
ze źródła `70afd6c`; nie obejmuje nowej bariery.

## Miejsce zatrzymania

`SessionController.synchronizeMeals` wykonuje dotychczasowy transport HTTPS
i niezmienione `MealPushStore.prepareAck`. Dopiero po pełnej poprawnej
odpowiedzi i sprawdzeniu całego DTO wywołuje hook, przed `withApiSession`
i atomowym `applyAck`. Bariera jest więc poza mutexem sesji oraz transakcją
Room i nie wydłuża limitów odczytu/zapisu sieci. Pierwotna partia pozostaje
trwała, attempted=true i bez responseJson. Po zwolnieniu nadal obowiązują
dotychczasowe kontrole bieżącego konta, lease, kontekstu i wersji wierszy.

Poprzedni plan O1-079 rozważał zatrzymanie przed przygotowaniem ACK.
Wybrano punkt **po walidacji DTO, nadal przed trwałym zapisem**, aby wadliwa
odpowiedź nie mogła zostać uznana za osiągnięcie bariery. Nie dodano drugiego
parsera i nie zmieniono zachowania `already_applied`.

## Ograniczenia i sterowanie

- `MealPushAckGate` oraz sterowanie istnieją wyłącznie w source set validation.
  Zwykłe debug/release używają no-op z `ENABLED=false`. Nie ma kontrolki UI,
  odbiornika sieciowego ani automatycznego uzbrojenia.
- Instrumentacja uzbraja dokładny lokalny UUID partii i SHA256 utrwalonych
  bajtów koperty. Inna partia lub hash nie zużywają biletu. Jednoczesne
  uzbrojenie albo próba obejścia już trzymanej odpowiedzi są odrzucane.
- Maksymalny czas hold wynosi **45 s**, od osiągnięcia bariery. Uzbrojenie
  wygasa po **120 s** według zegara monotonicznego; pozostały czas tego
  okresu dodatkowo ogranicza hold. Nie ma bezterminowego czekania.
- Timeout, cancellation i rozbrojenie trzymanej odpowiedzi kończą oczekiwanie
  wyjątkiem, bez dostarczenia przygotowanego ACK. `disarm` starego biletu
  nie usuwa nowego. Timeout nie wyzwala ponownej wysyłki.
- Log zawiera tylko stałą nazwę zdarzenia held/released/expired/cancelled,
  nowy losowy identyfikator próby i UTC. Brak UUID partii, hashy, danych
  konta, URL, body lub tokenów. Awaria loggera nie zmienia decyzji.

Właściwy eksperyment pozostawia bilet w stanie held podczas osobnej
obserwacji PG C1 i rzeczywiście zabija proces aplikacji przed ACK.
`release` służy kontrolowanym testom samej bariery; zwolnienie lub wygaśnięcie
przed przerwaniem nie dowodzi utraty ACK. Nowy proces ponawia zapisane
żądanie przez istniejący transport, bez ręcznej edycji Room.

## Historyczny odbiór pierwszej bariery — 17cddcf

Lekkie testy JVM obejmują dopasowanie konkretnej koperty, one-shot,
blokadę ponownego uzbrojenia, timeout, cancellation, disarm/stary bilet,
TTL, równoległe wejście, redakcję diagnostyki i błędy loggera.
Nie wykonują Room, HTTP, restartu aplikacji ani obserwacji PostgreSQL.
Kompilacja obu wariantów kontrolera jest sprawdzana osobno bez Gradle.
Wynik: **12/12 JVM PASS**, bez błędów/pominięć; wykonanie testów 0,833 s.
Kompilacja bariery/testów 8,81 s, kontrolera standard 17,72 s, validation
18,56 s — wszystkie exit0. Sprawdzono również wynik kompilatora: klasy
kontrolera standard nie odwołują się do MealPushObservation, a validation
zawiera wywołanie. Kompilator używał jednego procesora, limitu heap256 MiB
i obniżonego priorytetu; bez Gradle lub uruchomienia aplikacji.

Wszystkie pięć wejść źródłowych miało identyczne hashe przed/po kontroli.
Pozostałe 256 wcześniejszych wejść zweryfikowano względem zachowanego buildu
0.8.23. Kompilacja kontrolera korzystała z jego wcześniej zbudowanych klas
zależnych; nie jest pełnym buildem aplikacji ani testem uruchomienia hooka
na Room. Log JUnit SHA256:
`54a1dd991379a87cf022398984eb5d92ab425e1524718e814220eebd39560397`.
Plik odcisków źródeł i klas zależnych SHA256:
`abecd0877f0f723aa581d6b2b3d9f78b20d5f68cc3598f24d0ab08260d07c781`.

**Na tym etapie wspólny E4 NOT_RUN.** Pozostawały opt-in driver urządzenia,
neutralny receipt rzeczywistego POST i niezależne dowody Room przed kill/po
restarcie, a także osobny skonfigurowany APK/driver z manifestem i SHA256.
Potem O2/O3 porównują go z używanym obrazem/schema24 i uzgadniają świeże
ograniczone okno. Sam hook i testy JVM nie oznaczają gotowości do startu.
Zachowujemy [oracle O2](https://github.com/Roseru/aplikacja-mobilna/blob/4228ccafdf01a8936dc39bc1964f5d325504ec04/docs/integracja/ODBIOR_R2_R3_ORACLE_E4_O2.md)
i [C0/C1/C2 O3](https://github.com/Roseru/aplikacja-mobilna/blob/c0aef3671d81338c0e5a3ad96aa5f3823b18f34e/docs/integracja/PRZYGOTOWANIE_REPLAY_E4_O3.md).
Nowszy dokument drivera rozlicza przygotowane od tego czasu źródła i nadal
brakujące dowody; nie przypisujemy mu historycznych testów innego źródła.

Podczas gry właściciela bez Gradle, emulatora, instalacji, Gemini lub nowych
połączeń testowych. Nie zmieniono wersji aplikacji, schematu Room ani
dotychczasowych APK. Pełny build i testy urządzenia pozostają osobnym etapem.
