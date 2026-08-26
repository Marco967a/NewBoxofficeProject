# NewBoxofficeProject

Pipeline Python che raccoglie dati settimanali di box office da ComingSoon.it e li carica su PostgreSQL.

## Overview
Questo progetto raccoglie dati settimanali di box office da ComingSoon.it, li normalizza e li carica su PostgreSQL.

## Come eseguire (ambiente di sviluppo)
1. Crea e attiva l'ambiente virtuale e installa le dipendenze:

```powershell
python -m pip install -r requirements.txt
```

2. Configura il file `.env` nella root del progetto con le variabili richieste:

```
TMDB_API_KEY=...
DB_HOST=localhost
DB_NAME=boxoffice
DB_USER=postgres
DB_PASSWORD=...
DB_PORT=5432
```

3. Inizializza il DB (crea le tabelle):

```powershell
python init_db.py
```

4. Esegui il bootstrap TMDB separatamente:

```powershell
python scripts/bootstrap.py
```

5. Esegui il caricamento weekly separatamente:

```powershell
python scripts/weekly_run.py
```

Il comando precedente `python scripts/load_weekly_run.py` resta supportato come wrapper compatibile.

6. Per un backfill storico:

```powershell
python scripts/backfill_historical_weekly.py --start-date 2024-02-15 --weeks 4
```

7. Verifica il contenuto della tabella:

```powershell
python scripts/verify_db.py
```

## Note tecniche
- `WeeklyBoxOfficeService` gestisce ingestion run, creazione delle tabelle e upsert tramite `WeeklyBoxOfficeRepository`.
- `python main_v3.py` esegue bootstrap TMDB e caricamento weekly in sequenza.
- Il caricamento weekly non richiede più `PYTHONPATH` quando gli script sono eseguiti direttamente.
