from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

import mediafile

from music_monitor.clients.coverart import CoverArtArchiveClient
from music_monitor.clients.lidarr import LidarrClient
from music_monitor.clients.musicbrainz import MusicBrainzClient
from music_monitor.config import AppConfig
from music_monitor.constants import SUPPORTED_AUDIO_EXTENSIONS
from music_monitor.mapping.paths import build_destination_path
from music_monitor.metadata.beets_writer import read_track_metadata, save_cover_art_sidecar, write_track_metadata
from music_monitor.types import AlbumLookupResult, MusicBrainzLookupResult, NamingFormats, TrackMetadata

LOGGER = logging.getLogger(__name__)
MAX_PROCESSED_SNAPSHOT_ENTRIES = 2048
MAX_COLLISION_INDEX = 10_000
FILE_OUTCOME_PROCESSED = "processed"
FILE_OUTCOME_SKIPPED = "skipped"
FILE_OUTCOME_FAILED = "failed"
NON_RETRYABLE_PROCESSING_EXCEPTIONS = (FileExistsError, ValueError)
SOURCE_CLEANUP_SENTINEL_FILE = ".music-monitor-cleanup"
FILE_SETTLE_STATUS_SETTLING = "settling"
FILE_SETTLE_STATUS_STABLE = "stable"
FILE_SETTLE_STATUS_TIMEOUT = "timeout"


