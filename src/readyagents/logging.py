"""Process-wide logging setup."""

from __future__ import annotations

import logging
from typing import Any

_CONFIGURED = False


def configure_logging(level: str = "INFO", **kwargs: Any) -> None:
    """Configure the root `readyagents` logger once."""
    global _CONFIGURED
    numeric = getattr(logging, level.upper(), logging.INFO)
    logger = logging.getLogger("readyagents")
    logger.setLevel(numeric)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.propagate = False
    else:
        logger.setLevel(numeric)
    _CONFIGURED = True
    if kwargs:
        logger.debug("extra logging kwargs ignored: %s", sorted(kwargs))


def get_logger(name: str) -> logging.Logger:
    if not name.startswith("readyagents"):
        name = f"readyagents.{name}"
    return logging.getLogger(name)
