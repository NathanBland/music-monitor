from __future__ import annotations

import re
from pathlib import Path

from music_monitor.constants import (
    FALLBACK_ARTIST_FOLDER_FORMAT,
    FALLBACK_MULTI_DISC_TRACK_FORMAT,
    FALLBACK_STANDARD_TRACK_FORMAT,
)
from music_monitor.types import NamingFormats, TrackMetadata


INVALID_PATH_CHARS_PATTERN = re.compile(r"[<>:\\|?*\x00-\x1f]")
EMPTY_VALUE = "Unknown"


def build_destination_path(output_root: Path, metadata: TrackMetadata, naming: NamingFormats | None) -> Path:
    """Build the destination path for a track using Lidarr-style naming templates."""
    naming_formats = naming or NamingFormats(
        artist_folder_format=FALLBACK_ARTIST_FOLDER_FORMAT,
        standard_track_format=FALLBACK_STANDARD_TRACK_FORMAT,
        multi_disc_track_format=FALLBACK_MULTI_DISC_TRACK_FORMAT,
    )

    path_template = naming_formats.standard_track_format
    if metadata.medium_number > 1:
        path_template = naming_formats.multi_disc_track_format

    template_values = {
        "album_title": _clean_value(metadata.album_title),
        "release_year": _clean_value(metadata.release_year),
        "artist_name": _clean_value(metadata.artist_name),
        "track_number": f"{metadata.track_number:02d}",
        "track_title": _clean_value(metadata.track_title),
        "medium_format": _clean_value(metadata.medium_format),
        "medium_number": f"{metadata.medium_number:02d}",
    }

    normalized_template = _normalize_lidarr_template(path_template)
    relative_path = normalized_template.format(**template_values)
    return output_root / relative_path


def _normalize_lidarr_template(template: str) -> str:
    """Translate Lidarr placeholders into Python `str.format` placeholders."""
    replacements = {
        "{Album Title}": "{album_title}",
        "{Release Year}": "{release_year}",
        "{Artist Name}": "{artist_name}",
        "{Track Title}": "{track_title}",
        "{Medium Format}": "{medium_format}",
        "{track:00}": "{track_number}",
        "{medium:00}": "{medium_number}",
    }

    normalized = template
    for source_value, target_value in replacements.items():
        normalized = normalized.replace(source_value, target_value)
    return normalized


def _clean_value(value: str) -> str:
    """Trim and sanitize a metadata value for safe use in file paths."""
    trimmed = value.strip()
    sanitized = INVALID_PATH_CHARS_PATTERN.sub("_", trimmed)
    if sanitized:
        return sanitized
    return EMPTY_VALUE