@dataclass
class ProcessingService:
    """Handle metadata enrichment and file moves for discovered album folders."""

    config: AppConfig
    lidarr_client: LidarrClient
    musicbrainz_client: MusicBrainzClient | None = None
    cover_art_client: CoverArtArchiveClient | None = None
    naming_formats: NamingFormats | None = None
    processed_snapshots: dict[Path, tuple[int, int]] = field(default_factory=dict)
    musicbrainz_lookups_by_album_id: dict[str, MusicBrainzLookupResult] = field(default_factory=dict)
    cover_art_by_album_id: dict[str, bytes | None] = field(default_factory=dict)

    async def process_album_directory(self, album_directory: Path) -> None:
        """Wait for file-settle, process album tracks, then clean up source directories."""
        audio_files = list(discover_audio_files(album_directory))
        if not audio_files:
            return

        are_files_settled = await self._wait_for_album_files_to_settle(audio_files, album_directory)
        if not are_files_settled:
            return

        total_files = len(audio_files)
        processed_count = 0
        skipped_count = 0
        failed_count = 0

        LOGGER.info(
            "processing_album_directory",
            extra={"album_directory": str(album_directory), "file_count": total_files},
        )

        for index, audio_path in enumerate(audio_files, start=1):
            outcome = await self._process_with_retry(audio_path)
            if outcome == FILE_OUTCOME_PROCESSED:
                processed_count += 1
            elif outcome == FILE_OUTCOME_FAILED:
                failed_count += 1
            else:
                skipped_count += 1

            LOGGER.info(
                "album_progress",
                extra={
                    "album_directory": str(album_directory),
                    "completed": index,
                    "total": total_files,
                    "processed": processed_count,
                    "skipped": skipped_count,
                    "failed": failed_count,
                    "status": "in_progress" if index < total_files else "completed",
                },
            )

        if self.config.dry_run:
            return

        cleanup_marker = album_directory / SOURCE_CLEANUP_SENTINEL_FILE
        _remove_empty_source_parent_directories(
            source=cleanup_marker,
            watch_root=self.config.watch_path,
            cleanup_root=album_directory,
        )

    async def _process_with_retry(self, audio_path: Path) -> str:
        """Process one file with retries and return a terminal processing outcome."""
        file_snapshot = _build_file_snapshot(audio_path)
        if file_snapshot and self._is_recently_processed(audio_path, file_snapshot):
            LOGGER.info("duplicate_file_event_skipped", extra={"file": str(audio_path)})
            return FILE_OUTCOME_SKIPPED

        max_attempts = self.config.backoff.attempts
        delay_seconds = self.config.backoff.initial_seconds

        for attempt in range(1, max_attempts + 1):
            try:
                was_processed = await self._process_single_file(audio_path)
                if file_snapshot:
                    self._mark_processed(audio_path, file_snapshot)
                LOGGER.info("file_processed", extra={"file": str(audio_path), "attempt": attempt})
                if was_processed:
                    return FILE_OUTCOME_PROCESSED
                return FILE_OUTCOME_SKIPPED
            except Exception as error:
                LOGGER.error(
                    "file_processing_failed",
                    extra={"file": str(audio_path), "attempt": attempt, "error": str(error)},
                )

                if not audio_path.exists():
                    LOGGER.info("source_file_missing_skip", extra={"file": str(audio_path), "attempt": attempt})
                    return FILE_OUTCOME_SKIPPED

                if isinstance(error, NON_RETRYABLE_PROCESSING_EXCEPTIONS):
                    if isinstance(error, ValueError) and "artist identity unresolved" in str(error).lower():
                        LOGGER.error(
                            "artist_identity_unresolved",
                            extra={"file": str(audio_path), "attempt": attempt},
                        )
                    self._move_to_failed(audio_path)
                    return FILE_OUTCOME_FAILED

                if attempt >= max_attempts:
                    self._move_to_failed(audio_path)
                    return FILE_OUTCOME_FAILED

                await asyncio.sleep(delay_seconds)
                delay_seconds = min(delay_seconds * 2, self.config.backoff.max_seconds)

        return FILE_OUTCOME_FAILED

    async def _process_single_file(self, audio_path: Path) -> bool:
        """Read, enrich, retag, and move one file, returning whether a move was performed."""
        metadata = read_track_metadata(audio_path)
        metadata = await self._apply_musicbrainz_metadata(metadata)
        lookup_result = await self.lidarr_client.fetch_album_lookup(metadata.artist_name, metadata.album_title)
        metadata = _apply_lookup_result_to_metadata(metadata, lookup_result)
        album_art_bytes = await self._resolve_album_art(metadata, lookup_result)

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
        conflicting_file = _find_cross_format_duplicate(final_destination)
        if conflicting_file is not None:
            raise FileExistsError(
                f"destination stem collision with different format: {final_destination.name} vs {conflicting_file.name}"
            )
        final_destination.parent.mkdir(parents=True, exist_ok=True)

        if self.config.dry_run:
            LOGGER.info(
                "dry_run_file_processing",
                extra={"source": str(audio_path), "destination": str(final_destination)},
            )
            return False

        write_track_metadata(audio_path, metadata, album_art_bytes)
        _copy_verify_and_remove_source(audio_path, final_destination)
        save_cover_art_sidecar(final_destination.parent, album_art_bytes)
        LOGGER.info("file_moved", extra={"source": str(audio_path), "destination": str(final_destination)})
        return True

    def _move_to_failed(self, source_path: Path) -> None:
        """Move a file into the configured failed directory."""
        if not source_path.exists():
            LOGGER.info("source_missing_before_failed_move", extra={"source": str(source_path)})
            return

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

    async def _apply_musicbrainz_metadata(self, metadata: TrackMetadata) -> TrackMetadata:
        """Apply metadata from MusicBrainz with MB IDs preferred over text search."""
        if self.musicbrainz_client is None:
            return metadata

        cached_lookup = self._get_cached_musicbrainz_lookup(metadata.musicbrainz_album_id)
        lookup_result = cached_lookup or await self.musicbrainz_client.fetch_track_lookup(metadata)
        if lookup_result.musicbrainz_album_id:
            self.musicbrainz_lookups_by_album_id[lookup_result.musicbrainz_album_id] = lookup_result

        return _apply_musicbrainz_lookup_result(metadata, lookup_result)

    async def _resolve_album_art(self, metadata: TrackMetadata, lidarr_lookup: AlbumLookupResult) -> bytes | None:
        """Resolve album art bytes preferring Cover Art Archive, then Lidarr fallback."""
        musicbrainz_album_id = metadata.musicbrainz_album_id
        if musicbrainz_album_id and self.cover_art_client:
            cached_art = self.cover_art_by_album_id.get(musicbrainz_album_id)
            if cached_art is not None:
                return cached_art

            fetched_art = await self.cover_art_client.fetch_front_cover(musicbrainz_album_id)
            self.cover_art_by_album_id[musicbrainz_album_id] = fetched_art
            if fetched_art is not None:
                return fetched_art

        return lidarr_lookup.album_art_bytes

    def _get_cached_musicbrainz_lookup(self, album_id: str | None) -> MusicBrainzLookupResult | None:
        """Return a previously fetched MusicBrainz lookup by album ID when available."""
        if album_id is None:
            return None
        normalized_album_id = album_id.strip()
        if not normalized_album_id:
            return None
        return self.musicbrainz_lookups_by_album_id.get(normalized_album_id)

    async def _wait_for_album_files_to_settle(self, audio_files: list[Path], album_directory: Path) -> bool:
        """Wait until all discovered files in an album remain stable before processing."""
        if not self.config.ingest.settle_enabled:
            return True

        poll_interval_seconds = self.config.ingest.poll_interval_seconds
        stable_polls_required = self.config.ingest.stable_polls_required
        max_wait_seconds = self.config.ingest.max_wait_seconds

        stable_poll_counts: dict[Path, int] = {audio_path: 0 for audio_path in audio_files}
        last_snapshots: dict[Path, tuple[int, int]] = {}

        LOGGER.info(
            "album_file_settle_wait_started",
            extra={
                "album_directory": str(album_directory),
                "file_count": len(audio_files),
                "status": FILE_SETTLE_STATUS_SETTLING,
                "poll_interval_seconds": poll_interval_seconds,
                "stable_polls_required": stable_polls_required,
                "max_wait_seconds": max_wait_seconds,
            },
        )

        elapsed_seconds = 0.0
        while elapsed_seconds <= max_wait_seconds:
            all_files_stable = True
            for audio_path in audio_files:
                current_snapshot = _build_file_snapshot(audio_path)
                if current_snapshot is None:
                    LOGGER.info(
                        "album_file_settle_wait_interrupted_missing_file",
                        extra={"album_directory": str(album_directory), "file": str(audio_path)},
                    )
                    return False

                previous_snapshot = last_snapshots.get(audio_path)
                if previous_snapshot == current_snapshot:
                    stable_poll_counts[audio_path] += 1
                else:
                    stable_poll_counts[audio_path] = 1
                    last_snapshots[audio_path] = current_snapshot

                if stable_poll_counts[audio_path] < stable_polls_required:
                    all_files_stable = False

            if all_files_stable:
                LOGGER.info(
                    "album_file_settle_wait_completed",
                    extra={
                        "album_directory": str(album_directory),
                        "file_count": len(audio_files),
                        "status": FILE_SETTLE_STATUS_STABLE,
                        "elapsed_seconds": elapsed_seconds,
                    },
                )
                return True

            if elapsed_seconds >= max_wait_seconds:
                break

            await asyncio.sleep(poll_interval_seconds)
            elapsed_seconds += poll_interval_seconds

        LOGGER.info(
            "album_file_settle_wait_timeout",
            extra={
                "album_directory": str(album_directory),
                "file_count": len(audio_files),
                "status": FILE_SETTLE_STATUS_TIMEOUT,
                "elapsed_seconds": elapsed_seconds,
            },
        )
        return False


