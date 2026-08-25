# NewBoxofficeProject

Pipeline Python per raccogliere i dati settimanali del box office italiano da
[ComingSoon.it](https://www.comingsoon.it/cinema/boxoffice/), arricchire i film
tramite TMDB e salvare i dati in PostgreSQL.

## Indice

- [Funzionalità](#funzionalità)
- [Architettura](#architettura)
- [Prerequisiti](#prerequisiti)
- [Configurazione](#configurazione)
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
- Bootstrap dei film TMDB più redditizi e arricchimento dei relativi dettagli.
- Upsert idempotente delle tabelle `movies` e `weekly_box_office`.
- Tracciamento delle esecuzioni nella tabella `ingestion_runs`.
- Modalità `--dry-run` per analizzare i dati senza scrivere nel database.

## Architettura

```text
app/
├── models/          Modelli dati
├── parsers/         Parser ComingSoon e normalizzazione
├── repositories/    Accesso e upsert PostgreSQL
├── services/        Orchestrazione bootstrap e caricamento weekly
├── db.py            Gestione connessioni PostgreSQL
├── settings.py      Configurazione da variabili d'ambiente
└── tmdb_client.py   Client API TMDB
scripts/
├── bootstrap.py     Carica i film da TMDB
├── weekly_run.py    Carica la classifica weekly da ComingSoon
├── load_weekly_run.py  CLI weekly con opzione --dry-run
└── verify_db.py     Verifica i dati nel database
init_db.py           Crea le tabelle
main_v3.py           Esegue bootstrap e caricamento weekly in sequenza
tests/               Test di regressione
```

Il flusso completo eseguito da `main_v3.py` è:

1. recupero dei film TMDB e salvataggio nella tabella `movies`;
2. recupero e parsing della classifica ComingSoon;
3. upsert dei record nella tabella `weekly_box_office`;
4. registrazione dell'esito nella tabella `ingestion_runs`.

## Prerequisiti

- Python 3.12 consigliato (la CI usa Python 3.12).
- PostgreSQL raggiungibile dall'ambiente di esecuzione.
- Una chiave API TMDB per il bootstrap dei film.

## Configurazione

Creare un file `.env` nella root del progetto. Il file è escluso dal controllo
versione e non deve contenere valori reali condivisi:

```dotenv
TMDB_API_KEY=your_tmdb_api_key
DB_HOST=localhost
DB_NAME=boxoffice
DB_USER=postgres
DB_PASSWORD=your_database_password
LOG_LEVEL=INFO
REQUEST_TIMEOUT=30
```

Le prime cinque variabili sono obbligatorie. `LOG_LEVEL` e `REQUEST_TIMEOUT`
hanno valori predefiniti.

## Installazione

Da PowerShell, nella root del progetto:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Esecuzione

### Inizializzazione del database

```powershell
python init_db.py
```

Il comando crea, se non esistono, le tabelle `movies`,
`weekly_box_office` e `ingestion_runs`.

### Pipeline completa

```powershell
python main_v3.py
```

### Esecuzione delle fasi separatamente

```powershell
$env:PYTHONPATH="."; python scripts/bootstrap.py
$env:PYTHONPATH="."; python scripts/weekly_run.py
$env:PYTHONPATH="."; python scripts/verify_db.py
```

### Parsing weekly senza scrittura

```powershell
python scripts/load_weekly_run.py --dry-run
```

Questa modalità esegue il parsing e restituisce zero record scritti senza
aprire una connessione al database.

## Test e Continuous Integration

La suite usa `unittest` e sostituisce le dipendenze dal database con repository
fittizi. Perciò i test non richiedono PostgreSQL, TMDB o un file `.env`:

```powershell
python -m unittest discover --start-directory tests --verbose
```

Il workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) esegue lo
stesso comando a ogni push e pull request. Installa le dipendenze bloccate in
[`requirements.txt`](requirements.txt), usa il caching di pip e limita i
permessi del job alla sola lettura del repository.

## Schema dati

### `movies`

Contiene i dettagli dei film provenienti da TMDB. L'ID TMDB è la chiave
primaria e i caricamenti successivi aggiornano i valori esistenti.

### `weekly_box_office`

Contiene una riga per posizione, fonte, territorio e intervallo settimanale.
La chiave unica `(source_name, territory, week_start, week_end, rank)` rende
il caricamento ripetibile senza duplicati.

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
