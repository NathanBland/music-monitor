from __future__ import annotations

from pathlib import Path


SUPPORTED_AUDIO_EXTENSIONS = {
    ".aac",
    ".aiff",
    ".alac",
    ".ape",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}

FALLBACK_STANDARD_TRACK_FORMAT = (
    "{album_title} ({release_year})/{artist_name} - {album_title} - {track_number} - {track_title}"
)
FALLBACK_MULTI_DISC_TRACK_FORMAT = (
    "{album_title} ({release_year})/{medium_format} {medium_number}/{artist_name} - "
    "{album_title} - {track_number} - {track_title}"
)
FALLBACK_ARTIST_FOLDER_FORMAT = "{artist_name}"

FAILED_FOLDER_NAME = "failed"
DEFAULT_CONFIG_FILE = Path("config.toml")