def discover_audio_files(root: Path) -> Iterator[Path]:
    """Yield valid audio files directly under a directory, skipping unsupported inputs."""
    for path in root.iterdir():
        if not path.is_file():
            continue

        if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            LOGGER.debug("non_audio_file_detected", extra={"file": str(path)})
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
    while collision_index <= MAX_COLLISION_INDEX:
        candidate = parent / f"{stem} ({collision_index}){suffix}"
        if not candidate.exists():
            return candidate
        collision_index += 1

    raise FileExistsError(f"unable to find unique destination for {destination} after {MAX_COLLISION_INDEX} collisions")


def _build_file_snapshot(path: Path) -> tuple[int, int] | None:
    """Build a `(size, mtime_ns)` snapshot tuple for duplicate-event detection."""
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None

    return (stat_result.st_size, stat_result.st_mtime_ns)


def _apply_lookup_result_to_metadata(metadata: TrackMetadata, lookup_result: AlbumLookupResult) -> TrackMetadata:
    """Apply selected lookup fields to metadata when local values are missing."""
    if metadata.release_year == "Unknown" and lookup_result.release_year:
        return replace(metadata, release_year=lookup_result.release_year)
    return metadata


def _apply_musicbrainz_lookup_result(
    metadata: TrackMetadata, lookup_result: MusicBrainzLookupResult
) -> TrackMetadata:
    """Apply non-empty MusicBrainz fields onto existing file metadata values."""
    return replace(
        metadata,
        artist_name=lookup_result.artist_name or metadata.artist_name,
        album_title=lookup_result.album_title or metadata.album_title,
        track_title=lookup_result.track_title or metadata.track_title,
        track_number=lookup_result.track_number or metadata.track_number,
        track_total=lookup_result.track_total or metadata.track_total,
        medium_number=lookup_result.medium_number or metadata.medium_number,
        medium_total=lookup_result.medium_total or metadata.medium_total,
        release_year=lookup_result.release_year or metadata.release_year,
        musicbrainz_track_id=lookup_result.musicbrainz_track_id or metadata.musicbrainz_track_id,
        musicbrainz_album_id=lookup_result.musicbrainz_album_id or metadata.musicbrainz_album_id,
        musicbrainz_artist_id=lookup_result.musicbrainz_artist_id or metadata.musicbrainz_artist_id,
        musicbrainz_album_artist_id=lookup_result.musicbrainz_album_artist_id or metadata.musicbrainz_album_artist_id,
    )


