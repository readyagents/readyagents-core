"""Process-wide logging setup."""

from __future__ import annotations

import logging
from typing import Any

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)s %(name)s run=%(run_id)s node=%(node_id)s: %(message)s"


class _RunContextFilter(logging.Filter):
    """Ensure every record has run_id / node_id so the formatter never KeyErrors."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = "-"
        if not hasattr(record, "node_id"):
            record.node_id = "-"
        return True


def configure_logging(level: str = "INFO", **kwargs: Any) -> None:
    """Configure the root `readyagents` logger once."""
    global _CONFIGURED
    numeric = getattr(logging, level.upper(), logging.INFO)
    logger = logging.getLogger("readyagents")
    logger.setLevel(numeric)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(_RunContextFilter())
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
        logger.propagate = False
    else:
        logger.setLevel(numeric)
        for handler in logger.handlers:
            if not any(isinstance(f, _RunContextFilter) for f in handler.filters):
                handler.addFilter(_RunContextFilter())
            handler.setFormatter(logging.Formatter(_FORMAT))
    _CONFIGURED = True
    if kwargs:
        logger.debug("extra logging kwargs ignored: %s", sorted(kwargs))


def get_logger(name: str) -> logging.Logger:
    if not name.startswith("readyagents"):
        name = f"readyagents.{name}"
    return logging.getLogger(name)
