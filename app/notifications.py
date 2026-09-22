"""Notifica sui guasti della pipeline settimanale (usata da scripts/notify.py, chiamato da run_weekly.ps1).

Nessuna notifica per i soli WARN: coerente con scripts/health_check.py, che esce con 0 quando non c'è
nessun FAIL. Altrimenti le settimane storiche già note come mancanti avviserebbero a ogni esecuzione.
Un guasto è: la pipeline (main_v3.py) esce con codice diverso da 0, oppure l'health check trova un FAIL.
"""
import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT = 10
MAX_LOG_LINES = 6
# Parole che marcano le righe di log utili a capire cosa è andato storto, da preferire alle ultime N
# righe qualunque (che spesso sono solo "=== fine ===").
_INTERESTING_MARKERS = ("Error", "ERRORE", "Traceback", "[FAIL")


@dataclass(frozen=True)
class FailureReport:
    title: str
    message: str


def _relevant_log_lines(log_text: str, max_lines: int = MAX_LOG_LINES) -> str:
    lines = [ln for ln in log_text.splitlines() if ln.strip()]
    interesting = [ln for ln in lines if any(marker in ln for marker in _INTERESTING_MARKERS)]
    chosen = interesting[-max_lines:] if interesting else lines[-max_lines:]
    return "\n".join(chosen)


def describe_failure(pipeline_exit: int, health_exit: int, log_text: str = "") -> Optional[FailureReport]:
    """FailureReport da notificare, o None se non c'è nulla da segnalare (entrambi gli esiti sono 0)."""
    if pipeline_exit == 0 and health_exit == 0:
        return None

    parts = []
    if pipeline_exit != 0:
        parts.append(f"pipeline: codice di uscita {pipeline_exit}")
    if health_exit != 0:
        parts.append(f"health check: codice di uscita {health_exit} (almeno un controllo FAIL)")
    summary = "; ".join(parts)

    detail = _relevant_log_lines(log_text) if log_text else ""
    message = f"{summary}\n{detail}" if detail else summary
    return FailureReport(title="NewBoxOffice: guasto nella pipeline settimanale", message=message)


def send_webhook(report: FailureReport, webhook_url: Optional[str]) -> bool:
    """Invio best-effort: non solleva mai (una notifica rotta non deve mascherare il guasto originale).

    Ritorna True solo se l'invio è riuscito; False se non c'era un URL configurato o l'invio è fallito.
    """
    if not webhook_url:
        return False
    try:
        # "text" (Slack) e "content" (Discord) insieme: ogni servizio legge la chiave che riconosce e
        # ignora l'altra, senza dover sapere in anticipo quale webhook l'utente ha configurato.
        body = f"{report.title}\n{report.message}"
        response = requests.post(webhook_url, json={"text": body, "content": body}, timeout=WEBHOOK_TIMEOUT)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.warning("Invio della notifica webhook fallito: %s", type(exc).__name__)
        return False
