from __future__ import annotations

from pathlib import Path

from music_monitor.metadata.beets_writer import (
    _build_image,
    _coalesce,
    _optional_string,
    _safe_int,
    _supports_kwargs,
    _write_artwork,
    read_track_metadata,
    save_cover_art_sidecar,
)


class FakeMediaRead:
    def __init__(self, _path: str) -> None:
        self.albumartist = ""
        self.artist = "Artist"
        self.album = ""
        self.title = ""
        self.track = "3"
        self.tracktotal = "12"
        self.disc = "2"
        self.disctotal = "2"
        self.year = "2019"
        self.disctitle = ""
        self.mb_trackid = " track-id "
        self.mb_albumid = " album-id "
        self.mb_artistid = " artist-id "
        self.mb_albumartistid = " album-artist-id "


class FakeTargetMedia:
    def __init__(self) -> None:
        self.images = []


def test_read_track_metadata_normalizes_media_fields(monkeypatch, tmp_path: Path) -> None:
    track_path = tmp_path / "Album" / "track.mp3"
    track_path.parent.mkdir(parents=True)
    track_path.write_bytes(b"x")

    monkeypatch.setattr("music_monitor.metadata.beets_writer.mediafile.MediaFile", FakeMediaRead)

    metadata = read_track_metadata(track_path)

    assert metadata.artist_name == "Artist"
    assert metadata.album_title == "Album"
    assert metadata.track_title == "track"
    assert metadata.track_number == 3
    assert metadata.track_total == 12
    assert metadata.medium_number == 2
    assert metadata.medium_total == 2
    assert metadata.release_year == "2019"
    assert metadata.medium_format == "Disc"
    assert metadata.musicbrainz_track_id == "track-id"
    assert metadata.musicbrainz_album_id == "album-id"


def test_save_cover_art_sidecar_writes_once(tmp_path: Path) -> None:
    save_cover_art_sidecar(tmp_path, None)

    cover_path = tmp_path / "cover.jpg"
    assert not cover_path.exists()

    save_cover_art_sidecar(tmp_path, b"cover")
    assert cover_path.read_bytes() == b"cover"

    save_cover_art_sidecar(tmp_path, b"updated")
    assert cover_path.read_bytes() == b"cover"


def test_write_artwork_handles_missing_image_class(monkeypatch) -> None:
    target = FakeTargetMedia()
    monkeypatch.setattr("music_monitor.metadata.beets_writer.mediafile.Image", None, raising=False)

    _write_artwork(target, b"img")

    assert target.images == []


def test_write_artwork_sets_images_when_image_can_be_built(monkeypatch) -> None:
    target = FakeTargetMedia()

    class Image:
        def __init__(self, data: bytes, mime_type: str, type: int) -> None:
            self.data = data
            self.mime_type = mime_type
            self.type = type

    monkeypatch.setattr("music_monitor.metadata.beets_writer.mediafile.Image", Image, raising=False)

    _write_artwork(target, b"img")

    assert len(target.images) == 1
    assert target.images[0].data == b"img"


def test_build_image_fallback_paths() -> None:
    class PositionalOnlyImage:
        def __init__(self, data: bytes) -> None:
            self.data = data

    image = _build_image(PositionalOnlyImage, b"img")
    assert image is not None

    class AlwaysFailingImage:
        def __init__(self, *args, **kwargs) -> None:
            raise ValueError("boom")

    assert _build_image(AlwaysFailingImage, b"img") is None


def test_supports_kwargs_and_primitive_helpers() -> None:
    class SignatureImage:
        def __init__(self, data: bytes, mime_type: str, type: int) -> None:
            self.data = data

    assert _supports_kwargs(SignatureImage, {"data": b"x"}) is True
    assert _supports_kwargs(SignatureImage, {"missing": 1}) is False

    class NoSignature:
        __signature__ = None

        def __call__(self):
            return None

    assert _safe_int("5", 0) == 5
    assert _safe_int(None, 7) == 7
    assert _safe_int("no-int", 9) == 9

    assert _coalesce(None, "", "value") == "value"
    assert _coalesce(None, " ") == "Unknown"

    assert _optional_string(None) is None
    assert _optional_string(" ") is None
    assert _optional_string(" value ") == "value"
