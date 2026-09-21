-- Allinea lo schema reale a quello voluto dal codice e aggiunge vincoli di integrità.

-- movies: il codice si aspettava title NOT NULL, created_at e i DEFAULT, assenti nel DB reale.
ALTER TABLE movies ALTER COLUMN title SET NOT NULL;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
UPDATE movies SET created_at = updated_at WHERE created_at IS NULL OR created_at > updated_at;
ALTER TABLE movies ALTER COLUMN revenue SET DEFAULT 0;
ALTER TABLE movies ALTER COLUMN budget SET DEFAULT 0;
ALTER TABLE movies ALTER COLUMN popularity SET DEFAULT 0;
ALTER TABLE movies ALTER COLUMN vote_average SET DEFAULT 0;

-- Timestamp con fuso orario. I valori esistenti erano scritti da NOW() nel fuso di sessione
-- del server, quindi vengono interpretati in quel fuso. Idempotente.
DO $$
DECLARE
    col RECORD;
BEGIN
    FOR col IN
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND data_type = 'timestamp without time zone'
          AND (table_name, column_name) IN (
              ('ingestion_runs', 'started_at'), ('ingestion_runs', 'finished_at'),
              ('movies', 'created_at'), ('movies', 'updated_at'),
              ('weekly_box_office', 'created_at'), ('weekly_box_office', 'updated_at'))
    LOOP
        EXECUTE format(
            'ALTER TABLE %I ALTER COLUMN %I TYPE TIMESTAMPTZ USING %I AT TIME ZONE current_setting(''TimeZone'')',
            col.table_name, col.column_name, col.column_name);
    END LOOP;
END $$;

-- ingestion_runs
ALTER TABLE ingestion_runs ALTER COLUMN records_read SET NOT NULL;
ALTER TABLE ingestion_runs ALTER COLUMN records_written SET NOT NULL;
ALTER TABLE ingestion_runs
    ADD CONSTRAINT ingestion_runs_status_check CHECK (status IN ('running', 'success', 'failed'));

-- weekly_box_office
ALTER TABLE weekly_box_office
    ADD CONSTRAINT weekly_box_office_week_order_check CHECK (week_end >= week_start);
ALTER TABLE weekly_box_office
    ADD CONSTRAINT weekly_box_office_rank_check CHECK (rank > 0);

-- Indici sulle colonne usate per join e filtri (le FK di Postgres non li creano da sole).
CREATE INDEX IF NOT EXISTS idx_weekly_box_office_week_start ON weekly_box_office (week_start);
CREATE INDEX IF NOT EXISTS idx_weekly_box_office_ingestion_run_id ON weekly_box_office (ingestion_run_id);
