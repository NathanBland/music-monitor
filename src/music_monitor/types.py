from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TrackMetadata:
    source_path: Path
    artist_name: str
    album_title: str
    track_title: str
    track_number: int
    track_total: int
    medium_number: int
    medium_total: int
    medium_format: str
    release_year: str
    musicbrainz_track_id: str | None = None
    musicbrainz_album_id: str | None = None
    musicbrainz_artist_id: str | None = None
    musicbrainz_album_artist_id: str | None = None


@dataclass
class NamingFormats:
    artist_folder_format: str
    standard_track_format: str
    multi_disc_track_format: str


@dataclass
class AlbumLookupResult:
    album_art_bytes: bytes | None
    release_year: str | None


@dataclass
class MusicBrainzLookupResult:
    artist_name: str | None = None
    album_title: str | None = None
    track_title: str | None = None
    track_number: int | None = None
    track_total: int | None = None
    medium_number: int | None = None
    medium_total: int | None = None
    release_year: str | None = None
    musicbrainz_track_id: str | None = None
    musicbrainz_album_id: str | None = None
    musicbrainz_artist_id: str | None = None
    musicbrainz_album_artist_id: str | None = None
