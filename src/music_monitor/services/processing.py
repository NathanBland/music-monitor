from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import mediafile

from music_monitor.clients.lidarr import LidarrClient
from music_monitor.config import AppConfig
from music_monitor.constants import SUPPORTED_AUDIO_EXTENSIONS
from music_monitor.mapping.paths import build_destination_path
from music_monitor.metadata.beets_writer import read_track_metadata, write_track_metadata
from music_monitor.types import AlbumLookupResult, NamingFormats, TrackMetadata


LOGGER = logging.getLogger(__name__)
MAX_PROCESSED_SNAPSHOT_ENTRIES = 2048
NON_RETRYABLE_PROCESSING_EXCEPTIONS = (FileExistsError, ValueError)


@dataclass
class ProcessingService:
    """Handle metadata enrichment and file moves for discovered album folders."""

    config: AppConfig
    lidarr_client: LidarrClient
    naming_formats: NamingFormats | None = None
    processed_snapshots: dict[Path, tuple[int, int]] = field(default_factory=dict)

    async def process_album_directory(self, album_directory: Path) -> None:
        """Process each valid audio file found under an album directory."""
        audio_files = list(discover_audio_files(album_directory))
        if not audio_files:
            return

        LOGGER.info(
            "processing_album_directory",
            extra={"album_directory": str(album_directory), "file_count": len(audio_files)},
        )

        for audio_path in audio_files:
            await self._process_with_retry(audio_path)

    async def _process_with_retry(self, audio_path: Path) -> None:
        """Process one file with exponential backoff and failed-folder fallback."""
        file_snapshot = _build_file_snapshot(audio_path)
        if file_snapshot and self._is_recently_processed(audio_path, file_snapshot):
            LOGGER.info("duplicate_file_event_skipped", extra={"file": str(audio_path)})
            return

        max_attempts = self.config.backoff.attempts
        delay_seconds = self.config.backoff.initial_seconds

        for attempt in range(1, max_attempts + 1):
            try:
                await self._process_single_file(audio_path)
                if file_snapshot:
                    self._mark_processed(audio_path, file_snapshot)
                LOGGER.info("file_processed", extra={"file": str(audio_path), "attempt": attempt})
                return
            except Exception as error:
                LOGGER.error(
                    "file_processing_failed",
                    extra={"file": str(audio_path), "attempt": attempt, "error": str(error)},
                )

                if isinstance(error, NON_RETRYABLE_PROCESSING_EXCEPTIONS):
                    self._move_to_failed(audio_path)
                    return

                if attempt >= max_attempts:
                    self._move_to_failed(audio_path)
                    return

                await asyncio.sleep(delay_seconds)
                delay_seconds = min(delay_seconds * 2, self.config.backoff.max_seconds)

    async def _process_single_file(self, audio_path: Path) -> None:
        """Read, enrich, retag, and move a single audio file to its destination."""
        metadata = read_track_metadata(audio_path)
        lookup_result = await self.lidarr_client.fetch_album_lookup(metadata.artist_name, metadata.album_title)
        metadata = _apply_lookup_result_to_metadata(metadata, lookup_result)
        write_track_metadata(audio_path, metadata, lookup_result.album_art_bytes)

        base_destination = build_destination_path(
            output_root=self.config.output_path,
            metadata=metadata,
            naming=self.naming_formats,
        )
        constrained_destination = _constrain_to_output_root(
            destination=base_destination.with_suffix(audio_path.suffix.lower()),
            output_root=self.config.output_path,
        )
        final_destination = constrained_destination
        final_destination.parent.mkdir(parents=True, exist_ok=True)

        _copy_verify_and_remove_source(audio_path, final_destination)
        _remove_empty_source_parent_directories(audio_path, self.config.watch_path)
        LOGGER.info("file_moved", extra={"source": str(audio_path), "destination": str(final_destination)})

    def _move_to_failed(self, source_path: Path) -> None:
        """Move a file into the configured failed directory."""
        failed_root = self.config.watch_path / self.config.failed_subdir
        failed_root.mkdir(parents=True, exist_ok=True)

        failed_destination = ensure_unique_destination(failed_root / source_path.name)
        shutil.move(str(source_path), str(failed_destination))
        LOGGER.error(
            "file_moved_to_failed",
            extra={"source": str(source_path), "destination": str(failed_destination)},
        )

    def _is_recently_processed(self, audio_path: Path, snapshot: tuple[int, int]) -> bool:
        """Return whether the current file snapshot matches the last processed snapshot."""
        existing_snapshot = self.processed_snapshots.get(audio_path)
        if existing_snapshot is None:
            return False
        return existing_snapshot == snapshot

    def _mark_processed(self, audio_path: Path, snapshot: tuple[int, int]) -> None:
        """Record a processed file snapshot and evict the oldest entry when full."""
        if len(self.processed_snapshots) >= MAX_PROCESSED_SNAPSHOT_ENTRIES:
            oldest_path = next(iter(self.processed_snapshots))
            self.processed_snapshots.pop(oldest_path, None)
        self.processed_snapshots[audio_path] = snapshot


