from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from music_monitor.config import AppConfig
from music_monitor.constants import SUPPORTED_AUDIO_EXTENSIONS


LOGGER = logging.getLogger(__name__)


class DirectoryWatcher:
    """Watch the configured input tree and enqueue album directories for processing."""

    def __init__(self, config: AppConfig, album_queue: asyncio.Queue[Path]) -> None:
        """Store watcher configuration and the shared processing queue."""
        self.config = config
        self.album_queue = album_queue

    async def seed_existing_albums(self) -> None:
        """Scan existing files once at startup and enqueue each discovered album folder."""
        seen_albums: set[Path] = set()

        for path in self.config.watch_path.rglob("*"):
            if not path.is_file():
                continue
            if is_failed_path(path, self.config):
                continue
            if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
                continue

            album_directory = path.parent
            if album_directory in seen_albums:
                continue

            seen_albums.add(album_directory)
            await self.album_queue.put(album_directory)

        LOGGER.info("watcher_seeded_existing_albums", extra={"album_count": len(seen_albums)})

    async def watch(self) -> None:
        """Listen for filesystem changes and enqueue album folders for new audio files."""
        from watchfiles import Change, awatch

        LOGGER.info("watcher_started", extra={"watch_path": str(self.config.watch_path)})
        async for changes in awatch(str(self.config.watch_path), recursive=True):
            for change, changed_path in changes:
                path = Path(changed_path)

                if is_failed_path(path, self.config):
                    continue
                if change == Change.deleted:
                    continue

                for candidate in resolve_candidate_paths(path):
                    if is_failed_path(candidate, self.config):
                        continue
                    if not candidate.exists() or not candidate.is_file():
                        continue
                    if candidate.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
                        LOGGER.error("non_audio_file_detected", extra={"file": str(candidate)})
                        continue

                    await self.album_queue.put(candidate.parent)


def resolve_candidate_paths(path: Path) -> list[Path]:
    """Expand a changed path into candidate files to validate and enqueue."""
    if path.is_file():
        return [path]
    if path.is_dir():
        return [child for child in path.rglob("*") if child.is_file()]
    return []


def is_failed_path(path: Path, config: AppConfig) -> bool:
    """Return whether a path is inside the configured failed-subdirectory tree."""
    failed_root = config.watch_path / config.failed_subdir
    try:
        path.resolve().relative_to(failed_root.resolve())
    except ValueError:
        return False
    return True
