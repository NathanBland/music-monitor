from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Iterable

from pythonjsonlogger import jsonlogger


def configure_logging(level: str, log_file: Path, max_bytes: int, backup_count: int) -> None:
    """Configure JSON console/file logging and replace any existing root handlers."""
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level.upper())

    formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count
    )
    file_handler.setFormatter(formatter)

    for handler in list(_iter_handlers(root)):
        root.removeHandler(handler)

    root.addHandler(console_handler)
    root.addHandler(file_handler)


def _iter_handlers(logger: logging.Logger) -> Iterable[logging.Handler]:
    """Yield logger handlers via a dedicated iterator helper for safe copying."""
    for handler in logger.handlers:
        yield handler
