"""Accesso ai segreti: variabile d'ambiente (CI, override) oppure Gestione credenziali di Windows.

Nel deposito (Windows Credential Manager, cifrato con DPAPI e legato all'account utente) i segreti stanno
sotto il servizio "NewBoxofficeProject" con questi nomi:
    db:<ruolo>          password del ruolo PostgreSQL (es. db:boxoffice_app)
    tmdb_api_key        chiave API TMDB
    tmdb_read_token     API Read Access Token TMDB (preferito: viaggia in un header, non nell'URL)
    notify_webhook_url  opzionale: URL webhook (Slack/Discord/Teams) per i guasti della pipeline

Nessuna funzione di questo modulo scrive segreti nei log.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

SERVICE = "NewBoxofficeProject"
KNOWN_NAMES = ("tmdb_api_key", "tmdb_read_token", "notify_webhook_url")


def get_secret(name: str, env_var: Optional[str] = None) -> Optional[str]:
    """Valore del segreto: prima la variabile d'ambiente `env_var`, poi il deposito. None se assente."""
    if env_var:
        value = os.getenv(env_var)
        if value:
            return value
    try:
        import keyring

        return keyring.get_password(SERVICE, name)
    except Exception as exc:  # nessun backend (CI, Linux headless) o deposito bloccato: si ripiega su "assente"
        logger.debug("Deposito segreti non disponibile per '%s': %s", name, type(exc).__name__)
        return None


def set_secret(name: str, value: str) -> None:
    """Scrive nel deposito. A differenza di get_secret, un guasto qui NON va inghiottito: è una scrittura,
    non va fatta credere riuscita se non lo è. Viene solo tradotto in un errore leggibile."""
    import keyring

    try:
        keyring.set_password(SERVICE, name, value)
    except Exception as exc:
        raise RuntimeError(f"Impossibile scrivere '{name}' nel deposito credenziali: {type(exc).__name__}") from exc


def delete_secret(name: str) -> bool:
    import keyring
    from keyring.errors import PasswordDeleteError

    try:
        keyring.delete_password(SERVICE, name)
        return True
    except PasswordDeleteError:
        return False
    except Exception as exc:
        raise RuntimeError(f"Impossibile eliminare '{name}' dal deposito credenziali: {type(exc).__name__}") from exc


def vault_backend_name() -> str:
    try:
        import keyring

        return type(keyring.get_keyring()).__name__
    except Exception:
        return "nessuno"
