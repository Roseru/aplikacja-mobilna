# Przejęcie zadań Androida O1 przez Agenta 2

Stan: **26.10.2026, przekazanie na jawne polecenie właściciela**. Autor: Agent 1.
To instrukcja wykonania i mapa źródeł, nie drugi dziennik wyników.
Trwałe decyzje i ACK zapisujemy nadal w [jedynym dzienniku](KOMUNIKACJA_AGENTOW.md),
bieżące pytania w uzgodnionym pokoju, a przy braku narzędzi w
[PR146](https://github.com/Roseru/aplikacja-mobilna/pull/146).

## 1. Co dokładnie przejmujesz

Właściciel poprosił, aby Agent 2 mógł przejąć zadania Agenta 1.
O2 dostaje **cały bieżący etap MRE 0.8.40**, jego integrację i odbiór,
a następnie dalsze braki Androida do 1.0 opisane poniżej.
O2 nadal podpisuje własne commity `agent 2: ...`.
O1 po publikacji tego przekazania **nie edytuje równolegle przekazanych źródeł**.
Nie uznajemy samej dostawy za ACK O2; potwierdź pin, własną gałąź i zakres.

Przeczytaj przed edycją: [AGENTS](../AGENTS.md),
[wymagania](../WYMAGANIA_PROJEKTOWE.md), [workflow](WORKFLOW.md),
[dotychczasowy pakiet O2](ANDROID_O2_PAKIET_PRAC.md),
[opis MRE](../android/MRE_2026.md),
[materiały MRE](../Random%20Data/MRE/README.md).

Źródło przekazania: gałąź **`codex/android-mre-2026`**, rodzic
`c1c8380285d19f84acbbf19a734b86198036dfe7` (scalony PR187).
Dokładny commit przekazania podaje wiadomość O1 w PR146 po pushu.
Manifest [plików](PRZEKAZANIE_O1_DO_O2_PLIKI.json) zawiera SHA-256 bajtów wersjonowanych w Git (blob), przed lokalnym przeliczeniem LF/CRLF.
**MRE nie było jeszcze kompilowane, lintowane ani uruchamiane w JVM/emulatorze.**
Commit przekazania zabezpiecza niedokończoną pracę; nie jest wydaniem lub PASS.
Nie ma PR MRE. Jeden duży PR utwórz po domknięciu i sprawdzeniu etapu.

## 2. Rozpoczęcie bez kolizji

1. Sprawdź własny status/branch/remotes, nowe wiadomości i otwarte PR-y.
2. Pobierz `origin/main` i gałąź przekazania. Nie nadpisuj lokalnych zmian.
3. We **własnym checkoutcie** utwórz `codex/android-o2-mre-2026` z konkretnego
   commita przekazania. Nie pracuj w checkoutcie O1 ani na jego branchu.
4. Zapisz ACK pina i przejęcie rezerwacji w jedynym dzienniku/PR146.
5. Z czystego checkoutu zwykłym merge dołącz aktualny main. Zachowaj oba
   końce dziennika. Nie rebase/force-push, nie przenoś innych niescalonych PR.
6. Po złożeniu całości wykonaj ograniczony odbiór z rozdziału 5 i napraw
   rzeczywiste błędy. Dopiero potem PR do main, wymagane CI, merge i osobny
   odbiór main. Wynik poprzedniego head nie kwalifikuje nowego drzewa.

Ostatni odczytany main: `59a68fc94a44c510763f21cdbfefc603a4565fe2`
(PR177, zależności backendu; źródło O2-067 i komentarz6425078747).
Kolejka O3 obejmuje PR183/186/185/184; PR183 odświeża swoją bazę po177.
Nie przejmuj tych gałęzi lub main.lock; koordynuj tylko krótki slot merge.
Android dependencies PR176/82 to niezależny zakres, nie dorzucaj go do MRE.

## 3. Stan implementacji MRE

Złożono kod, dane i testy, lecz **nie wykonano odbioru funkcjonalnego**.
Wersja robocza Androida: `0.8.40`, code51, validation1051.
Room pozostaje **27 / 55 encji**, brak nowej migracji.

Pakiet MRE jest **osobny**, `kind=demo`, release1:

| Wartość | Pin |
|---|---|
| package_id | `3aa9b766-b01d-5111-8fd0-4c5b6257961b` |
| źródło DLA | `304728b1-c81a-536f-9b95-7b70836cd3c3` |
| produkty / racje / komponenty / źródła | 111 / 24 / 235 / 112 |
| source.json SHA-256 | `f519ef7390287c06293e7d45ff65371d5fa5cc68565994c948baebd2b0c2ad94` |
| payload SHA-256 | `f32b25aa525d3644c872ce4a76baeb5d4383628242ef52b06f9210bd1f24babc` |
| gzip SHA-256 | `a5f25f04d47375347b096b51bf3ba556cd11fa13ce703e658f48b3148314e77f` |

Stary E2 DEMO1 pozostaje osobno i bez zmiany: 18 produktów / 1 racja.
Z 15 produktami i 2 racjami legacy oczekiwana całość aplikacji to
**144 produkty / 27 racji**. Wcześniejsza koncepcja rozszerzenia DEMO do
release2 została wycofana przed przekazaniem. Nie wracaj do niej przez
stare notatki, nie kopiuj poprzednich hashy lub łącznych liczb129/25.

### Mapa kodu i rezerwacja przekazywana O2

- `tools/catalog/build_mre_2026.py`: Decimal, UUIDv5, gzip mtime0;
  źródła `Random Data/MRE` pozostają nietknięte. Kopia w APK ma LF.
- `android/app/src/main/assets/catalog/mre2026/`: manifest, gzip `.bin`,
  źródło i reguły związane z hashem/release/revizją racji. Lokalny
  `.gitattributes` stabilizuje hashe między Windows/Linux.
- `core/catalog/MreRationSelection.kt`: walidacja związania reguł,
  wzajemnie wykluczające warianty, pakiet zbiorczy kontra szczegóły,
  Decimal ręcznej ilości i odżywienia. Brak danych nie jest zerem.
- `data/MreCatalogueAssets.kt`: wspólny czytnik E2 z osobnym package_id,
  ograniczenia rozmiaru, Loading/Ready/Unavailable, bez cichego uznania
  błędu MRE za sukces.
- `data/DiaryRepository.kt`: import MRE, repozytoryjny guard wariantów,
  ręczny niepotwierdzony składnik; atomowy posiłek i outbox, owner lease,
  osobne ścieżki gość/legacy oraz konto/sync-v1. Nowe czasy w mikrosekundach.
- `DiaryViewModel.kt`: stan katalogu, zapis nieznanego składnika,
  sygnał sukcesu zachowujący ekran racji i pozostałe zaznaczenia.
- `ui/RationScreen.kt`, `MreReferenceDialog.kt`,
  `MreUnknownIngredientDialog.kt`: porcje, warianty, wszystkie pola źródła,
  osobny wpis ręczny, wykluczenie sprzętu niejadalnego.
- `catalogupdate/CatalogUpdateRepository.kt`, `ui/CatalogUpdatePanel.kt`,
  `ui/CatalogSourcesDialog.kt`, `ui/App.kt`: rozpoznanie i wyświetlanie
  osobnego MRE DEMO bez poszerzania kanału official aktualizacji HTTPS.
- `android/app/build.gradle.kts`: wyłącznie wersja etapu.
- Nowe testy `MreRationSelectionTest`, `MreCatalogueFlowTest`,
  `MreRationScreenTest`; istniejące fixture katalogu w CatalogStorage,
  CatalogUpdateScreen, DiaryStorage, OwnerStorage i RationStorage.
- Dokumenty tego przekazania, `android/MRE_2026.md` oraz własne wpisy
  w jedynym dzienniku. Inne pliki dobieraj tylko do realnej poprawki,
  respektując bieżące rezerwacje O3 i pozostałych wykonawców.

### Zachowania, których nie wolno uprościć

- Warianty nie są sumą; cake w menu9 wymaga pojedynczego wyboru.
- Zaznaczenie zbiorcze omija niejednoznaczne warianty i średnią pakietu.
  Starsza średnia dodatków B nie sumuje się z ich szczegółami.
- Profil odniesienia z `reference_profile_ids` nie staje się automatycznie
  dopasowaniem składnika. Braki i niepewności pozostają widoczne.
- Ręczny brakujący składnik wymaga rzeczywistych gramów; wartości/100g
  mogą pozostać null. Jawne0 jest znaną wartością. Brak kcal utrzymuje
  niekompletność dnia. Ręczny wpis nie tworzy publicznego produktu.
- Zapis ręcznego składnika nie kasuje pozostałych zaznaczeń racji;
  wyłącza ewentualną średnią dodatków. Znane składniki mają stare reguły
  snapshotów, korekty ilości i identyfikatory.
- Konto, gość, zmiana właściciela i rollback posiłek/outbox zachowują
  dotychczasową izolację. Nie zamieniaj błędu importu na udany status.
- Wszystkie MRE są referencyjne/niepotwierdzone. Nie oznaczaj ich
  official lub complete w celu przejścia czytnika.

## 4. Co już zamknięto i czego te wyniki nie potwierdzają

[PR187](https://github.com/Roseru/aplikacja-mobilna/pull/187) scalony:
head `1f6ffbc5292c31c8d243701eaa5a16ba17efe07a`, merge `c1c8380`.
FULL PR40357700293 i niezależny main40361951765: **wszystkie8 SUCCESS**,
odczytane przez O1. Wyniki dotyczą trwałych podglądów offline0.8.39,
nie nowego MRE. Historyczne17FAIL oczekiwań wersji26→27 poprawiono;
nie ukrywaj ich w opisie historii, raport ma zakresy i wcześniejsze SHA.

Nie cofaj zintegrowanych etapów O2 A/B/C, runtime, ETag, PULL,
zarządzania archiwami, kalkulatora celu lub podglądów offline.
Ich implementacja nie oznacza jeszcze końcowego live odbioru1.0.

## 5. Domknięcie MRE — najbliższa kolejność

1. Przeczytaj całość delty i dokończ implementację; nie uruchamiaj serii
   drobnych testów po każdym pliku. W razie błędu kompilacji napraw go,
   nie deklaruj go jako wykonany PASS.
2. Po złożeniu uruchom generator do osobnego katalogu i porównaj bajty
   czterech artefaktów z dostawą. Zweryfikuj brak zmiany źródeł Random Data,
   starego DEMO i schematów Room1–27. Nie publikuj prywatnych lokalizacji.
3. Jeden build etapu: assembleDebug, assembleValidation,
   assembleValidationAndroidTest, lintDebug i **4 metody** klasy
   `pl.roseru.kalorie.MreRationSelectionTest` przez testDebugUnitTest.
   Wariant debug/validation zachowuje ustawienia projektu.
4. Native ograniczone do realnego zakresu etapu: nowe MreCatalogueFlow3
   i MreRationScreen1, RationStorage3, oraz po jednym:
   DiaryStorage.restartPreservesSnapshotAndOutbox;
   OwnerStorage.guestAndTwoAccountsKeepPrivateDataAnalyticsAndQueuesSeparate;
   OwnerStorage.sharedRationCatalogKeepsConsumedAmountsAndSnapshotsPrivate;
   CatalogStorage.partialRationKeepsExactSnapshotsAndQueueThroughCatalogUpdateAndEditing;
   CatalogStorage.actualSqliteFullDuringStagePreservesPreviousCatalogDiaryAndOutbox;
   CatalogUpdateScreen.guestCanInspectSourcesWhileBlockedThenExplicitlyEnableAndDownloadWithoutDiaryMutation.
   To plan **13 przypadków**, nie wykonany wynik. Potwierdź aktualne
   nazwy/metody runnerem i nie zaliczaj pominięć jako sukcesu.
5. Przydziel własne applicationId/testApplicationId i sprawdź je w APK
   PRZED instalacją. Nie instaluj MRE nad oryginalnym profilem lub Room23.
   Jeżeli pracujesz na innym komputerze, utwórz własny profil testowy.
6. Sprawdź źródła/ilości w UI offline: menu1 częściowa porcja,
   menu9 zmiana wariantu, ręczne gramy z pustymi kcal, restart,
   źródła MRE i brak utraty wyboru. Błędy poprawiaj w tym samym etapie.
7. E0 kontraktów/linków, `git diff --check`, przegląd źródeł i wyników;
   potem jeden duży PR. Opisz brak zmiany API/Room i nieoficjalność danych.
   Zdalne wymagane CI i osobny main odczytaj rzeczywiście po publikacji.

Testy napisane używają assets względem `src/main/assets/catalog`;
przy FileNotFound sprawdź workingDir JVM, nie przenoś danych produkcyjnych.
W fixture outbox prawdziwe pola to `wireFormat`, `wireJson`, `payload`;
kolumna SQL to `payload`. Konta native są syntetyczne, nie dowodzą PKCE.
Nie powtarzaj pełnych554 native lokalnie bez nowego uzasadnienia;
obowiązkowego CI całego PR nie wyłączaj.

## 6. Dalsze zadania do 1.0 po MRE

**Najpierw zamknij duży rozpoczęty etap, potem następną całość.**

1. Oficjalny seed z wymagań11.4: ARPOL WZ1/WZ4 WEGE i podstawowe produkty
   z weryfikowalnymi źródłami/FDC/etykietami. MRE nie zastępuje tego braku.
   Zachowaj stałe ID, jednostki i niepewne dopasowania. Nie wdrażaj
   referencji nowych produktów do backendu w oknie zamrożonego E4.
2. Zgraj z backendem ten sam niezależny pakiet MRE przed testem synchronizacji
   jego nowych publicznych referencji. Czytnik/importer backendu ma parametr
   expected package/kind; potwierdź faktyczny import i zgodność, nie zmieniaj
   publicznego kontraktu tylko po to, by zastąpić brak danych.
3. Odbiór skonfigurowanej aplikacji z O3 według rozdziału7. O1 na razie
   pozostaje umówionym operatorem fizycznego stanowiska; O2 może prowadzić
   przygotowanie i poprawki. Zmiana operatora wymaga jawnego uzgodnienia,
   żeby nie uruchomić dwóch prób na tym samym profilu.
4. Po acceptance osobny live E4 z prywatnym prepared.json i związaniem
   trial/Meal/operation/account/epoch, dowody PG przed/po oraz niezależny
   odbiór O3; **PULL jest oddzielnym kolejnym zakresem**, nie domyślnym PASS.
5. Gemini: backend jest jedynym posiadaczem klucza. Sprawdź faktyczną
   konfigurację i Free Tier przed realnym rozpoznaniem; nie dodawaj klucza
   do APK/commita i nie zakładaj, że wcześniejszy screenshot lub test modelu
   potwierdza cały przepływ zdjęcie→korekta→zapis→deduplikacja.
6. Końcowa macierz wymagań: konto offline/gość, zmiana konta, 7/30/90,
   cele i waga, osiągnięcia/ranking/Nemesis, community, zdjęcia, konflikty,
   30dni offline i wznowienie. Ustal faktyczny brak z kodu/raportów;
   nie przebudowuj działających funkcji na podstawie samej tej listy.
   Przy końcu dostarcz konkretny APK/commit/SHA, raport i plan demo O3.

Zachowaj zaakceptowany wygląd: analityka jak dotąd, mniejsze podsumowanie
osiągnięć i więcej odznak, zagęszczona lista rankingu. Klasy to
„Etat biurowo-kawowy”, „Liniowa”, „Komandos”, z ikonami i wpływem na cel.

## 7. Zamrożona dostawa Room23 — osobny zakres

Nie zastępuj jej kodem MRE/Room27. Źródło dostawy
`2319357d06da47af818f2b891bc1efbde486b734`, źródło kodu
`eacc8f192ed9c9cd5c8e45e38f44385b18b6774d`, Android tree
`0c83ee386de48335a49ac3061523befcfe1de073`.
0.8.35/code46/validation1046, Room23/49 encji,
identity `d8e3ed92a9b0fd8af6cc2e57fc644687`.

[ZIP czterech APK](https://github.com/Roseru/aplikacja-mobilna/releases/download/integration-handoff-20261014/O1-Room23-0.8.35-four-apks-2319357-20261026.zip):
48 976 465B, SHA-256 `6efcae4fa9c4eb881b44edf320fbbcabd2ace9f6405d0ee528013d9272160f0b`.
Manifest: `3e15eb0ad4a657a9f6ead4137c2a55e09f6e95d25d7c0dd4d0289470b072fcc1`.

| Rola | SHA-256 APK |
|---|---|
| debug | `e99a7ef881c0c484715b2aad5efd89208ccb5a965436a9a7500a7d9f588474a7` |
| validation | `aa764a6db26e006de85b1561cc5788fa859b1123ad55fcd7d5bc2fe77c56d684` |
| default test | `6e57c4852afe92aaf865c5d748f1e5ea5cf5a3938a5c96aa50aadabc6b936c83` |
| opt-in test | `3fcdb95d3e6ac5dd56391390f43b28c1d52aeef3b7dd8d3a5a038d580553ff09` |

STATIC47 odebrane także niezależnie przez O3. Na własnym odseparowanym
AVD O1Room23Accept35/emulator5566 wykonano jedynie OFFLINE_CLIENT_SMOKE:
4 role zainstalowane/sprawdzone, oba APK uruchomione, Banan120g/107kcal
i1pending przetrwały force-stop oraz cold start. Receipt
`336a48085c60a0db69ae93628ff3a5567ff0f699db47caf3a50332538c30ceda`.
**android_acceptance NOT_CREATED, live_trial NOT_RUN.**
Zainstalowany opt-in nie oznacza uruchomionego drivera.

Oracle: [odbiór APK/API](integracja/ODBIOR_APK_API_O2.md), linie219–291.
O3-108 doprecyzował6425740295: istniejący neutralny szablon można wypełnić
ręcznie po prawdziwej próbie; brak generatora nie blokuje. Potrzebne
browser/PKCE A, bootstrap/me/motivation200, kontekst/no-store,
baseline Room+WAL **po bootstrapie**, brak implicit push/import/consent,
logout/restart/B→A/izolacja/freshGET. Minimalny PASS i extended/late_response
oddzielnie; late_response wymaga rzeczywistej kolejności held/release/guard.
Wynik konkretnego validation APK nie kwalifikuje regularnego APK.

O3-109 jest właścicielem transportu i cleanup, O3-108 niezależnym odbiorcą.
Rzeczywisty prywatny routing R1 dotarł26.10, O1 potwierdził odbiór w
[6425822596](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6425822596).
Nie jest to potwierdzenie łączności lub rozpoczęcia próby. Aktualne parametry,
kontakty, konta, CA i sekrety pobieraj prywatnie, nie z tego dokumentu.
Nie kopiuj ich do GitHuba ani nie podstawiaj adresu transportu za issuer.

## 8. Ograniczenia stanowiska i wznowienia

Właściciel zabronił restartu komputera bez osobnej zgody. Nie kasuj danych
oryginalnej aplikacji, nie wipe emulatora, nie rób reinstall nad jego profilem.
Nie publikuj surowych DB/WAL, logów z tokenami, SDK paths lub kont.
Przy braku UI/MCP nie podpisuj wiadomości jako zalogowany Kamil/Benek/Johnny.
W sesji O1 CUA kończy się błędem inicjalizacji kernel assets/os error3,
narzędzia pokoju nie są dostępne. Metadata otrzymano prywatnie; sama ich
znajomość nie jest zgodą na zmianę audience/roli lub obchodzenie logowania.

Właściciel polecił zatrzymanie pracy przy **3% pozostałego limitu Codex**,
z checkpointem i powrotem po rzeczywistym odnowieniu. Odczytaj narzędzie
usage limits; nie utożsamiaj tego z rozmiarem kontekstu. Nie uruchamiaj
drugiego wykonawcy nad zarezerwowanymi plikami po odnowieniu limitu.
Lokalne środowisko O1 i prywatne receipt są w jego niewersjonowanym
checkpointcie `.tooling/o1-work-state.json` głównego workspace; O2 na innym
komputerze nie zakłada dostępu do tych plików i nie potrzebuje sekretów O1
do ukończenia MRE. Nie ma aktywnego builda MRE do przejęcia.
