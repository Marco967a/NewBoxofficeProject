-- Collegamento box office -> film (movie_id), chiave naturale della settimana e dati grezzi.

-- Film come li conosce la sorgente (per ComingSoon: ID nell'URL /film/<slug>/<id>/scheda/).
-- E' l'unico posto dove vive il legame con TMDB: movies.id resta l'ID TMDB.
CREATE TABLE source_movies (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_movie_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    -- RESTRICT: un film con match confermato non si cancella; prima va rimosso il match.
    movie_id INTEGER REFERENCES movies(id),
    match_status TEXT NOT NULL DEFAULT 'unmatched'
        CHECK (match_status IN ('unmatched', 'auto', 'manual', 'needs_review', 'no_match')),
    match_method TEXT,
    match_confidence NUMERIC(4, 3) CHECK (match_confidence BETWEEN 0 AND 1),
    matched_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_name, source_movie_id),
    CHECK ((movie_id IS NULL) = (match_status NOT IN ('auto', 'manual')))
);
CREATE INDEX idx_source_movies_movie_id ON source_movies (movie_id);
CREATE INDEX idx_source_movies_status ON source_movies (match_status);

-- Pagina grezza scaricata a ogni run: permette di rielaborare senza riscaricare.
CREATE TABLE raw_snapshots (
    id BIGSERIAL PRIMARY KEY,
    ingestion_run_id BIGINT NOT NULL REFERENCES ingestion_runs(id),
    source_name TEXT NOT NULL,
    url TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_sha256 TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX idx_raw_snapshots_run ON raw_snapshots (ingestion_run_id);

-- weekly_box_office: riferimento al film della sorgente e FK reale su movie_id.
ALTER TABLE weekly_box_office
    ADD COLUMN source_movie_ref BIGINT REFERENCES source_movies(id) ON DELETE SET NULL;
ALTER TABLE weekly_box_office
    ADD CONSTRAINT weekly_box_office_movie_id_fkey
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE SET NULL;
CREATE INDEX idx_weekly_box_office_movie_id ON weekly_box_office (movie_id);
CREATE INDEX idx_weekly_box_office_source_movie_ref ON weekly_box_office (source_movie_ref);

-- Nuova chiave naturale: un film compare una volta per settimana. Il rank diventa un attributo
-- (prima era nella chiave: una classifica rivista sovrascriveva il film sbagliato e lasciava righe vecchie).
DO $$
DECLARE
    con RECORD;
BEGIN
    FOR con IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'weekly_box_office'::regclass AND contype = 'u'
    LOOP
        EXECUTE format('ALTER TABLE weekly_box_office DROP CONSTRAINT %I', con.conname);
    END LOOP;
END $$;

ALTER TABLE weekly_box_office
    ADD CONSTRAINT weekly_box_office_week_title_key
    UNIQUE (source_name, territory, week_start, external_movie_title);
CREATE INDEX idx_weekly_box_office_week_rank ON weekly_box_office (source_name, territory, week_start, rank);
