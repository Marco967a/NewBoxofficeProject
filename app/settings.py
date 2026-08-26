from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)


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

    @property
    def db_config(self) -> dict:
        return {
            "host": self.db_host,
            "dbname": self.db_name,
            "user": self.db_user,
            "password": self.db_password,
            "port": self.db_port,
        }


def get_settings() -> Settings:
    settings = Settings(
        tmdb_api_key=os.getenv("TMDB_API_KEY", ""),
        db_host=os.getenv("DB_HOST", ""),
        db_name=os.getenv("DB_NAME", ""),
        db_user=os.getenv("DB_USER", ""),
        db_password=os.getenv("DB_PASSWORD", ""),
        db_port=int(os.getenv("DB_PORT", "5432")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
    )

    missing = [
        name for name, value in {
            "TMDB_API_KEY": settings.tmdb_api_key,
            "DB_HOST": settings.db_host,
            "DB_NAME": settings.db_name,
            "DB_USER": settings.db_user,
            "DB_PASSWORD": settings.db_password,
        }.items() if not value
    ]

    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Create or update the .env file in the project root."
        )

    return settings
