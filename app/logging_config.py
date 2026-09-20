import logging

from app.settings import get_log_level


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, get_log_level().upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
