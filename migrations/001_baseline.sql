-- Baseline: fotografa lo schema reale in produzione al 2026-09-21.
-- Su un DB già popolato è un no-op (IF NOT EXISTS); su un DB vuoto crea lo stato di partenza
-- su cui lavorano le migrazioni successive.

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id BIGSERIAL PRIMARY KEY,
    pipeline_name TEXT NOT NULL,
    source_name TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    records_read INTEGER DEFAULT 0,
    records_written INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY,
    title TEXT,
    release_date DATE,
    revenue BIGINT,
    budget BIGINT,
    popularity DOUBLE PRECISION,
    vote_average DOUBLE PRECISION,
    runtime INTEGER,
    original_language TEXT,
    genres TEXT,
    overview TEXT,
    tagline TEXT,
    status TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS weekly_box_office (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    territory TEXT NOT NULL DEFAULT 'IT',
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    rank INTEGER NOT NULL,
    movie_id INTEGER,
    external_movie_title TEXT NOT NULL,
    distributor TEXT,
    weekly_gross NUMERIC(14,2),
    screen_count INTEGER,
    weeks_in_release INTEGER,
    ingestion_run_id BIGINT REFERENCES ingestion_runs(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    total_gross NUMERIC(14,2),
    UNIQUE (source_name, territory, week_start, week_end, rank)
);
