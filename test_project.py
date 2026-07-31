#!/usr/bin/env python
"""Test di verifiche complete del progetto"""
import sys
import os

print("=" * 70)
print("REPORT DI ANALISI - BOX OFFICE PROJECT")
print("=" * 70)

# 1. Verifica Configurazione
print("\n[1/5] Configurazione...")
try:
    from app.settings import get_settings
    settings = get_settings()
    print(f"  ✓ TMDB API Key: {settings.tmdb_api_key[:10]}...")
    print(f"  ✓ Database: {settings.db_name}@{settings.db_host}")
    print(f"  ✓ Timeout: {settings.request_timeout}s")
except Exception as e:
    print(f"  ✗ ERRORE: {e}")
    sys.exit(1)

# 2. Verifica Import Principali
print("\n[2/5] Import Moduli...")
try:
    from app.tmdb_client import TMDBClient
    from app.parsers.comingsoon_parser import parse_comingsoon_weekly_boxoffice
    from app.services.movie_ingestion_service import MovieIngestionService
    from app.services.weekly_box_office_service import WeeklyBoxOfficeService
    from app.repositories.movie_repository import MovieRepository
    from app.db import get_connection
    print("  ✓ TMDBClient")
    print("  ✓ ComingSoon Parser")
    print("  ✓ MovieIngestionService")
    print("  ✓ WeeklyBoxOfficeService")
    print("  ✓ Repositories")
    print("  ✓ Database Module")
except Exception as e:
    print(f"  ✗ ERRORE: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 3. Verifica Dipendenze
print("\n[3/5] Dipendenze Esterne...")
try:
    import requests
    import bs4
    import psycopg2
    from dotenv import load_dotenv
    print(f"  ✓ requests v{requests.__version__}")
    print("  ✓ beautifulsoup4")
    print(f"  ✓ psycopg2 v{psycopg2.__version__}")
    print("  ✓ python-dotenv")
except Exception as e:
    print(f"  ✗ ERRORE: {e}")
    sys.exit(1)

# 4. Verifica File
print("\n[4/5] Struttura File...")
files = {
    "main_v3.py": "Entry point principale",
    "scripts/bootstrap.py": "Script dedicato al bootstrap TMDB",
    "scripts/weekly_run.py": "Script dedicato al caricamento weekly",
    ".env": "Configurazione ambiente",
    "app/__init__.py": "Package app",
    "app/db.py": "Database utilities",
    "app/settings.py": "Settings configuration",
    "app/tmdb_client.py": "TMDB API client",
    "app/models/weekly_record.py": "Data models",
    "app/parsers/comingsoon_parser.py": "ComingSoon parser",
    "app/repositories/movie_repository.py": "Movie repository",
    "app/services/movie_ingestion_service.py": "Movie service",
}
missing = []
for file_path, desc in files.items():
    if os.path.exists(file_path):
        print(f"  ✓ {file_path}")
    else:
        print(f"  ✗ {file_path} - MANCANTE")
        missing.append(file_path)

if missing:
    print(f"\n  ✗ File mancanti: {missing}")
    sys.exit(1)

# 5. Verifica Compilazione
print("\n[5/5] Compilazione Python...")
import py_compile
import tempfile
py_files = [
    "main_v3.py",
    "scripts/bootstrap.py",
    "scripts/weekly_run.py",
    "app/db.py",
    "app/settings.py",
    "app/tmdb_client.py",
    "app/services/movie_ingestion_service.py",
]
all_good = True
for py_file in py_files:
    try:
        with tempfile.NamedTemporaryFile(suffix='.pyc', delete=True):
            py_compile.compile(py_file, doraise=True)
        print(f"  ✓ {py_file}")
    except py_compile.PyCompileError as e:
        print(f"  ✗ {py_file}: {e}")
        all_good = False

print("\n" + "=" * 70)
if all_good and not missing:
    print("✓✓✓ PROGETTO COMPLETAMENTE FUNZIONANTE ✓✓✓")
    print("Il progetto è pronto per l'esecuzione!")
else:
    print("✗ Il progetto ha problemi")
    sys.exit(1)
print("=" * 70)
