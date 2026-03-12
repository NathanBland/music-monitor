from __future__ import annotations

import inspect
import logging
from pathlib import Path

import mediafile

from music_monitor.types import TrackMetadata


LOGGER = logging.getLogger(__name__)


def read_track_metadata(path: Path) -> TrackMetadata:
    """Read tags from an audio file and normalize them into `TrackMetadata`."""
    media = mediafile.MediaFile(str(path))

    artist_name = _coalesce(media.albumartist, media.artist, path.parent.name)
    album_title = _coalesce(media.album, path.parent.name)
    track_title = _coalesce(media.title, path.stem)
    track_number = _safe_int(media.track, 0)
    track_total = _safe_int(getattr(media, "tracktotal", None), 0)
    medium_number = _safe_int(media.disc, 1)
    medium_total = _safe_int(getattr(media, "disctotal", None), 0)
    release_year = str(_safe_int(media.year, 0) or "Unknown")
    medium_format = _coalesce(media.disctitle, "Disc")
    musicbrainz_track_id = _optional_string(getattr(media, "mb_trackid", None))
    musicbrainz_album_id = _optional_string(getattr(media, "mb_albumid", None))
    musicbrainz_artist_id = _optional_string(getattr(media, "mb_artistid", None))
    musicbrainz_album_artist_id = _optional_string(getattr(media, "mb_albumartistid", None))

    return TrackMetadata(
        source_path=path,
        artist_name=artist_name,
        album_title=album_title,
        track_title=track_title,
        track_number=track_number,
        track_total=track_total,
        medium_number=medium_number,
        medium_total=medium_total,
        medium_format=medium_format,
        release_year=release_year,
        musicbrainz_track_id=musicbrainz_track_id,
        musicbrainz_album_id=musicbrainz_album_id,
        musicbrainz_artist_id=musicbrainz_artist_id,
        musicbrainz_album_artist_id=musicbrainz_album_artist_id,
    )


def write_track_metadata(path: Path, metadata: TrackMetadata, album_art_bytes: bytes | None) -> None:
    """Write normalized metadata and optional album art back into an audio file."""
    media = mediafile.MediaFile(str(path))

    media.albumartist = metadata.artist_name
    media.artist = metadata.artist_name
    media.album = metadata.album_title
    media.title = metadata.track_title
    media.track = metadata.track_number
    media.tracktotal = metadata.track_total
    media.disc = metadata.medium_number
    media.disctotal = metadata.medium_total
    media.mb_trackid = metadata.musicbrainz_track_id
    media.mb_albumid = metadata.musicbrainz_album_id
    media.mb_artistid = metadata.musicbrainz_artist_id
    media.mb_albumartistid = metadata.musicbrainz_album_artist_id

    try:
        media.year = int(metadata.release_year)
    except (TypeError, ValueError):
        media.year = 0

    if album_art_bytes:
        _write_artwork(media, album_art_bytes)

    media.save()


def _write_artwork(target_media: mediafile.MediaFile, album_art_bytes: bytes) -> None:
    """Attach cover art to a media object when the current beets API supports it."""
    image_class = getattr(mediafile, "Image", None)
    if image_class is None:
        LOGGER.warning("beets_image_class_unavailable")
        return

    image_object = _build_image(image_class, album_art_bytes)
    if image_object is None:
        LOGGER.warning("beets_image_build_failed")
        return

    target_media.images = [image_object]


def _build_image(image_class: type, album_art_bytes: bytes) -> object | None:
    """Construct an image object using the first compatible constructor signature."""
    image_signatures = [
        {"data": album_art_bytes, "mime_type": "image/jpeg", "type": 3},
        {"data": album_art_bytes, "type": 3},
        {"data": album_art_bytes},
    ]

    for signature in image_signatures:
        if not _supports_kwargs(image_class, signature):
            continue

        try:
            return image_class(**signature)
        except Exception:
            continue

    try:
        return image_class(album_art_bytes)
    except Exception:
        return None


def _supports_kwargs(image_class: type, kwargs: dict[str, object]) -> bool:
    """Return whether a callable appears to accept all provided keyword arguments."""
    try:
        parameters = inspect.signature(image_class).parameters
    except (TypeError, ValueError):
        return True

    return all(key in parameters for key in kwargs)


def _safe_int(value: object, fallback: int) -> int:
    """Convert `value` to `int`, returning `fallback` for null or invalid values."""
    try:
        if value is None:
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coalesce(*values: object) -> str:
    """Return the first non-empty string value, or `'Unknown'` if none are usable."""
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return "Unknown"


def _optional_string(value: object) -> str | None:
    """Normalize nullable tag values to a stripped string or `None`."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text
