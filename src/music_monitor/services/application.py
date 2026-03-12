from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from music_monitor.clients.lidarr import LidarrClient
from music_monitor.config import AppConfig
from music_monitor.services.processing import ProcessingService
from music_monitor.services.watching import DirectoryWatcher


LOGGER = logging.getLogger(__name__)


class MusicMonitorApp:
    """Coordinate watcher and workers to process discovered album directories."""

    def __init__(self, config: AppConfig) -> None:
        """Initialize queue-backed processing services from application config."""
        self.config = config
        self.album_queue: asyncio.Queue[Path] = asyncio.Queue()
        self.processing_lock = asyncio.Lock()
        self.processing_directories: set[Path] = set()

        self.lidarr_client = LidarrClient(
            base_url=config.lidarr.base_url,
            api_key=config.lidarr.api_key,
            timeout_seconds=config.lidarr.timeout_seconds,
        )
        self.processing_service = ProcessingService(config=config, lidarr_client=self.lidarr_client)
        self.watcher = DirectoryWatcher(config=config, album_queue=self.album_queue)

    async def run(self) -> None:
        """Start watching, seed existing albums, and run worker tasks indefinitely."""
        self.config.output_path.mkdir(parents=True, exist_ok=True)

        naming_formats = await self.lidarr_client.fetch_naming_formats()
        self.processing_service.naming_formats = naming_formats

        LOGGER.info(
            "music_monitor_starting",
            extra={
                "watch_path": str(self.config.watch_path),
                "output_path": str(self.config.output_path),
                "workers": self.config.workers,
            },
        )

        await self.watcher.seed_existing_albums()

        worker_tasks = [asyncio.create_task(self._worker_loop(index)) for index in range(self.config.workers)]
        watch_task = asyncio.create_task(self.watcher.watch())
        await asyncio.gather(watch_task, *worker_tasks)

    async def _worker_loop(self, worker_index: int) -> None:
        """Consume album directories from the queue and process each once at a time."""
        LOGGER.info("worker_started", extra={"worker": worker_index})
        while True:
            album_directory = await self.album_queue.get()
            reserved = False
            try:
                reserved = await self._reserve_directory(album_directory)
                if not reserved:
                    continue

                await self.processing_service.process_album_directory(album_directory)
            finally:
                if reserved:
                    await self._release_directory(album_directory)
                self.album_queue.task_done()

    async def _reserve_directory(self, directory: Path) -> bool:
        """Reserve a directory for processing, returning `False` if already reserved."""
        async with self.processing_lock:
            if directory in self.processing_directories:
                return False

            self.processing_directories.add(directory)
            return True

    async def _release_directory(self, directory: Path) -> None:
        """Release a previously reserved directory."""
        async with self.processing_lock:
            self.processing_directories.discard(directory)
