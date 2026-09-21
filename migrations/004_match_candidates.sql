-- Fase 3: supporto alla risoluzione dei match (box office -> film TMDB).

-- Titolo originale del film (utile per verificare i match e per confronti futuri).
ALTER TABLE movies ADD COLUMN IF NOT EXISTS original_title TEXT;

-- Candidati TMDB valutati per un film sorgente: serve alla revisione manuale dei match incerti.
CREATE TABLE match_candidates (
    source_movie_id BIGINT NOT NULL REFERENCES source_movies(id) ON DELETE CASCADE,
    tmdb_id INTEGER NOT NULL,
    title TEXT,
    original_title TEXT,
    release_date DATE,
    popularity DOUBLE PRECISION,
    score NUMERIC(4, 3) NOT NULL,
    title_score NUMERIC(4, 3) NOT NULL,
    date_score NUMERIC(4, 3) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_movie_id, tmdb_id)
);
