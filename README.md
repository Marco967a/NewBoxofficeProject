# NewBoxofficeProject

Breve documentazione del progetto e delle modifiche recenti.

## Overview
Questo progetto raccoglie dati settimanali di box office da ComingSoon.it, li normalizza e li carica su PostgreSQL.

## Cambiamenti recenti
- Il parser `app/parsers/comingsoon_parser.py` è stato migliorato: le date ora sono restitute come `date` (non stringhe), i pattern regex sono più tolleranti e viene aggiunto un `User-Agent` alla richiesta HTTP.
- La logica di upsert per `weekly_box_office` è stata unificata in `app/db.py::insert_weekly_records`.
- `app/repositories/weekly_box_office_repository.py` è stato rimosso. `app/services/weekly_box_office_service.WeeklyBoxOfficeService` ora utilizza `insert_weekly_records`.

## Come eseguire (ambiente di sviluppo)
1. Crea e attiva l'ambiente virtuale, installa dipendenze (es. `requests`, `beautifulsoup4`, `psycopg2-binary`, `python-dotenv`).

2. Configura il file `.env` nella root del progetto con le variabili richieste:

```
TMDB_API_KEY=...
DB_HOST=localhost
DB_NAME=boxoffice
DB_USER=postgres
DB_PASSWORD=...
```

3. Inizializza il DB (crea le tabelle):

```powershell
python init_db.py
```

4. Esegui il bootstrap TMDB separatamente:

```powershell
$env:PYTHONPATH="."; python scripts/bootstrap.py
```

5. Esegui il caricamento weekly separatamente:

```powershell
python scripts/weekly_run.py
```

Il comando precedente `python scripts/load_weekly_run.py` resta supportato come wrapper compatibile.

6. Verifica il contenuto della tabella:

```powershell
$env:PYTHONPATH="."; python scripts/verify_db.py
```

Nota: su PowerShell si usa `$env:PYTHONPATH="."; python ...` per rendere importabile il package `app`.

## Note tecniche
- `insert_weekly_records(records, ingestion_run_id=None, conn=None)` supporta sia `dict` che oggetti dataclass.
- Se desideri ripristinare un'architettura con repository, la query SQL è ora presente in `app/db.py` e `WeeklyBoxOfficeService` la riutilizza.

## Prossimi passi suggeriti
- Aggiungere test unitari per `parse_italian_date()` e `extract_week_range()`.
- Aggiungere logging alla produzione e gestione rate-limit/ritardi per il fetching esterno.
