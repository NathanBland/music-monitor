from __future__ import annotations

import logging
from pathlib import Path

from music_monitor.logging_setup import _iter_handlers, configure_logging


def test_configure_logging_replaces_existing_handlers(tmp_path: Path) -> None:
    logger = logging.getLogger()
    original_handlers = list(logger.handlers)
    previous_level = logger.level

    stale_handler = logging.NullHandler()
    logger.addHandler(stale_handler)

    try:
        log_path = tmp_path / "logs" / "music-monitor.log"
        configure_logging(level="info", log_file=log_path, max_bytes=1024, backup_count=2)

        assert log_path.parent.exists()
        assert logger.level == logging.INFO
        assert stale_handler not in logger.handlers
        assert len(logger.handlers) == 2
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        for handler in original_handlers:
            logger.addHandler(handler)
        logger.setLevel(previous_level)


def test_iter_handlers_yields_handlers() -> None:
    logger = logging.getLogger("music-monitor-test-iter")
    handler = logging.NullHandler()
    logger.addHandler(handler)

    try:
        yielded_handlers = list(_iter_handlers(logger))
        assert yielded_handlers == [handler]
    finally:
        logger.removeHandler(handler)
