from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from music_monitor.app import MusicMonitorApp
from music_monitor.config import load_config
from music_monitor.logging_setup import configure_logging


def main() -> None:
    """Parse CLI args, initialize services, and run the async application loop."""
    parser = argparse.ArgumentParser(description="Monitor a music folder and organize tagged output")
    parser.add_argument("--config", default=None, help="Path to TOML config file")
    args = parser.parse_args()

    config = load_config(None if args.config is None else Path(args.config))
    configure_logging(
        level=config.logging.level,
        log_file=config.logging.file_path,
        max_bytes=config.logging.max_bytes,
        backup_count=config.logging.backup_count,
    )

    app = MusicMonitorApp(config)
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