def discover_audio_files(root: Path) -> Iterator[Path]:
    """Yield valid audio files from a directory tree, skipping unsupported inputs."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            LOGGER.error("non_audio_file_detected", extra={"file": str(path)})
            continue

        try:
            mediafile.MediaFile(str(path))
        except Exception:
            LOGGER.error("unsupported_audio_or_corrupt_file", extra={"file": str(path)})
            continue

        yield path


def ensure_unique_destination(destination: Path) -> Path:
    """Return a non-colliding destination path by appending numeric suffixes."""
    if not destination.exists():
        return destination

    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent

    collision_index = 1
    while True:
        candidate = parent / f"{stem} ({collision_index}){suffix}"
        if not candidate.exists():
            return candidate
        collision_index += 1


def _build_file_snapshot(path: Path) -> tuple[int, int] | None:
    """Build a `(size, mtime_ns)` snapshot tuple for duplicate-event detection."""
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None

    return (stat_result.st_size, stat_result.st_mtime_ns)


def _apply_lookup_result_to_metadata(
    metadata: TrackMetadata, lookup_result: AlbumLookupResult
) -> TrackMetadata:
    """Apply selected lookup fields to metadata when local values are missing."""
    if metadata.release_year == "Unknown" and lookup_result.release_year:
        metadata.release_year = lookup_result.release_year
    return metadata


def _constrain_to_output_root(destination: Path, output_root: Path) -> Path:
    """Resolve and validate that destination remains inside the configured output root."""
    resolved_output_root = output_root.resolve()
    resolved_destination = destination.resolve()

    try:
        resolved_destination.relative_to(resolved_output_root)
    except ValueError as error:
        raise ValueError("resolved destination escapes configured output root") from error

    return resolved_destination


def _copy_verify_and_remove_source(source: Path, destination: Path) -> None:
    """Copy a file, verify byte size integrity, then remove the original source file."""
    source_size_bytes = source.stat().st_size
    destination_created = False
    try:
        with source.open("rb") as source_file:
            with destination.open("xb") as destination_file:
                destination_created = True
                shutil.copyfileobj(source_file, destination_file)

        shutil.copystat(str(source), str(destination))

        destination_size_bytes = destination.stat().st_size
        if destination_size_bytes != source_size_bytes:
            raise ValueError("destination file size mismatch after copy")
    except Exception:
        if destination_created:
            destination.unlink(missing_ok=True)
        raise

    source.unlink()


def _remove_empty_source_parent_directories(source: Path, watch_root: Path) -> None:
    """Remove empty source parent directories up to, but not including, the watch root."""
    resolved_watch_root = watch_root.resolve()
    current_parent = source.parent

    try:
        current_parent.resolve().relative_to(resolved_watch_root)
    except ValueError:
        return

    while current_parent != resolved_watch_root:
        try:
            current_parent.rmdir()
        except OSError:
            return
        current_parent = current_parent.parent
