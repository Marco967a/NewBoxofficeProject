#!/usr/bin/env python
"""Inizializza il database creando le tabelle"""
from app.db import get_connection
from app.repositories.ingestion_run_repository import IngestionRunRepository
from app.repositories.movie_repository import MovieRepository
from app.repositories.weekly_box_office_repository import WeeklyBoxOfficeRepository

if __name__ == "__main__":
    try:
        print("Creazione tabelle...")
        with get_connection() as conn:
            IngestionRunRepository().create_table(conn)
            MovieRepository().create_table(conn)
            WeeklyBoxOfficeRepository().create_table(conn)
        print("✓ Tabelle create con successo!")
    except Exception as e:
        print(f"✗ ERRORE: {e}")
        exit(1)