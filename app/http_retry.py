"""GET con qualche tentativo e attese crescenti su errori transitori (rate limit, 5xx, timeout).

Condiviso da app/wayback.py e app/tmdb_client.py: entrambi i servizi esterni rispondono in modo
transitorio con errori che un secondo tentativo, poco dopo, risolve da solo.
"""
import logging
import time
from typing import Callable

import requests

logger = logging.getLogger(__name__)

DEFAULT_RETRY_STATUSES = {429, 500, 502, 503, 504}
DEFAULT_RETRY_WAITS = (5, 15, 45)  # secondi prima dei tentativi successivi al primo


def get_with_retry(
    session: requests.Session,
    url: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    retry_statuses: set[int] = DEFAULT_RETRY_STATUSES,
    retry_waits: tuple[float, ...] = DEFAULT_RETRY_WAITS,
    log_label: str = "richiesta",
    **kwargs,
) -> requests.Response:
    """Come session.get(), ma riprova su timeout/errori di connessione e sui codici in `retry_statuses`."""
    for attempt in range(len(retry_waits) + 1):
        try:
            response = session.get(url, **kwargs)
            if response.status_code not in retry_statuses:
                response.raise_for_status()
                return response
            error: Exception = requests.HTTPError(f"HTTP {response.status_code}", response=response)
        except (requests.Timeout, requests.ConnectionError) as exc:
            error = exc
        if attempt == len(retry_waits):
            raise error
        logger.warning("%s: %s, riprovo tra %ss", log_label, type(error).__name__, retry_waits[attempt])
        sleep(retry_waits[attempt])
    raise AssertionError("non raggiungibile")  # pragma: no cover