def _find_cross_format_duplicate(destination: Path) -> Path | None:
    """Return an existing destination sibling with the same stem but different extension."""
    parent_directory = destination.parent
    if not parent_directory.exists():
        return None

    target_stem = destination.stem.lower()
    target_suffix = destination.suffix.lower()
    for sibling in parent_directory.glob("*"):
        if not sibling.is_file():
            continue
        if sibling.stem.lower() != target_stem:
            continue
        if sibling.suffix.lower() == target_suffix:
            continue
        return sibling

    return None


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
        with source.open("rb") as source_file, destination.open("xb") as destination_file:
            destination_created = True
            shutil.copyfileobj(source_file, destination_file)

        shutil.copystat(str(source), str(destination))

        destination_size_bytes = destination.stat().st_size
        if destination_size_bytes != source_size_bytes:
            raise ValueError("destination file size mismatch after copy")

        source.unlink()
    except Exception as error:
        if isinstance(error, OSError):
            LOGGER.warning(
                "source_delete_or_copy_failed",
                extra={
                    "source": str(source),
                    "destination": str(destination),
                    "error": str(error),
                },
            )
        if destination_created:
            try:
                destination.unlink(missing_ok=True)
            except OSError as cleanup_error:
                LOGGER.warning(
                    "destination_cleanup_delete_failed",
                    extra={
                        "source": str(source),
                        "destination": str(destination),
                        "error": str(cleanup_error),
                    },
                )
        raise


def _remove_empty_source_parent_directories(source: Path, watch_root: Path, cleanup_root: Path) -> None:
    """Remove empty source parent directories up to and including the configured cleanup root."""
    resolved_watch_root = watch_root.resolve()
    resolved_cleanup_root = cleanup_root.resolve()
    current_parent = source.parent

    try:
        current_parent.resolve().relative_to(resolved_watch_root)
    except ValueError:
        return
    try:
        current_parent.resolve().relative_to(resolved_cleanup_root)
    except ValueError:
        return

    while current_parent != resolved_watch_root:
        try:
            current_parent.rmdir()
        except OSError as error:
            if _contains_audio_files(current_parent):
                LOGGER.info(
                    "source_parent_cleanup_skipped_audio_remaining",
                    extra={"directory": str(current_parent), "error": str(error)},
                )
                return

            _remove_non_audio_contents(current_parent)
            try:
                current_parent.rmdir()
            except OSError as cleanup_error:
                LOGGER.info(
                    "source_parent_cleanup_skipped",
                    extra={"directory": str(current_parent), "error": str(cleanup_error)},
                )
                return

            LOGGER.info(
                "source_parent_cleanup_non_audio_removed",
                extra={"directory": str(current_parent)},
            )

        if current_parent == resolved_cleanup_root:
            return
        current_parent = current_parent.parent


def _contains_audio_files(directory: Path) -> bool:
    """Return whether a directory tree contains files with supported audio extensions."""
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
            return True
    return False


def _remove_non_audio_contents(directory: Path) -> None:
    """Delete non-audio files and empty subdirectories under a directory."""
    subpaths = sorted(directory.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for subpath in subpaths:
        if subpath.is_file():
            if subpath.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
                continue
            try:
                subpath.unlink()
            except OSError as error:
                LOGGER.info(
                    "source_non_audio_delete_skipped",
                    extra={"path": str(subpath), "error": str(error)},
                )
            continue

        if not subpath.is_dir():
            continue

        try:
            subpath.rmdir()
        except OSError:
            continue
