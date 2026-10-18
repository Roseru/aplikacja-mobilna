# Powrót do poprawek po odrzuconej decyzji — 0.8.22

Agent1/O1,19 października2026, gałąź `codex/android-potwierdzenie-posilku`,
[PR122](https://github.com/Roseru/aplikacja-mobilna/pull/122).
Kontynuacja [zatwierdzania0.8.21](POTWIERDZENIE_INTERFEJS.md), zgodnie z
[obsługą konfliktów E7](../docs/e7/INTEGRACJA_O1.md).

## Zachowanie użytkownika

Po409 `proposal_revision_conflict` albo `photo_catalog_choice_changed` użytkownik
wybiera „Sprawdź wynik”. Poprawny odczyt `succeeded/pending` może udostępnić
„Wróć do poprawek”. Dla konfliktu rewizji odczyt musi mieć rewizję wyższą od
odrzuconej decyzji. Powrót wymaga osobnego dialogu; sam odczyt nie odblokowuje
edycji ani nie wysyła nowej decyzji.

Lokalny powrót zachowuje nazwę, dzień, ilości, jednostki, wartości i UUID posiłku
oraz składników. Zwiększa rewizję przeglądu, żeby wcześniejszy dialog nie mógł
zatwierdzić innej decyzji. Nie wysyła HTTP i nie odświeża tokenu, więc działa
także przy wygasłym dostępie, jeżeli zapisany dowód i kontekst konta nadal pasują.
Późniejsze dodanie posiłku wymaga osobnego zatwierdzenia z nowym kluczem.

Utrata odpowiedzi, niepewna decyzja, potwierdzona/anulowana analiza, reuse klucza
i inne niejednoznaczne odrzucenia nie upoważniają do nowej decyzji. Niepewną
wysyłkę nadal ponawia się z identycznym kluczem i body. Dla terminalnej decyzji
obowiązuje odrębne uzgodnienie stanu, nie zmiana zatwierdzonej analizy.

## Trwała historia i atomowość

Room13 dodaje `photo_confirmation_history`. Pierwotny klucz, pełny JSON
odrzuconej decyzji z provenance, analiza, zlecenie, kontekst i czas archiwizacji
pozostają niezmienne. Osobne pola przechowują hash ostatniego poprawnego odczytu
oraz rewizję jawnego powrotu. Brak zdjęć i tokenów w historii. Znane historyczne
klucze nie mogą zostać użyte do kolejnego confirm/cancel.

Odrzucenie i archiwum zapisują się w jednej transakcji. Odczyt i dowód również;
GET rozpoczęty przed odrzuceniem lub odrzucony jako starszy od zapisanego stanu
nie może stworzyć nowego dowodu. Powrót atomowo oznacza archiwalną decyzję jako
zakończony przegląd i zastępuje bieżący szkic. Awaria dowolnego zapisu wycofuje
całość. Lease, pełny kontekst, oryginalny wiersz i historia mają CAS; nowe odczyty,
recovery, logout i A→B→A unieważniają wcześniejsze przygotowanie.

Migracja12→13 tworzy nową tabelę i indeks; nie przepisuje26 wcześniejszych tabel.
Odrzucenia ze starszego Room12 zachowują swój JSON i dostają archiwum przy
pierwszym jawnym poprawnym GET. Nie uznajemy wcześniejszego cache za nowy dowód.

## Odbiór

Kod `39c935f339bc8cd28a360aff5479ddea508c832c`,0.8.22/code33,
validation1033/Room13. Build,313JVMdebug/328validation i lint0error PASS.
252 wejścia buildu mają niezmienione hashe. Niezależny SQLite potwierdził27 tabel,
niezmienione26 starszych definicji i eksporty1–12 oraz zgodne kolumny/indeksy/FK.

17 celowanych przypadków urządzenia API35 PASS,116,963s instrumentacji.
Pełny zestaw **299/299 PASS**,0fail/0skip,464,342s instrumentacji/468,984s
całego przebiegu. Offline przed i po obu odbiorach. Nowe testy obejmują migrację
z26 zapełnionymi tabelami, historyczne odrzucenie bez archiwum, stare GET,
powrót po restarcie bez przygotowanego obrazu, trzy błędy transakcji, późny ACK,
ponowne zatwierdzenie z zachowaniem ID, blokadę historycznych kluczy,
nowe odczyty/zmianę kontekstu/A→B→A oraz jawny dialog z wygasłym dostępem.

Rzeczywista aktualizacja zwykłego APK przez install-r12→13 zachowała wszystkie
26 starych tabel/kolumn/wartości i rowid pozycji przed instalacją, po instalacji
oraz po pierwszym uruchomieniu. FK bez błędów, nowa27.tabela historii pusta.
Przed kopią kontrolną uruchomiono starą0.8.21 na bieżącej dobie, oddzielając jej
normalną inicjalizację dnia od migracji. Pierwsze obserwacje zimnych startów nie
zastały jeszcze gotowych kontrolek; ANR nie było. Kolejne obserwacje tego samego
procesu bez relaunch potwierdziły gotowy interfejs. Aplikacja0.8.22 pozostaje
otwarta do testów. Surowe kopie bazy/UI są prywatne poza Git/OneDrive.

## Artefakty

APK są lokalnymi niezmiennymi artefaktami, poza Git:

| Artefakt | SHA-256 |
|---|---|
| debug0.8.22 | `83b0676d4353cecb6ba44385fb26ee6725066ffa186119bd227e776db98d1550` |
| validation0.8.22 | `02ba81bee9c0f54d6954792a55cdb1501202854798e0e0c1138aa1b465b14376` |
| domyślny test APK | `d02d0482824b1a7e7382f9fc841e5e9c36a9b8dc13be0dbdbd721d89fb2e588b` |

Log17 SHA: `0590da8001961fdedc422e17e22ba1d9013972ee568be66be2f88357d960247f`.
Log299 SHA: `d4aac0b06705c72130ccb2ecd87a3e7a685d854a9af9a3314f1ee27fece0a72b`.
Domyślny test APK nie zawiera drivera rzeczywistego API; zwykły debug nie ma
obserwatorów walidacyjnych. Artefakty i zainstalowane APK zweryfikowano hashami.

Nie jest to odbiór rzeczywistego APK/API, Gemini ani całego E4/E7/KO32.
Transport push/pull, legacy, pełne recovery i retencja historii pozostają
osobnymi zadaniami. Nie zmienia się protokół serwera ani używana instalacja O3.
