#!/usr/bin/env python
"""Inizializza il database creando le tabelle"""
from app.db import create_weekly_tables

if __name__ == "__main__":
    try:
        print("Creazione tabelle...")
        create_weekly_tables()
        print("✓ Tabelle create con successo!")
    except Exception as e:
        print(f"✗ ERRORE: {e}")
        exit(1)