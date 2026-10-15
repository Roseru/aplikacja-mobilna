# Odbiór automatycznego utrzymania O3 — 15.10.2026

Źródła: `codex/devops-lokalne-utrzymanie`, runtime `00c1b7b`.
Stan lokalny jest oddzielny od przyszłego CI i scalenia tej gałęzi.

## Wykonane

- Zainstalowano trzy zadania Windows: start po zalogowaniu, backup o03:00/15:00
  z catch-up oraz niezależne recovery co minutę. Pythonw, uprawnienia zwykłego
  użytkownika, bez okien konsoli. Runtime jest prywatną kopią zatwierdzonych źródeł.
- Akcję startup uruchomiono rzeczywiście z harmonogramu o16:52:19 CEST:
  LastTaskResult0 i receipt PASS. Nie przeprowadzano logout/reboot użytkownika.
- Kontrolowany dodatkowy klient PostgreSQL spowodował odmowę backupu;
  wszystkie pierwotne usługi wznowione, receipt FAIL, recovery_pending=false.
- Po zapisie dziennika i zatrzymaniu API proces zakończono przymusowo.
  Oddzielne zainstalowane zadanie recovery samodzielnie wznowiło ten sam kontener
  i potwierdziło gotowość. Nie tworzono kontenerów zastępczych ani kont.
- Ręczny pełny przebieg: capture/weryfikacja/resume/rehearsal PASS; restore13,732s.
- **Rzeczywisty pełny przebieg zadania backupu 16:57:06–16:57:43 CEST:**
  LastTaskResult0, capture/integrity/resume/rehearsal PASS; restore11,795s.
  Obie bazy/globals/katalog/konfiguracja są w prywatnej kopii.
- Pliki konfiguracji/env/TLS/realm/credentials, epoka, fingerprinty kont aplikacji
  i tożsamości Keycloak oraz identyfikatory oryginalnych kontenerów zgodne przed/po.
- Retencja14 poprawnych kopii; usuwa wyłącznie własne zweryfikowane podkatalogi.
  Ręczne i niepełne kopie pozostają zachowane. Minimalny wolny dysk2GiB/10%.
- Monitor ma oddzielne sensory local_backup/startup; lokalna kopia nie zmienia
  statusu offsite. Brak, FAIL, niepełny receipt lub wiek ponad24h wywołują alarm.
- Kontrolowana próba starego receipt: dwie awarie otworzyły
  [testowy alert106](https://github.com/Roseru/aplikacja-mobilna/issues/106),
  poprawny pomiar zamknął go; oba stany potwierdzone osobnym GET z GitHuba.
  Rzeczywiste sensory local_backup/startup poprawne, pełny zestaw114testów PASS.

Pierwszy przebieg zadania backupu o16:54 zakończył się FAIL przed capture,
podczas gdy ten sam runner ręczny przeszedł. Instalator początkowo zapisywał
logiczną ścieżkę LocalAppData z kontekstu aplikacji. Wpisano fizyczną ścieżkę
rozwiązaną przez Python; powyższy pełny przebieg harmonogramu potwierdza poprawkę.
Wynik nieudany pozostaje w historii, nie jest przypisywany jako PASS.

Testy regresji obejmują błędny capture/restore, wznowienie usług, zachowanie
dziennika po błędzie recovery, obcy projekt, prawdziwą blokadę między procesami,
zwolnienie blokady po zabiciu jej właściciela, odizolowany entrypoint Windows,
retencję i niepoprawne/stare receipts. Pełny wynik i CI są w PR.

## Dalej

[Instrukcja operatora](../../infra/integration/UTRZYMANIE_LOKALNE.md) opisuje
instalację, wyłączanie harmonogramu na rollout/test O1 i diagnostykę prywatną.
Nie przeprowadzono rzeczywistego ponownego logowania lub restartu komputera.
Nie ma jeszcze offsite, publicznego serwera ani docelowego RPO/RTO. Pełny KO17/32
wymaga niezależnego rejestru usunięć, unieważnienia sesji i próby telefonu O1/O2.
AI oraz finalizer pozostają odpowiednio niewdrożone i świadomie wyłączone.

Szczegółowe receipts, ścieżki i fingerprinty pozostają poza Git. Raport nie
potwierdza odbioru APK za O1 ani odbioru reguł/recovery za O2.
