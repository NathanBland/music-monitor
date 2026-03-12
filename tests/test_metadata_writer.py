from __future__ import annotations

from pathlib import Path

from music_monitor.metadata.beets_writer import write_track_metadata
from music_monitor.types import TrackMetadata


class FakeMediaFile:
    def __init__(self, _path: str) -> None:
        self.albumartist = None
        self.artist = None
        self.album = None
        self.title = None
        self.track = None
        self.tracktotal = None
        self.disc = None
        self.disctotal = None
        self.year = None
        self.mb_trackid = None
        self.mb_albumid = None
        self.mb_artistid = None
        self.mb_albumartistid = None
        self.images = []
        self.saved = False

    def save(self) -> None:
        self.saved = True


def test_write_track_metadata_sets_lidarr_compatible_fields(monkeypatch, tmp_path: Path) -> None:
    created: list[FakeMediaFile] = []

    def fake_media_file(path: str) -> FakeMediaFile:
        instance = FakeMediaFile(path)
        created.append(instance)
        return instance

    monkeypatch.setattr("music_monitor.metadata.beets_writer.mediafile.MediaFile", fake_media_file)

    metadata = TrackMetadata(
        source_path=tmp_path / "track.mp3",
        artist_name="Artist",
        album_title="Album",
        track_title="Track",
        track_number=2,
        track_total=12,
        medium_number=1,
        medium_total=2,
        medium_format="Disc",
        release_year="2015",
        musicbrainz_track_id="mb-track",
        musicbrainz_album_id="mb-album",
        musicbrainz_artist_id="mb-artist",
        musicbrainz_album_artist_id="mb-album-artist",
    )

    write_track_metadata(tmp_path / "track.mp3", metadata, None)

    assert len(created) == 1
    written = created[0]
    assert written.albumartist == "Artist"
    assert written.artist == "Artist"
    assert written.album == "Album"
    assert written.title == "Track"
    assert written.track == 2
    assert written.tracktotal == 12
    assert written.disc == 1
    assert written.disctotal == 2
    assert written.year == 2015
    assert written.mb_trackid == "mb-track"
    assert written.mb_albumid == "mb-album"
    assert written.mb_artistid == "mb-artist"
    assert written.mb_albumartistid == "mb-album-artist"
    assert written.saved is True
