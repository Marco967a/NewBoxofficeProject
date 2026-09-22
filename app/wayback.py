"""Recupero di classifiche ComingSoon già archiviate dalla Wayback Machine (Internet Archive).

ComingSoon non ha archivio: se una settimana non viene caricata la si può recuperare solo se l'Internet
Archive ne ha uno snapshot. L'HTML viene richiesto nella variante `id_` (contenuto originale, senza
la barra e la riscrittura dei link di Wayback) e passa dal parser di sempre, quindi la settimana e i
campi sono quelli scritti dalla pagina stessa; la data dello snapshot serve solo a sceglierlo.
"""
import logging
import time
from datetime import date, timedelta
from typing import Callable, Optional

import requests

from app.http_retry import DEFAULT_RETRY_STATUSES as RETRY_STATUSES
from app.http_retry import DEFAULT_RETRY_WAITS as RETRY_WAITS
from app.http_retry import get_with_retry
from app.parsers.comingsoon_parser import FetchResult, parse_boxoffice_page

logger = logging.getLogger(__name__)

CDX_URL = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT_URL = "https://web.archive.org/web/{timestamp}id_/{url}"
USER_AGENT = "NewBoxofficeProject-recovery/1.0 (progetto personale, poche richieste)"

MIN_ROWS = 10  # sotto questa soglia una classifica è considerata incompleta
CDX_TIMEOUT = 180  # l'indice CDX è spesso lento


def _get(session: requests.Session, url: str, sleep: Callable[[float], None] = time.sleep, **kwargs) -> requests.Response:
    """GET con qualche tentativo e attese crescenti: Wayback risponde spesso 503/timeout in modo transitorio."""
    return get_with_retry(session, url, sleep=sleep, headers={"User-Agent": USER_AGENT}, log_label="Wayback", **kwargs)


def list_snapshots(url: str, start: date, end: date, session: Optional[requests.Session] = None) -> list[str]:
    """Timestamp (YYYYMMDDhhmmss) degli snapshot con esito 200 tra `start` e `end` inclusi, in ordine crescente."""
    session = session or requests.Session()
    response = _get(
        session,
        CDX_URL,
        params={
            "url": url,
            "from": start.strftime("%Y%m%d"),
            "to": end.strftime("%Y%m%d"),
            "output": "json",
            "fl": "timestamp",
            "filter": "statuscode:200",
        },
        timeout=CDX_TIMEOUT,
    )
    rows = response.json() if response.text.strip() else []
    return sorted({row[0] for row in rows[1:]})  # la prima riga è l'intestazione


def snapshot_url(timestamp: str, url: str) -> str:
    return SNAPSHOT_URL.format(timestamp=timestamp, url=url)


def fetch_snapshot(timestamp: str, url: str, session: Optional[requests.Session] = None) -> str:
    session = session or requests.Session()
    return _get(session, snapshot_url(timestamp, url), timeout=120).text


def candidate_timestamps(week_start: date, snapshots: list[str]) -> list[str]:
    """Snapshot in cui la classifica di `week_start` può essere online, dal più recente.

    La classifica del weekend (giovedì-domenica) compare la domenica sera/lunedì e resta fino al
    weekend dopo: finestra da W+3 a W+10 giorni. Il più recente è il più probabile con i dati definitivi.
    """
    lo = (week_start + timedelta(days=3)).strftime("%Y%m%d")
    hi = (week_start + timedelta(days=10)).strftime("%Y%m%d")
    return sorted((ts for ts in snapshots if lo <= ts[:8] <= hi), reverse=True)


def recover_week(
    week_start: date,
    original_url: str,
    snapshots: list[str],
    fetch: Callable[[str, str], str] = fetch_snapshot,
    max_attempts: int = 5,
    delay_seconds: float = 2.0,
) -> Optional[FetchResult]:
    """Prova gli snapshot candidati e ritorna il primo la cui pagina riguarda davvero `week_start`.

    La verifica usa la settimana scritta nella pagina, non la data dello snapshot: uno snapshot
    di un'altra settimana (o incompleto) viene scartato invece di essere etichettato male.
    """
    for attempt, timestamp in enumerate(candidate_timestamps(week_start, snapshots)[:max_attempts]):
        if attempt:
            time.sleep(delay_seconds)
        try:
            html = fetch(timestamp, original_url)
            records = parse_boxoffice_page(html)
        except (requests.RequestException, RuntimeError) as exc:
            logger.warning("Snapshot %s scartato: %s", timestamp, exc)
            continue

        page_week = records[0].week_start if records else None
        if page_week != week_start:
            logger.info("Snapshot %s riguarda la settimana %s, non %s: scartato", timestamp, page_week, week_start)
            continue
        if len(records) < MIN_ROWS:
            logger.warning("Snapshot %s con sole %s righe: scartato", timestamp, len(records))
            continue
        return FetchResult(url=snapshot_url(timestamp, original_url), html=html, records=records)
    return None
