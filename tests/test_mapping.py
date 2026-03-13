from __future__ import annotations

from pathlib import Path

import pytest

from music_monitor.mapping.paths import build_destination_path
from music_monitor.types import NamingFormats, TrackMetadata


def test_build_destination_path_uses_fallback_format() -> None:
    metadata = TrackMetadata(
        source_path=Path("/tmp/source.mp3"),
        artist_name="Artist",
        album_title="Album",
        track_title="Song",
        track_number=3,
        track_total=10,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2024",
    )

    destination = build_destination_path(Path("/output"), metadata, None)

    assert str(destination) == "/output/Artist/Album (2024)/Artist - Album - 03 - Song"


def test_build_destination_path_uses_multi_disc_template() -> None:
    metadata = TrackMetadata(
        source_path=Path("/tmp/source.flac"),
        artist_name="Artist",
        album_title="Album",
        track_title="Song",
        track_number=11,
        track_total=12,
        medium_number=2,
        medium_total=2,
        medium_format="CD",
        release_year="2001",
    )
    naming_formats = NamingFormats(
        artist_folder_format="{Artist Name}",
        standard_track_format="{Album Title}/{Track Title}",
        multi_disc_track_format="{Album Title}/{Medium Format} {medium:00}/{track:00} {Track Title}",
    )

    destination = build_destination_path(Path("/library"), metadata, naming_formats)

    assert str(destination) == "/library/Artist/Album/CD 02/11 Song"


def test_build_destination_path_overrides_album_only_artist_folder_template() -> None:
    metadata = TrackMetadata(
        source_path=Path("/tmp/source.flac"),
        artist_name="Sleep Token",
        album_title="Take Me Back To Eden",
        track_title="The Summoning",
        track_number=2,
        track_total=12,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2023",
    )
    naming_formats = NamingFormats(
        artist_folder_format="{Album Title}",
        standard_track_format=(
            "{Album Title} ({Release Year})/{Artist Name} - {Album Title} - {track:00} - {Track Title}"
        ),
        multi_disc_track_format=(
            "{Album Title} ({Release Year})/{Medium Format} {medium:00}/"
            "{Artist Name} - {Album Title} - {track:00} - {Track Title}"
        ),
    )

    destination = build_destination_path(Path("/library"), metadata, naming_formats)

    assert str(destination) == (
        "/library/Sleep Token/Take Me Back To Eden (2023)/Sleep Token - Take Me Back To Eden - 02 - The Summoning"
    )


def test_build_destination_path_sanitizes_invalid_chars() -> None:
    metadata = TrackMetadata(
        source_path=Path("/tmp/source.mp3"),
        artist_name="Bad:Artist",
        album_title="Album/Name",
        track_title="Title?",
        track_number=1,
        track_total=9,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2020",
    )

    destination = build_destination_path(Path("/out"), metadata, None)

    assert "Album_Name" in str(destination)
    assert "Bad_Artist" in str(destination)
    assert "Title_" in str(destination)


def test_build_destination_path_replaces_commas_and_ampersands() -> None:
    metadata = TrackMetadata(
        source_path=Path("/tmp/source.mp3"),
        artist_name="Artist, Name & Co",
        album_title="Album, Name & More",
        track_title="Song, Pt. 1 & 2",
        track_number=1,
        track_total=9,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2020",
    )

    destination = build_destination_path(Path("/out"), metadata, None)

    assert "," not in str(destination)
    assert "&" not in str(destination)
    assert "Artist Name Co" in str(destination)
    assert "Album Name More" in str(destination)
    assert "Song Pt. 1 2" in str(destination)


def test_build_destination_path_sanitizes_path_traversal_segments() -> None:
    metadata = TrackMetadata(
        source_path=Path("/tmp/source.mp3"),
        artist_name="../Artist",
        album_title="..",
        track_title="Track",
        track_number=1,
        track_total=1,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2020",
    )

    destination = build_destination_path(Path("/out"), metadata, None)

    assert ".." not in str(destination)


def test_build_destination_path_raises_when_artist_identity_unresolved() -> None:
    metadata = TrackMetadata(
        source_path=Path("/tmp/source.mp3"),
        artist_name=" ",
        album_title="Album",
        track_title="Track",
        track_number=1,
        track_total=1,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2020",
    )

    with pytest.raises(ValueError, match="artist identity unresolved"):
        build_destination_path(Path("/out"), metadata, None)
