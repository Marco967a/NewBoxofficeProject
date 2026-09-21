# NewBoxofficeProject

Pipeline Python per raccogliere i dati settimanali del box office italiano da
[ComingSoon.it](https://www.comingsoon.it/cinema/boxoffice/), arricchire i film
tramite TMDB e salvare i dati in PostgreSQL.

## Indice

- [Funzionalità](#funzionalità)
- [Architettura](#architettura)
- [Prerequisiti](#prerequisiti)
- [Configurazione](#configurazione)
- [Sicurezza e credenziali](#sicurezza-e-credenziali)
- [Installazione](#installazione)
- [Esecuzione](#esecuzione)
- [Test e Continuous Integration](#test-e-continuous-integration)
- [Schema dati](#schema-dati)
- [Cronologia del progetto](#cronologia-del-progetto)
- [Limitazioni e prossimi passi](#limitazioni-e-prossimi-passi)

## Funzionalità

- Parsing della classifica settimanale di ComingSoon.
- Estrazione di intervallo date, posizione, titolo, distributore, incasso,
  schermi e settimane di programmazione.
- Normalizzazione in oggetti `WeeklyBoxOfficeRecord`.
- Collegamento di ogni film della classifica al film TMDB (`movie_id`) con punteggio di somiglianza, revisione dei casi incerti e override manuali.
- Bootstrap opzionale dei film TMDB più redditizi.
- Upsert idempotente delle tabelle `movies` e `weekly_box_office`, con schema gestito da migrazioni SQL versionate.
- Tracciamento delle esecuzioni nella tabella `ingestion_runs`.
- Modalità `--dry-run` per analizzare i dati senza scrivere nel database.

## Architettura

```text
app/
├── models/          Modelli dati
├── parsers/         Parser ComingSoon e normalizzazione
├── repositories/    Accesso e upsert PostgreSQL
├── services/        Orchestrazione bootstrap e caricamento weekly
├── db.py            Connessioni PostgreSQL per ruolo (app, owner, ro)
├── credentials.py   Accesso ai segreti (variabili d'ambiente o Gestione credenziali)
├── roles.py         Ruoli PostgreSQL a privilegi minimi, grant e verifica
├── migrations.py    Runner delle migrazioni SQL
├── health.py        Controlli di salute e qualità sul database
├── matching.py      Punteggio e decisione dei match (logica pura)
├── validation.py    Controlli di qualità sui record weekly
├── settings.py      Configurazione (.env per i valori non segreti)
└── tmdb_client.py   Client API TMDB
scripts/
├── bootstrap.py     Carica i film da TMDB
├── weekly_run.py    Carica la classifica weekly da ComingSoon
├── resolve_matches.py  Collega i film della classifica ai film TMDB (movie_id)
├── load_weekly_run.py  CLI weekly con opzione --dry-run
├── migrate.py       Applica le migrazioni (ruolo owner) e riapplica i privilegi (--status per lo stato)
├── recover_from_wayback.py  Recupera da Wayback le settimane mancanti
├── health_check.py  Controlli di salute e qualità (esce con 1 se c'è un FAIL)
├── manage_secrets.py  Gestione dei segreti nel deposito credenziali
├── setup_db_roles.py  Crea i ruoli a privilegi minimi e ne verifica i permessi
├── backup_db.py     Backup con pg_dump in backups/
├── harden_permissions.ps1  Limita i permessi di .env, backups e logs al solo utente
├── run_weekly.ps1   Esecuzione non presidiata: pipeline + health check, con log
├── register_weekly_task.ps1  Registra/rimuove l'attività pianificata di Windows
└── verify_db.py     Verifica i dati nel database
migrations/          Migrazioni SQL numerate (001_baseline.sql, ...)
init_db.py           Alias di scripts/migrate.py
main_v3.py           Esegue caricamento weekly e risoluzione dei match in sequenza
tests/               Test di regressione
```

Il flusso completo eseguito da `main_v3.py` è:

1. recupero e parsing della classifica ComingSoon;
2. upsert dei record nella tabella `weekly_box_office` e registrazione dell'esito in `ingestion_runs`;
3. risoluzione dei match: i film ancora senza `movie_id` vengono cercati su TMDB e, se il match è netto,
   scaricati nella tabella `movies`.

Il bootstrap dei film più redditizi (`scripts/bootstrap.py`) non fa più parte della pipeline: `movies`
si popola solo con i film che compaiono davvero nelle classifiche italiane.

## Prerequisiti

- Python 3.12 consigliato (la CI usa Python 3.12).
- PostgreSQL raggiungibile dall'ambiente di esecuzione.
- Una chiave API TMDB per il bootstrap dei film.

## Configurazione

Copiare `.env.example` in `.env` nella root del progetto (il file è escluso dal controllo versione). **Contiene solo
valori non segreti**: host, nome del database e i nomi dei ruoli PostgreSQL. Password e chiavi API stanno nella
Gestione credenziali di Windows (vedi «Sicurezza e credenziali»); in CI si passano come variabili d'ambiente.

```dotenv
DB_HOST=localhost
DB_NAME=boxoffice
DB_USER=boxoffice_app
DB_OWNER_USER=boxoffice_owner
DB_RO_USER=boxoffice_ro
```

Sono obbligatorie `DB_HOST`, `DB_NAME` e `DB_USER`. `DB_PORT`, `LOG_LEVEL` e `REQUEST_TIMEOUT` hanno valori
predefiniti.

## Sicurezza e credenziali

**Ruoli PostgreSQL a privilegi minimi.** Nessuno è superutente (un superutente può eseguire comandi sul sistema con
`COPY ... PROGRAM` e leggere file del server: una sua password trapelata equivale a compromettere l'utente Windows).

| Ruolo | Chi lo usa | Cosa può fare |
|---|---|---|
| `boxoffice_owner` | solo `scripts/migrate.py` e `backup_db.py` | proprietario del database e degli oggetti; unico con DDL |
| `boxoffice_app` | pipeline, resolver, recupero da Wayback | `SELECT`/`INSERT`/`UPDATE` (e `DELETE` solo su `source_movies` e `match_candidates`); nessun DDL, nessun `TRUNCATE` |
| `boxoffice_ro` | `health_check.py`, `verify_db.py`, analisi | solo `SELECT` |
| `boxoffice_test` | test di integrazione locali | può creare database temporanei; nessun accesso al database reale |

I privilegi sono dichiarati tabella per tabella in `TABLE_PRIVILEGES` (`app/roles.py`): una tabella nuova non è
accessibile a nessuno finché non viene aggiunta lì (un test lo impone), e `migrate.py` riapplica i privilegi dopo
ogni migrazione. Le password sono passate a PostgreSQL già trasformate in hash SCRAM, quindi non compaiono nemmeno
nei log del server.

**Dove stanno i segreti.** Nella Gestione credenziali di Windows (cifrata con DPAPI e legata al tuo account), servizio
`NewBoxofficeProject`: `db:<ruolo>`, `tmdb_api_key`, `tmdb_read_token`. Se una variabile d'ambiente con lo stesso
scopo è impostata (`DB_PASSWORD`, `TMDB_API_KEY`, `TMDB_READ_TOKEN`) ha la precedenza: serve alla CI. Quindi `.env`, i
backup, i log e la cartella del progetto non contengono segreti.

```powershell
python scripts/manage_secrets.py list                    # cosa c'è nel deposito (mai i valori)
python scripts/manage_secrets.py set tmdb_read_token     # chiede il valore senza mostrarlo
python scripts/manage_secrets.py get db:postgres --show  # recupero della password amministratore, se serve
python scripts/setup_db_roles.py --verify-only           # prova cosa possono e cosa NON possono fare i ruoli
python scripts/setup_db_roles.py --rotate                # nuove password per tutti i ruoli
python scripts/backup_db.py --label prima_di_x           # backup con pg_dump in backups/
```

**Prima configurazione** (una tantum, da amministratore PostgreSQL): `python scripts/manage_secrets.py import-env --strip`
sposta nel deposito i segreti eventualmente presenti in `.env`; poi
`python scripts/setup_db_roles.py --database boxoffice` crea i ruoli, trasferisce la proprietà, assegna i privilegi,
genera le password e le salva nel deposito, quindi prova i permessi. Infine impostare `DB_USER=boxoffice_app` in `.env`.
La password dell'amministratore (`postgres`) resta solo nel deposito: recuperarla con `get db:postgres --show` e, se
si preferisce, conservarla in un gestore di password ed eliminarla dal deposito.

**TMDB.** Con `tmdb_read_token` (il «API Read Access Token» del tuo account TMDB) la richiesta usa l'header
`Authorization: Bearer` e il token non compare mai nell'URL; in mancanza si ripiega sulla chiave API (`tmdb_api_key`).

**Permessi dei file.** `scripts/harden_permissions.ps1` limita `.env`, `backups/` e `logs/` al solo tuo utente (più
SYSTEM e Administrators): per ereditarietà erano leggibili anche da altri gruppi locali.

**Rete.** PostgreSQL deve ascoltare solo su `localhost` (`listen_addresses = 'localhost'`); il valore è già scritto con
`ALTER SYSTEM` e diventa attivo al riavvio del servizio, che richiede un PowerShell **come amministratore**:
`Restart-Service postgresql-x64-18`. Verifica: `Get-NetTCPConnection -LocalPort 5432 -State Listen` deve mostrare solo
`127.0.0.1` e `::1`.

**GitHub.** Attivare a mano *Settings → Code security → Secret scanning* e *Push protection* del repository.

**Cosa NON protegge.** Il deposito credenziali difende da fughe del file (backup, sincronizzazioni, repository, altri utenti o gruppi locali) ma non da un programma malevolo che gira **con il tuo stesso account**: quello può chiedere al deposito le stesse password che chiede la pipeline. Per questo il danno massimo di quelle credenziali è limitato dai ruoli a privilegi minimi, e la password del superutente non è usata dall'applicazione.

## Installazione

Da PowerShell, nella root del progetto:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Esecuzione

### Inizializzazione e migrazioni del database

```powershell
python scripts/migrate.py            # applica le migrazioni mancanti
python scripts/migrate.py --status   # mostra lo stato senza modificare nulla
```

Lo schema è definito solo dalle migrazioni in [`migrations/`](migrations/) (tracciate nella tabella
`schema_migrations`). L'applicazione non esegue più DDL: se ci sono migrazioni da applicare,
bootstrap e caricamento weekly si fermano con un errore che indica di eseguire `migrate.py`.
Una migrazione già applicata non va mai modificata (il checksum viene verificato): se ne crea una nuova.
`python init_db.py` resta come alias di `migrate.py`. Le migrazioni girano con il ruolo `owner` (l'unico con DDL) e, a
migrazioni finite, `migrate.py` riapplica i privilegi dei ruoli `app` e `ro` (vedi «Sicurezza e credenziali»).

### Pipeline completa

```powershell
python main_v3.py
```

### Esecuzione delle fasi separatamente

```powershell
python scripts/bootstrap.py   # opzionale: top film per incasso mondiale
```

5. Esegui il caricamento weekly separatamente:

```powershell
python scripts/weekly_run.py
```

Il comando precedente `python scripts/load_weekly_run.py` resta supportato come wrapper compatibile.

6. Backfill storico (**limitato**): ComingSoon non ha un archivio consultabile e ignora i
   parametri data, servendo sempre la classifica corrente. Il backfill carica quindi solo le
   settimane che la pagina contiene davvero e salta (con un warning) tutte le altre, senza
   rietichettare la classifica corrente con date passate. Per costruire lo storico occorre
   eseguire `weekly_run.py` ogni settimana (giovedì–lunedì) oppure usare un'altra fonte.

```powershell
python scripts/backfill_historical_weekly.py --start-date 2026-09-18 --weeks 1
```

Per esperimenti usare il database di sviluppo, senza toccare quello reale
(`DB_NAME` da ambiente ha la precedenza su `.env`; `boxoffice_dev` va creato una volta
con `CREATE DATABASE` e inizializzato con `python init_db.py`):

```powershell
$env:DB_NAME = "boxoffice_dev"; python scripts/weekly_run.py
```

7. Collega i film ai film TMDB (`movie_id`):

```powershell
python scripts/resolve_matches.py              # abbina i film nuovi
python scripts/resolve_matches.py --dry-run    # valuta senza scrivere
python scripts/resolve_matches.py --review     # mostra i match incerti con i candidati
python scripts/resolve_matches.py --set 2 --tmdb-id 920   # conferma a mano (id di source_movies da --review)
python scripts/resolve_matches.py --no-match 28            # il film non esiste su TMDB
python scripts/resolve_matches.py --retry                  # riprova anche da_rivedere / senza_match
```

Per ogni film si cerca su TMDB in italiano e i migliori 3 candidati vengono valutati con il titolo
(anche originale e alternativi IT), la data di uscita in Italia pubblicata da TMDB (o, in mancanza, quella di
uscita generale) confrontata con quella stimata dalla classifica (`week_start − 7·(settimane − 1)`), e la popolarità.
Il match è **automatico** solo se il punteggio è ≥ 0.85 e il migliore ha almeno 0.10 di margine sul secondo;
tra 0.55 e la soglia va in **revisione** (`needs_review`, con i candidati in `match_candidates`); sotto è `no_match`.
I match manuali non vengono mai modificati dal resolver. Le righe caricate prima dell'introduzione degli ID
ComingSoon vengono collegate per titolo (`legacy:<titolo>`), adottando i `movie_id` già presenti.

8. Verifica il contenuto della tabella e la copertura dei `movie_id`:

```powershell
python scripts/verify_db.py
```

### Esecuzione pianificata (Windows)

ComingSoon **non ha archivio**: una settimana non caricata non si recupera. La pipeline va quindi eseguita ogni
settimana. `scripts/register_weekly_task.ps1` registra un'attività dell'Utilità di pianificazione che esegue
`scripts/run_weekly.ps1` (pipeline + health check) **ogni lunedì e venerdì alle 12:00**: la classifica del weekend
(giovedì–domenica) compare entro lunedì e resta fino al weekend dopo, quindi il venerdì è una rete di sicurezza per il
caso in cui il PC fosse spento lunedì. L'upsert è idempotente, quindi rieseguire non crea duplicati.

```powershell
.\scripts\register_weekly_task.ps1              # registra (lun e ven alle 12:00)
.\scripts\register_weekly_task.ps1 -Time 09:30  # altro orario
.\scripts\register_weekly_task.ps1 -Remove      # rimuove l'attività
Start-ScheduledTask -TaskName "NewBoxOffice-WeeklyRun"   # avvio manuale
```

L'attività gira come l'utente corrente **solo con la sessione aperta**, senza privilegi elevati né password salvata;
se il PC era spento all'ora prevista parte appena possibile (`StartWhenAvailable`). Ogni esecuzione scrive un log in
`logs/weekly_<data>.log` (conservati 90 giorni, cartella ignorata da git). Il codice di uscita è quello della pipeline
(o dell'health check): compare come «Ultimo risultato» nell'Utilità di pianificazione. Non ci sono notifiche attive:
i guasti si vedono lì, nel log e con `health_check.py`.

### Controlli di salute

```powershell
python scripts/health_check.py            # esce con 1 se c'è almeno un FAIL
python scripts/health_check.py --strict   # considera fallimento anche i WARN
```

Controlla: età e esito dell'ultimo run, ultima settimana presente (e numero di righe), settimane mancanti nelle
ultime 12, coerenza di `movie_id` tra `weekly_box_office` e `source_movies`, righe senza film sorgente, coda dei
match da abbinare/rivedere, copertura dei `movie_id` nell'ultima settimana e anomalie di sorgente (classifica non
ordinata per incasso, totale inferiore al weekend). I FAIL indicano una pipeline ferma o dati incoerenti; i WARN
sono cose da guardare (es. le settimane storiche perse, che restano segnalate finché rientrano nella finestra).

### Recupero di settimane mancanti da Wayback

Se una settimana non è stata caricata (PC spento, guasto), ComingSoon non la serve più. L'unica via è uno snapshot
dell'Internet Archive:

```powershell
python scripts/recover_from_wayback.py --dry-run   # cosa si troverebbe, senza scrivere
python scripts/recover_from_wayback.py             # scrive le settimane recuperabili
python scripts/resolve_matches.py                  # collega i film nuovi a TMDB
```

Lo script cerca i buchi come `health_check.py`, elenca gli snapshot di `comingsoon.it/cinema/boxoffice` e per ogni
settimana prova i più recenti nella finestra in cui quella classifica era online (da domenica a domenica dopo il
weekend). Uno snapshot è accettato solo se la settimana **scritta nella pagina** coincide e ha almeno 10 righe: la
data dello snapshot serve solo a sceglierlo, mai a etichettare i dati. Le richieste sono poche, con pause,
`User-Agent` senza dati personali e nuovi tentativi con attese crescenti (il servizio dà spesso 503). I run sono
registrati con `pipeline_name = 'weekly_box_office_recovery'` (non contano per la freschezza dell'health check) e la
pagina archiviata resta in `raw_snapshots`. Wayback ha pochi snapshot: nel periodo luglio–settembre 2026 solo 3, quindi
non ogni settimana è recuperabile. **Non usare Box Office Mojo** come fonte alternativa: il suo `robots.txt` vieta
l'accesso automatico e i dati sono convertiti in dollari.

### Vista per le analisi

`v_weekly_enriched` unisce classifica, film TMDB e stato del match (titolo TMDB e originale, generi, durata,
budget, incasso mondiale, `gross_per_screen`, `match_status`…): è il punto di accesso consigliato per report e
query, così i cambi di schema non rompono le analisi.

```sql
SELECT rank, external_movie_title, tmdb_title, weekly_gross, gross_per_screen
FROM v_weekly_enriched WHERE week_start = (SELECT max(week_start) FROM weekly_box_office) ORDER BY rank;
```

## Note tecniche
- `WeeklyBoxOfficeService` gestisce ingestion run, salvataggio della pagina grezza e upsert tramite `WeeklyBoxOfficeRepository`.
- `python main_v3.py` esegue il caricamento weekly e poi la risoluzione dei match.
- Il caricamento weekly non richiede più `PYTHONPATH` quando gli script sono eseguiti direttamente.

## Test e Continuous Integration

La suite usa `unittest` e sostituisce le dipendenze dal database con repository
fittizi. Perciò i test non richiedono PostgreSQL, TMDB o un file `.env`:

```powershell
python -m unittest discover --start-directory tests --verbose
```

I test di integrazione (`tests/test_db_integration.py`) sono saltati di default. Con
`RUN_DB_TESTS=1` usano il ruolo `boxoffice_test` (dal deposito credenziali; in CI l'utente configurato) per creare un database temporaneo
`boxoffice_test_<random>`, applicarvi le migrazioni ed eliminarlo al termine, senza toccare
il database configurato:

```powershell
$env:RUN_DB_TESTS = "1"; python -m unittest tests.test_db_integration -v
```

Il workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) esegue la suite a ogni push e pull request
con un **servizio Postgres 18** e `RUN_DB_TESTS=1`, quindi anche i test di integrazione girano in CI (con valori
fittizi: nessun segreto reale). Poi verifica che le migrazioni si applichino da zero e siano idempotenti, ed esegue
`bandit` e `pip-audit`. Installa le dipendenze di [`requirements.txt`](requirements.txt), usa il caching di pip e
limita i permessi del job alla sola lettura del repository.

## Schema dati

### `movies`

Contiene i dettagli dei film provenienti da TMDB. L'ID TMDB è la chiave
primaria e i caricamenti successivi aggiornano i valori esistenti.

### `weekly_box_office`

Una riga per film, fonte, territorio e settimana. La chiave unica è
`(source_name, territory, week_start, external_movie_title)`; il `rank` è un attributo, quindi una
classifica rivista aggiorna le righe esistenti invece di sovrascrivere il film sbagliato.
`movie_id` è una FK verso `movies(id)` (`ON DELETE SET NULL`) e un nuovo caricamento non lo azzera mai;
`source_movie_ref` punta al film della sorgente in `source_movies`.

### `match_candidates`

Candidati TMDB valutati per i film in `needs_review` (punteggio complessivo, di titolo e di data), usati da
`resolve_matches.py --review`.

### `source_movies`

Film come li conosce la sorgente (per ComingSoon l'ID nell'URL `/film/<slug>/<id>/scheda/`) e il loro
legame con `movies.id`: `movie_id`, `match_status` (`unmatched`, `auto`, `manual`, `needs_review`,
`no_match`), `match_method`, `match_confidence`. L'ingestion inserisce i film ma non decide i match.

### `raw_snapshots`

Pagina grezza scaricata a ogni run settimanale (URL, SHA-256, HTML), collegata a `ingestion_runs`.
Viene salvata anche se il caricamento fallisce, così si può rielaborare senza riscaricare.

### `ingestion_runs`

Registra pipeline, fonte, stato, timestamp, numero di record letti e scritti
ed eventuali errori.

## Cronologia del progetto

La cronologia seguente riassume i principali cambiamenti rilevati nei commit:

| Commit | Data | Evoluzione |
| --- | --- | --- |
| `25a5450` | 2026-06-16 | Primo pipeline completo: parser ComingSoon, servizi, repository e configurazione iniziale. |
| `e3ca6f5` | 2026-07-13 | Correzione del parser e passaggio dai dizionari al dataclass `WeeklyBoxOfficeRecord`. |
| `7e2ce94` | 2026-07-13 | Ulteriori correzioni a date, parser e gestione degli oggetti. |
| `bef234d` | 2026-07-14 | Allineamento della logica di inserimento weekly con l'upsert del repository. |
| `09a748a` | 2026-07-14 | Refactoring dell'accesso ai dati weekly e aggiunta di `verify_db.py`. |
| `6065b1a` | 2026-08-05 | Debug e pulizia del comportamento del pipeline. |
| `ae7a156` | 2026-08-07 | Rimozione di colonne non più utilizzate dallo schema weekly. |
| `6b31f28` | 2026-08-07 | Estensione del parser per serie storiche e aggiunta di una CLI di backfill. |
| `133c19f` | 2026-08-09 | Ampliamento dei test del parser e del servizio weekly. |
| `f1ca827` | 2026-08-10 | Introduzione della suite di test. |
| `407faa1` | 2026-08-24 | Debug del servizio weekly e aggiunta dei test di regressione attualmente presenti. |

I riferimenti sono abbreviazioni degli hash Git e possono essere approfonditi
con `git show <commit>` o `git log --all --oneline`.

## Limitazioni e prossimi passi

- Aggiungere test unitari mirati per `parse_italian_date()` e
  `extract_week_range()`.
- Aggiungere test del parser con fixture HTML, evitando dipendenze dal sito
  remoto durante i test.
- Valutare logging e retry con backoff per rate limit o indisponibilità delle
  sorgenti esterne.
- Separare ulteriormente le CLI dalle utility di orchestrazione.
