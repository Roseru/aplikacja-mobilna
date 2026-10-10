# Tekst startowy E3 do nowego czatu - osoba 2

Wklej poniższy tekst w nowym czacie tego projektu. Pełna instrukcja jest w [master prompcie E3](MASTER_PROMPT_E3.md). Ten PR publikuje plan i przekazanie; nie zawiera implementacji E3.

```text
Pracujemy jako OSOBA 2 / Agent 2 w repozytorium Roseru/aplikacja-mobilna.
Wykonaj E3 według całego pliku docs/MASTER_PROMPT_E3.md.
Priorytetem jest jakość, czytelna struktura oraz rzeczywiste dowody działania.

Najpierw pobierz aktualny GitHub, sprawdź status/gałąź/remote, przeczytaj
AGENTS.md i aktualną komunikację osób/agentów oraz wymagania i kontrakty.
Nie nadpisuj cudzych zmian. Sprawdź stan PR #4 (E2), #5 (komunikacja)
i PR z tym planem; nie zakładaj, że zostały scalone.

Przygotuj bazę E3 z aktualnego main zawierającego zaakceptowane E2.
Możesz scalić PR #4 po potwierdzeniu wymaganej recenzji innej osoby,
zielonych kontroli aktualnego head i rozwiązania uwag. Nie obchodź workflow.
Jeśli brakuje warunku, zgłoś konkretną zależność O3 i wykonuj niezależną
analizę/przygotowanie; nie przedstawiaj niescalonego kodu jako main.
Komunikację z niescalonego PR #5 czytaj na właściwym commicie,
bez scalenia całej gałęzi O1 dla pojedynczego dokumentu.

Implementuj na osobnej gałęzi codex/backend-e3-tozsamosc-profile.
Używaj subagentów, dobierając reasoning do zadania. Niezależny recenzent
ma odtworzyć istotne scenariusze. Poprawiaj do minimum 9/10 bez istotnych
nierozwiązanych usterek; same mocki nie zamykają integracji Keycloak.

Masz upoważnienie do potrzebnej komunikacji z Agentem 1 / O1
i Agentem 3 / O3: pytania, blokady, zmiany kontraktów i przekazanie wyników.
Korzystaj ze wspólnego dziennika zgodnie z jego zasadami; w razie potrzeby
z dostępnego czatu danego agenta lub komentarza właściwego PR.
Nie potwierdzaj odczytu za innych; komunikacja nie zastępuje recenzji.

Po wykonaniu E3 zrób commit agent 2: <wynik>, push i PR do main.
Zweryfikuj rzeczywiste CI aktualnego head, przygotuj raport i przekazanie O1/O3.
Nie scalaj E3 i nie rozpoczynaj E4 — wynik odbierzemy osobno.
```
