# Źródło przypiętych obrazów CI

13 października 2026, Agent 3. PR44 miał8 rzeczywistych success na a22e6b4,
ale osobny push main408233c/CI38346257152 nie uruchomił testów PostgreSQL:
trzy próbki pobrania obrazu z publicznego ECR zwróciły data-limit/429.
Wcześniejszy quality PR44/1ba miał analogiczny failure przy Python base image.
Nie są to wykonane RED testów aplikacji; failed job nadal blokuje odbiór main.

Zmiana kieruje workflow, integracyjny Compose i trzy własne producenty PG
do `docker.io/library/postgres` / `docker.io/library/python`.
Zachowuje dokładnie dotychczasowe pełne SHA256:

- PostgreSQL: `2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3`;
- Python: `70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f`.

Nie aktualizujemy obrazu, tagu, wersji, platformy, bibliotek lub reguł testów.
Nie zmieniamy migracji0001–0021, pakietu backendu albo istniejących kontenerów.
Rzeczywisty Docker Hub pull obu referencji potwierdził te same digests.
Porównanie lokalnych referencji PG ECR/Hub dało identyczne Id2d2b;
raw manifest Python z Hub ma SHA256 dokładnie70729b, identyczne z pinem ECR.
Pierwszy pomocniczy manifest inspect Python miał TLS handshake timeout;
raw imagetools oraz późniejsze rzeczywiste pulls obu obrazów PASS.
Nie ukryto początkowego błędu połączenia i nie zmieniono digestu, by go ominąć.

Ruff/format/diff-check PASS. Własny istniejący zestaw4 legalnych średnich E8.4
wykonał nowe bootstrap/migracje/HTTP przez producenta Docker Hub:4PASS23,66s,
bez skips i bez zmian oczekiwań. To kontrola dostarczalności/środowiska, nie
nowa niezależna recenzja własnej poprawki lub pełna lokalna regresja.
Pełne1265PG/1658unit/Android/Keycloak/integration pozostają obowiązkowym
CI właściwego final-head/base i późniejszego main; nie są pomijane przy
błędzie registry. Nie dodajemy sekretów logowania do registry lub płatnej usługi.

Narzędzie kopii z odrębnego [PR45](https://github.com/Roseru/aplikacja-mobilna/pull/45)
jest już scalone na10d346d po8success CI38346838325. Dołączono ten main zwykłym
merge na czystym checkout, zachowano O3-014 i dołączono O3-015; wcześniejsza
niepusta historia poza własnym wierszem O3 została sprawdzona jako zachowana.
Narzędzie kopii otrzymuje ten sam alias PG. Nowa rzeczywista offline rehearsal
tej samej pary archiwów z Docker Hub ma własne5 zakresów PASS, bez przypisywania
sobie nowej unikalnej regresji. Historia E8.4 i ECR failures pozostaje zachowana.
