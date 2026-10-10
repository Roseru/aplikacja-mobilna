# Zasady tablicy komunikacji agentów

Ten dokument jest stałą instrukcją zespołu. Zmieniaj go tylko na wyraźną prośbę właściciela projektu. Na komputerze, na którym powstał, plik jest oznaczony jako tylko do odczytu.

## Cel i pliki

- [`TABLICA.md`](TABLICA.md) to wspólny, chronologiczny czat Agentów 1, 2 i 3. Tu zgłaszamy odkryte problemy, niejasności, decyzje i wynik ukończonego zadania. Istotną informację z tablicy utrwal też w odpowiedniej dokumentacji lub kodzie; sama tablica nie zastępuje źródła prawdy projektu.
- Każdy agent ustala własny numer ze swojego **lokalnego pliku tożsamości poza repozytorium**. Pliki tożsamości nie są częścią tej tablicy i nie trafiają do GitHuba. Nie przypisuj sobie numeru na podstawie wpisów innych agentów.

## Jak pisać

1. Przed pracą pobierz aktualne zmiany z GitHuba i przeczytaj nowe wpisy. Przy kończeniu zadania ponownie sprawdź tablicę.
2. Dodawaj wpisy **na końcu** `TABLICA.md`. Nie zmieniaj ani nie usuwaj cudzych wpisów. Jeśli wcześniejsza wiadomość jest błędna, dopisz sprostowanie z odnośnikiem do niej.
3. Każdy wpis zaczyna się nagłówkiem `## RRRR-MM-DD — Agent N — typ`, np. `WYKONANE`, `UWAGA`, `PYTANIE`, `BLOKADA`, `ODPOWIEDŹ`. Treść zaczyna się od `**Agent N:**`. Podaj adresata, jeśli wpis jest do konkretnej osoby, oraz link do pliku, zadania, PR lub commitu, jeśli pomaga zrozumieć sprawę.
4. Pytanie lub blokada powinny mówić, co zostało sprawdzone i jakiej odpowiedzi potrzeba. Odpowiedź dodaj jako nowy wpis na końcu i wskaż, do którego pytania się odnosi.
5. Po ukończeniu zadania dodaj krótki wpis: co się zmieniło, gdzie to znaleźć i czy coś pozostało do zrobienia.
6. Przed wypchnięciem wpisu pobierz najnowsze zmiany. Jeśli równoległe dopisanie wywoła konflikt Git, zachowaj **oba** wpisy w kolejności i dopiero wtedy wypchnij. Nigdy nie używaj force-push do rozwiązywania konfliktu tablicy.
7. Nie wpisuj sekretów, tokenów, prywatnych danych użytkowników ani długich logów. Pilne blokady zgłaszaj również właścicielowi projektu bezpośrednio; tablica nie daje powiadomień na żywo.

Wpis jest widoczny dla innych komputerów dopiero po wypchnięciu na GitHuba i pobraniu zmian przez pozostałe osoby. Odczytanie pliku nie oznacza automatycznie, że adresat przeczytał wiadomość.
