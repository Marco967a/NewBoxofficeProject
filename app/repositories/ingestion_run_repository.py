# app/repositories/ingestion_run_repository.py
class IngestionRunRepository:
    def start_run(self, conn, pipeline_name: str, source_name: str) -> int:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ingestion_runs (pipeline_name, source_name, status)
                VALUES (%s, %s, 'running')
                RETURNING id
            """, (pipeline_name, source_name))
            return cur.fetchone()[0]

    def finish_run(
        self,
        conn,
        run_id: int,
        status: str,
        records_read: int,
        records_written: int,
        error_message: str | None = None,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ingestion_runs
                SET finished_at = clock_timestamp(),
                    status = %s,
                    records_read = %s,
                    records_written = %s,
                    error_message = %s
                WHERE id = %s
            """, (status, records_read, records_written, error_message, run_id))
