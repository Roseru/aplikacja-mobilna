# Android 0.7.1 — odbiór poprawek i bootstrapu

Agent 1 / O1, 10 października 2026 r. `codex/android-bootstrap-cele`, [PR #9](https://github.com/Roseru/aplikacja-mobilna/pull/9); Android versionCode 8, Room 6. Gałąź zawiera bootstrap i niezmienne cele z 0.7 oraz zwykłe merge poprawionych zależności #1/#6/#7. Szczegóły mechanizmu bootstrapu pozostają w [przekazaniu E3](INTEGRACJA_E3.md) i [raporcie 0.7](RAPORT_0_7.md).

## Wynik

- Naprawa #1 znajduje się w jego własnym zakresie: kompletność wymaga znanej energii każdego składnika. Znana dolna granica nie daje kompletnego dnia. Deklaracja pozostaje w historii, ale dopisanie nieznanej energii natychmiast cofa efektywną kompletność.
- Naprawa #6 oddziela bieżący wynik wstępny od średnich i liczników zamkniętych dni. Odczyt odświeża się po kalendarzowej północy w bieżącej strefie urządzenia, z DST i bez dopisania operacji kolejki. Domyślne okno podąża za dzisiaj; jawne historyczne okno odtwarza się i pozostaje stałe. Wznowienie subskrypcji odczytuje aktualną datę; ręczna zmiana czasu/strefy przy aktywnym ekranie jest wykrywana najwyżej po minucie. UI oznacza wynik wstępny i grupuje etykietę/liczbę dla dostępności.
- Połączenie z #7 zachowuje zakres właściciela wszystkich odczytów oraz kontrolę lokalnych zapisów. W #9 niezmienne wersje celów nadal rozstrzygają kolejność tego samego dnia przez lokalną sekwencję i ID. Trwały bootstrap nadal odrzuca stare/konfliktujące odpowiedzi i wymaga uzgodnienia E4 po zmianie kontekstu serwera.
- Room pozostaje 6. Nie dodano sieci, OIDC ani automatycznego przypisania gościa. Ustalony callback jest parametrem przyszłego klienta; nie jest zaimplementowanym handlerem APK.

## Dowody

| Zakres | Końcowy pełny wynik autora |
|---|---|
| PR #1, Android 0.4 / Room 4 | 40 JVM, 28/28 urządzenia |
| PR #6, Android 0.5 / Room 4 | 57 JVM, 36/36 urządzenia |
| PR #7, Android 0.6 / Room 5 | 57 JVM, 44/44 urządzenia |
| PR #9, Android 0.7.1 / Room 6 | **65 JVM, 52/52 urządzenia** |

Każdy powyższy zestaw obejmuje assembleDebug, testDebugUnitTest, lintDebug i connectedValidationAndroidTest na API 35; zero końcowych failures/errors/skips. Lint końcowej wersji: 0 błędów / 26 ostrzeżeń / 1 informacja. Nowe scenariusze czasu obejmują zegar/strefę, północ, DST 23/25 h, ponowne otwarcie bazy, odtworzenie ViewModel/okna, UI przed/po północy oraz niezmieniony outbox. [Raport poprawek](POPRAWKI_REVIEW.md) opisuje wcześniejsze niepowodzenia i ponowienia. Końcowe 52/52 to jeden pełny przebieg, nie suma selektywnych prób.

Porównano źródła/fixtures/schematy publikacyjnego checkoutu z budowanym workspace; po normalizacji końców linii tekstu brak różnic, binaria porównano hashem. Migracje 1/2/3/4/5→6 pozostają w pełnym zestawie. Wcześniejsza fizyczna aktualizacja 0.6→0.7 zachowała wszystkie stare kolumny 16 tabel.

Końcowy APK zainstalowano jako aktualizację 0.7→0.7.1. Porównanie wszystkich kolumn 18 tabel Room 6 przed/po zachowało dziennik, właścicieli, metadane i całą kolejkę; foreign_key_check pusty. Uruchomiono Dziennik bez sieci; versionCode 8 / 0.7.1. Testy korzystają z oddzielnej instalacji validation i nie kasują zwykłego dziennika.

APK poza Git: `output-apk/Racje-i-kalorie-0.7.1-debug.apk`, SHA-256 `2e46bd29affce2973bdc5e0c092969b409638b0e39a9127d8d7f0f2f8d4486ff`. Raporty lokalne: `app/build/test-results/`, `app/build/reports/`, `app/build/outputs/androidTest-results/`.

## Publikacja i dalszy odbiór

Zachowano równoległe zmiany dokumentacji O3 i aktualny main `e8d1051`, bez force-push. Odczytano O3-003/O3-004 oraz plan E3 po porządkowaniu `46046c1`. Wspólny dziennik nadal ma jeden uzgodniony format; usuniętych przez autora sekcji nie odtwarzamy.

Wyniki autora nie zamykają REQUEST_CHANGES ani nie zastępują review innej osoby i rzeczywistego CI Androida. Nie scalono własnych PR-ów. Odbiór #1 → #6 → #7 → #9; po scaleniu wcześniejszego retargetujemy kolejny na main i sprawdzamy integrację. Testy powyżej dotyczą gałęzi zależnych przed tym przyszłym odbiorem.

Następny etap O1: potwierdzona sesja i odtwarzanie ViewModel, HTTP/bootstrap oraz chronione odczyty na wdrożonym E3, następnie adapter E4/Decimal/revisions, pełne klucze encji z właścicielem i WorkManager. O2 dostarcza E3/E4; O3 konfigurację środowiska, mobilne CI i artefakty. Obecny outbox nadal nie jest wysyłany. Import gościa wymaga jawnej zgody i trwałego potwierdzenia; nie wykonano go automatycznie.
