#!/usr/bin/env python
"""Inizializza/aggiorna il database applicando le migrazioni (equivale a scripts/migrate.py)."""
from scripts.migrate import main

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"✗ ERRORE: {e}")
        exit(1)
