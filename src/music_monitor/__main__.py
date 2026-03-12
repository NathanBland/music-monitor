from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from music_monitor import __version__
from music_monitor.app import MusicMonitorApp
from music_monitor.config import load_config
from music_monitor.logging_setup import configure_logging


def main() -> None:
    """Parse CLI args, initialize services, and run the async application loop."""
    parser = argparse.ArgumentParser(description="Monitor a music folder and organize tagged output")
    parser.add_argument("--config", default=None, help="Path to TOML config file")
    parser.add_argument("--dry-run", action="store_true", help="Log intended changes without writing/moving files")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    config = load_config(None if args.config is None else Path(args.config))
    if args.dry_run:
        config.dry_run = True
    _validate_startup_paths(config.watch_path, config.output_path)

    configure_logging(
        level=config.logging.level,
        log_file=config.logging.file_path,
        max_bytes=config.logging.max_bytes,
        backup_count=config.logging.backup_count,
    )

    app = MusicMonitorApp(config)
    asyncio.run(app.run())


def _validate_startup_paths(watch_path: Path, output_path: Path) -> None:
    """Validate critical path assumptions before starting asynchronous services."""
    if not watch_path.exists():
        raise ValueError(f"watch_path does not exist: {watch_path}")
    if not watch_path.is_dir():
        raise ValueError(f"watch_path must be a directory: {watch_path}")

    output_path.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    main()
