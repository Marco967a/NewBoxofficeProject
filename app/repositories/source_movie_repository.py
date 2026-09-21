from psycopg2.extras import execute_values


class SourceMovieRepository:
    """Film come li conosce la sorgente (es. ID ComingSoon) e il loro legame con movies.id."""

    def upsert_many(self, conn, source_movies: list[dict]) -> dict[tuple[str, str], tuple[int, int | None]]:
        """Inserisce/aggiorna i film sorgente e ritorna {(source_name, source_movie_id): (id, movie_id)}.

        Non tocca mai movie_id / match_*: quelli li decide la risoluzione dei match, non l'ingestion.
        """
        unique: dict[tuple[str, str], dict] = {}
        for item in source_movies:
            unique.setdefault((item["source_name"], str(item["source_movie_id"])), item)

        if not unique:
            return {}

        rows = [
            (source_name, source_movie_id, item["title"], item.get("url"))
            for (source_name, source_movie_id), item in unique.items()
        ]

        sql = """
            INSERT INTO source_movies (source_name, source_movie_id, title, url)
            VALUES %s
            ON CONFLICT (source_name, source_movie_id) DO UPDATE SET
                title = EXCLUDED.title,
                url = COALESCE(EXCLUDED.url, source_movies.url),
                updated_at = now()
            RETURNING source_name, source_movie_id, id, movie_id
        """

        with conn.cursor() as cur:
            result = execute_values(cur, sql, rows, page_size=100, fetch=True)

        return {(row[0], row[1]): (row[2], row[3]) for row in result}

    # --- risoluzione dei match --------------------------------------------------------------

    def list_for_matching(
        self, conn, source_name: str, statuses: tuple[str, ...], limit: int | None = None
    ) -> list[dict]:
        """Film da abbinare, con la prima settimana in classifica (serve a stimare l'uscita italiana).

        I match manuali non vengono mai riproposti.
        """
        sql = """
            SELECT s.id, s.source_movie_id, s.title, first_week.week_start, first_week.weeks_in_release
            FROM source_movies s
            LEFT JOIN LATERAL (
                SELECT w.week_start, w.weeks_in_release
                FROM weekly_box_office w
                WHERE w.source_movie_ref = s.id
                ORDER BY w.week_start
                LIMIT 1
            ) first_week ON TRUE
            WHERE s.source_name = %s
              AND s.match_status = ANY(%s)
              AND s.match_method IS DISTINCT FROM 'manual'
            ORDER BY s.id
        """
        params: list = [source_name, list(statuses)]
        if limit:
            sql += " LIMIT %s"
            params.append(limit)

        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [
                {
                    "id": row[0],
                    "source_movie_id": row[1],
                    "title": row[2],
                    "first_week_start": row[3],
                    "first_weeks_in_release": row[4],
                }
                for row in cur.fetchall()
            ]

    def save_match(
        self,
        conn,
        ref_id: int,
        status: str,
        movie_id: int | None,
        method: str,
        confidence: float | None,
    ) -> None:
        """Registra l'esito e allinea movie_id delle righe settimanali (source_movies è la fonte di verità)."""
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE source_movies
                SET movie_id = %s, match_status = %s, match_method = %s, match_confidence = %s,
                    matched_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (movie_id, status, method, confidence, ref_id),
            )
            cur.execute(
                """
                UPDATE weekly_box_office
                SET movie_id = %s, updated_at = now()
                WHERE source_movie_ref = %s AND movie_id IS DISTINCT FROM %s
                """,
                (movie_id, ref_id, movie_id),
            )

    def replace_candidates(self, conn, ref_id: int, candidates: list) -> None:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM match_candidates WHERE source_movie_id = %s", (ref_id,))
            if candidates:
                execute_values(
                    cur,
                    """
                    INSERT INTO match_candidates (
                        source_movie_id, tmdb_id, title, original_title, release_date,
                        popularity, score, title_score, date_score
                    ) VALUES %s
                    """,
                    [
                        (ref_id, c.tmdb_id, c.title, c.original_title, c.release_date,
                         c.popularity, c.score, c.title_score, c.date_score)
                        for c in candidates
                    ],
                )

    def link_legacy_rows(self, conn, source_name: str) -> dict[str, int]:
        """Collega le righe weekly senza ID sorgente (caricate prima della Fase 2). Idempotente.

        1. per titolo esatto (senza maiuscole) a un film sorgente reale già noto;
        2. altrimenti a un film sorgente 'legacy:<titolo>', creato qui;
        3. se le righe avevano già un movie_id coerente, il match viene adottato.
        """
        counts = {}
        with conn.cursor() as cur:
            counts.update(self._promote_legacy(cur, source_name))

            cur.execute(
                """
                UPDATE weekly_box_office w SET source_movie_ref = s.id
                FROM (
                    SELECT DISTINCT ON (lower(btrim(title))) id, lower(btrim(title)) AS key
                    FROM source_movies
                    WHERE source_name = %s AND source_movie_id NOT LIKE 'legacy:%%'
                    ORDER BY lower(btrim(title)), id
                ) s
                WHERE w.source_name = %s AND w.source_movie_ref IS NULL
                  AND lower(btrim(w.external_movie_title)) = s.key
                """,
                (source_name, source_name),
            )
            counts["linked_to_real"] = cur.rowcount

            cur.execute(
                """
                INSERT INTO source_movies (source_name, source_movie_id, title)
                SELECT source_name, 'legacy:' || lower(btrim(external_movie_title)), min(external_movie_title)
                FROM weekly_box_office
                WHERE source_name = %s AND source_movie_ref IS NULL
                GROUP BY source_name, lower(btrim(external_movie_title))
                ON CONFLICT (source_name, source_movie_id) DO NOTHING
                """,
                (source_name,),
            )
            counts["legacy_created"] = cur.rowcount

            cur.execute(
                """
                UPDATE weekly_box_office w SET source_movie_ref = s.id
                FROM source_movies s
                WHERE w.source_name = %s AND w.source_movie_ref IS NULL
                  AND s.source_name = w.source_name
                  AND s.source_movie_id = 'legacy:' || lower(btrim(w.external_movie_title))
                """,
                (source_name,),
            )
            counts["linked_to_legacy"] = cur.rowcount

            cur.execute(
                """
                UPDATE source_movies s
                SET movie_id = x.movie_id, match_status = 'auto', match_method = 'legacy_exact_title',
                    matched_at = now(), updated_at = now()
                FROM (
                    SELECT source_movie_ref, min(movie_id) AS movie_id
                    FROM weekly_box_office
                    WHERE source_movie_ref IS NOT NULL AND movie_id IS NOT NULL
                    GROUP BY source_movie_ref
                    HAVING count(DISTINCT movie_id) = 1
                ) x
                WHERE s.id = x.source_movie_ref AND s.match_status = 'unmatched'
                """
            )
            counts["adopted_existing_movie_id"] = cur.rowcount

            # source_movies è la fonte di verità: allinea le righe weekly (es. settimane successive a
            # quella in cui il vecchio codice aveva valorizzato movie_id).
            cur.execute(
                """
                UPDATE weekly_box_office w
                SET movie_id = s.movie_id, updated_at = now()
                FROM source_movies s
                WHERE w.source_movie_ref = s.id AND w.source_name = %s
                  AND s.match_status IN ('auto', 'manual')
                  AND w.movie_id IS DISTINCT FROM s.movie_id
                """,
                (source_name,),
            )
            counts["synced_weekly_movie_id"] = cur.rowcount
        return counts

    def _promote_legacy(self, cur, source_name: str) -> dict[str, int]:
        """Unifica i film 'legacy' con l'omonimo reale comparso dopo (es. da un recupero da archivio).

        Coppie (legacy, reale) con lo stesso titolo. Se entrambi hanno già un match TMDB e sono diversi
        non si tocca nulla: è un conflitto da rivedere a mano (l'health check lo segnala).
        """
        cur.execute("DROP TABLE IF EXISTS pg_temp.legacy_pairs")
        cur.execute(
            """
            CREATE TEMP TABLE legacy_pairs ON COMMIT DROP AS
            SELECT l.id AS legacy_id, r.id AS real_id
            FROM source_movies l
            JOIN LATERAL (
                SELECT r0.id, r0.movie_id FROM source_movies r0
                WHERE r0.source_name = l.source_name
                  AND r0.source_movie_id NOT LIKE 'legacy:%%'
                  AND lower(btrim(r0.title)) = lower(btrim(l.title))
                ORDER BY r0.id LIMIT 1
            ) r ON TRUE
            WHERE l.source_name = %s AND l.source_movie_id LIKE 'legacy:%%'
              AND NOT (l.movie_id IS NOT NULL AND r.movie_id IS NOT NULL AND l.movie_id <> r.movie_id)
            """,
            (source_name,),
        )
        # 1. il match già deciso per il film legacy passa al film reale, se questo non ne ha uno suo
        cur.execute(
            """
            UPDATE source_movies r
            SET movie_id = l.movie_id, match_status = l.match_status, match_method = l.match_method,
                match_confidence = l.match_confidence, matched_at = l.matched_at, updated_at = now()
            FROM legacy_pairs p
            JOIN source_movies l ON l.id = p.legacy_id
            WHERE r.id = p.real_id
              AND r.match_status NOT IN ('auto', 'manual')
              AND r.match_method IS DISTINCT FROM 'manual'
              AND l.match_status IN ('auto', 'manual')
            """
        )
        # 2. le righe settimanali passano al film reale
        cur.execute(
            """
            UPDATE weekly_box_office w SET source_movie_ref = p.real_id
            FROM legacy_pairs p
            WHERE w.source_movie_ref = p.legacy_id
            """
        )
        moved = cur.rowcount
        # 3. i film legacy rimasti senza righe si eliminano (i candidati vanno via in cascata)
        cur.execute(
            """
            DELETE FROM source_movies s
            WHERE s.source_name = %s AND s.source_movie_id LIKE 'legacy:%%'
              AND NOT EXISTS (SELECT 1 FROM weekly_box_office w WHERE w.source_movie_ref = s.id)
            """,
            (source_name,),
        )
        return {"promoted_rows": moved, "legacy_removed": cur.rowcount}

    def get(self, conn, ref_id: int) -> dict | None:
        keys = ("id", "source_name", "source_movie_id", "title", "movie_id", "match_status", "match_method")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_name, source_movie_id, title, movie_id, match_status, match_method "
                "FROM source_movies WHERE id = %s",
                (ref_id,),
            )
            row = cur.fetchone()
        return dict(zip(keys, row)) if row else None

    def list_needing_review(self, conn, source_name: str) -> list[dict]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.id, s.source_movie_id, s.title,
                       c.tmdb_id, c.title, c.original_title, c.release_date, c.score
                FROM source_movies s
                LEFT JOIN match_candidates c ON c.source_movie_id = s.id
                WHERE s.source_name = %s AND s.match_status = 'needs_review'
                ORDER BY s.id, c.score DESC
                """,
                (source_name,),
            )
            rows = cur.fetchall()

        grouped: dict[int, dict] = {}
        for r in rows:
            entry = grouped.setdefault(
                r[0], {"id": r[0], "source_movie_id": r[1], "title": r[2], "candidates": []}
            )
            if r[3] is not None:
                entry["candidates"].append(
                    {"tmdb_id": r[3], "title": r[4], "original_title": r[5],
                     "release_date": r[6], "score": float(r[7])}
                )
        return list(grouped.values())
