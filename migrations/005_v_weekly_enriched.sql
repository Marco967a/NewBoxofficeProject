-- Vista di lettura: classifica settimanale arricchita con i dati del film TMDB e lo stato del match.
-- Punto di accesso consigliato per analisi e report (evita join manuali e semplifica i cambi di schema).
CREATE OR REPLACE VIEW v_weekly_enriched AS
SELECT
    w.id AS weekly_id,
    w.source_name,
    w.territory,
    w.week_start,
    w.week_end,
    w.rank,
    w.external_movie_title,
    w.distributor,
    w.weekly_gross,
    w.total_gross,
    w.screen_count,
    w.weeks_in_release,
    CASE WHEN w.screen_count > 0 THEN round(w.weekly_gross / w.screen_count, 2) END AS gross_per_screen,
    w.movie_id,
    m.title AS tmdb_title,
    m.original_title,
    m.release_date AS tmdb_release_date,
    m.genres,
    m.runtime,
    m.original_language,
    m.vote_average,
    m.budget,
    m.revenue AS worldwide_revenue,
    s.source_movie_id,
    s.url AS source_url,
    s.match_status,
    s.match_method,
    s.match_confidence,
    w.ingestion_run_id
FROM weekly_box_office w
LEFT JOIN source_movies s ON s.id = w.source_movie_ref
LEFT JOIN movies m ON m.id = w.movie_id;
