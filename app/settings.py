from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path
import logging
import os

from app.credentials import get_secret


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Ruoli PostgreSQL: (variabile con il nome utente, nome predefinito, variabile con la password)
_ROLE_SETTINGS = {
    "owner": ("DB_OWNER_USER", "boxoffice_owner", "DB_OWNER_PASSWORD"),
    "ro": ("DB_RO_USER", "boxoffice_ro", "DB_RO_PASSWORD"),
}


@dataclass(frozen=True)
class Settings:
    tmdb_api_key: str
    db_host: str
    db_name: str
    db_user: str
    db_password: str
    db_port: int = 5432
    log_level: str = "INFO"
    request_timeout: int = 30
    tmdb_read_token: str = ""

    @property
    def db_config(self) -> dict:
        return {
            "host": self.db_host,
            "dbname": self.db_name,
            "user": self.db_user,
            "password": self.db_password,
            "port": self.db_port,
        }


def get_log_level() -> str:
    """Legge solo LOG_LEVEL, senza richiedere i segreti obbligatori."""
    return os.getenv("LOG_LEVEL", "INFO")


def get_settings(require_tmdb: bool = True) -> Settings:
    """Impostazioni dell'applicazione.

    Le password e le chiavi API si cercano prima nell'ambiente (CI, override) e poi nel deposito
    credenziali del sistema (vedi app/credentials.py): in `.env` restano solo valori non segreti.
    `require_tmdb=False` per chi usa solo il database (migrazioni, health check, analisi).
    """
    db_user = os.getenv("DB_USER", "")
    settings = Settings(
        tmdb_api_key=get_secret("tmdb_api_key", "TMDB_API_KEY") or "",
        tmdb_read_token=get_secret("tmdb_read_token", "TMDB_READ_TOKEN") or "",
        db_host=os.getenv("DB_HOST", ""),
        db_name=os.getenv("DB_NAME", ""),
        db_user=db_user,
        db_password=(get_secret(f"db:{db_user}", "DB_PASSWORD") or "") if db_user else "",
        db_port=int(os.getenv("DB_PORT", "5432")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
    )

    required = {
        "DB_HOST": settings.db_host,
        "DB_NAME": settings.db_name,
        "DB_USER": settings.db_user,
        "DB_PASSWORD (ambiente o deposito credenziali 'db:<utente>')": settings.db_password,
    }
    if require_tmdb:
        required["TMDB_API_KEY o TMDB_READ_TOKEN (ambiente o deposito credenziali)"] = (
            settings.tmdb_api_key or settings.tmdb_read_token
        )
    missing = [name for name, value in required.items() if not value]

    if missing:
        raise RuntimeError(
            f"Configurazione mancante: {', '.join(missing)}. "
            "Imposta le variabili non segrete nel file .env della root del progetto e i segreti nel "
            "deposito credenziali (python scripts/manage_secrets.py set <nome>)."
        )

    return settings


def get_db_config(role: str = "app") -> dict:
    """Parametri di connessione per un ruolo: 'app' (predefinito), 'owner' (migrazioni) o 'ro' (sola lettura).

    Se il ruolo owner/ro non è configurato (nessuna password nell'ambiente né nel deposito) si ripiega sul
    ruolo applicativo: mai su un ruolo con più privilegi di quelli configurati.
    """
    config = get_settings(require_tmdb=False).db_config
    if role == "app":
        return config

    user_var, default_user, password_var = _ROLE_SETTINGS[role]
    user = os.getenv(user_var, default_user)
    password = get_secret(f"db:{user}", password_var)
    if not password:
        logger.warning("Ruolo '%s' (%s) non configurato: uso il ruolo applicativo", role, user)
        return config
    return {**config, "user": user, "password": password}
