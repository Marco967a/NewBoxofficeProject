import hashlib


class RawSnapshotRepository:
    """Pagine grezze scaricate a ogni run, per poter rielaborare senza riscaricare."""

    def insert(self, conn, ingestion_run_id: int, source_name: str, url: str, payload: str) -> int:
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO raw_snapshots (ingestion_run_id, source_name, url, content_sha256, payload)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (ingestion_run_id, source_name, url, digest, payload),
            )
            return cur.fetchone()[0]
