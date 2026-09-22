-- La chiave naturale di weekly_box_office confrontava external_movie_title lettera per lettera: uno
-- spazio o una maiuscola in più tra una settimana e l'altra (capita, ComingSoon non è consistente)
-- creava una riga nuova invece di aggiornare quella esistente, spezzando la storia del film.
-- title_key normalizza lo stesso modo già usato per collegare le righe storiche (lower(btrim(...))).

-- Difensivo: se in qualche ambiente esistessero già righe duplicate dopo la normalizzazione, le
-- unifica prima di creare il vincolo (tiene la più aggiornata, sposta gli eventuali riferimenti).
DO $$
DECLARE
    grp RECORD;
    keep_id BIGINT;
BEGIN
    FOR grp IN
        SELECT source_name, territory, week_start, lower(btrim(external_movie_title)) AS key
        FROM weekly_box_office
        GROUP BY 1, 2, 3, 4
        HAVING count(*) > 1
    LOOP
        SELECT id INTO keep_id FROM weekly_box_office
        WHERE source_name = grp.source_name AND territory = grp.territory AND week_start = grp.week_start
          AND lower(btrim(external_movie_title)) = grp.key
        ORDER BY updated_at DESC, id DESC LIMIT 1;

        -- Il duplicato con un movie_id/source_movie_ref che la riga tenuta non ha viene recuperato.
        UPDATE weekly_box_office w
        SET movie_id = COALESCE(w.movie_id, d.movie_id), source_movie_ref = COALESCE(w.source_movie_ref, d.source_movie_ref)
        FROM (
            SELECT movie_id, source_movie_ref FROM weekly_box_office
            WHERE source_name = grp.source_name AND territory = grp.territory AND week_start = grp.week_start
              AND lower(btrim(external_movie_title)) = grp.key AND id <> keep_id
            ORDER BY updated_at DESC LIMIT 1
        ) d
        WHERE w.id = keep_id;

        DELETE FROM weekly_box_office
        WHERE source_name = grp.source_name AND territory = grp.territory AND week_start = grp.week_start
          AND lower(btrim(external_movie_title)) = grp.key AND id <> keep_id;
    END LOOP;
END $$;

ALTER TABLE weekly_box_office
    ADD COLUMN title_key TEXT GENERATED ALWAYS AS (lower(btrim(external_movie_title))) STORED;

ALTER TABLE weekly_box_office DROP CONSTRAINT weekly_box_office_week_title_key;
ALTER TABLE weekly_box_office
    ADD CONSTRAINT weekly_box_office_week_title_key
    UNIQUE (source_name, territory, week_start, title_key);
