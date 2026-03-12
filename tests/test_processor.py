from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from music_monitor.clients.lidarr import LidarrClient
from music_monitor.config import AppConfig, BackoffConfig
from music_monitor.services.processing import ProcessingService, ensure_unique_destination
from music_monitor.types import AlbumLookupResult, NamingFormats, TrackMetadata


@pytest.mark.asyncio
async def test_process_with_retry_succeeds_after_retries(monkeypatch, tmp_path: Path) -> None:
    config = AppConfig(
        watch_path=tmp_path,
        output_path=tmp_path / "out",
        backoff=BackoffConfig(initial_seconds=0.01, max_seconds=0.02, attempts=3),
    )
    service = ProcessingService(config=config, lidarr_client=LidarrClient(base_url="", api_key=""))

    attempts = {"count": 0}

    async def flaky(_path: Path) -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("boom")

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(service, "_process_single_file", flaky)
    monkeypatch.setattr("music_monitor.services.processing.asyncio.sleep", fake_sleep)

    await service._process_with_retry(tmp_path / "song.mp3")

    assert attempts["count"] == 3
    assert sleep_calls == [0.01, 0.02]


@pytest.mark.asyncio
async def test_process_with_retry_moves_to_failed_on_exhaustion(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"x")

    config = AppConfig(
        watch_path=tmp_path,
        output_path=tmp_path / "out",
        backoff=BackoffConfig(initial_seconds=0.0, max_seconds=0.0, attempts=2),
    )
    service = ProcessingService(config=config, lidarr_client=LidarrClient(base_url="", api_key=""))

    async def always_fail(_path: Path) -> None:
        raise RuntimeError("fail")

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(service, "_process_single_file", always_fail)
    monkeypatch.setattr("music_monitor.services.processing.asyncio.sleep", fake_sleep)

    await service._process_with_retry(source)

    failed_file = tmp_path / "failed" / "song.mp3"
    assert failed_file.exists()


@pytest.mark.asyncio
async def test_process_with_retry_moves_traversal_destination_to_failed(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "escape.mp3"
    source.write_bytes(b"x")

    config = AppConfig(
        watch_path=tmp_path,
        output_path=tmp_path / "out",
        backoff=BackoffConfig(initial_seconds=0.0, max_seconds=0.0, attempts=1),
    )
    client = LidarrClient(base_url="", api_key="")
    service = ProcessingService(config=config, lidarr_client=client)

    metadata = TrackMetadata(
        source_path=source,
        artist_name="Artist",
        album_title="Album",
        track_title="Track",
        track_number=1,
        track_total=1,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2024",
    )
    service.naming_formats = NamingFormats(
        artist_folder_format="{Artist Name}",
        standard_track_format="../../outside/{Track Title}",
        multi_disc_track_format="../../outside/{Track Title}",
    )

    async def fake_lookup(_artist: str, _album: str):
        return AlbumLookupResult(album_art_bytes=None, release_year=None)

    monkeypatch.setattr(client, "fetch_album_lookup", fake_lookup)
    monkeypatch.setattr("music_monitor.services.processing.read_track_metadata", lambda _p: metadata)
    monkeypatch.setattr("music_monitor.services.processing.write_track_metadata", lambda *_args, **_kwargs: None)

    await service._process_with_retry(source)

    failed_file = tmp_path / "failed" / "escape.mp3"
    assert failed_file.exists()
    assert not (tmp_path / "outside").exists()


@pytest.mark.asyncio
async def test_process_single_file_writes_metadata_and_moves(monkeypatch, tmp_path: Path) -> None:
    watch_path = tmp_path / "watch"
    source_parent = watch_path / "Artist" / "Album"
    source_parent.mkdir(parents=True)
    source = source_parent / "track.mp3"
    album_art = source_parent / "Folder.jpg"
    source.write_bytes(b"x")
    album_art.write_bytes(b"img")

    config = AppConfig(watch_path=watch_path, output_path=tmp_path / "library")
    client = LidarrClient(base_url="", api_key="")
    service = ProcessingService(config=config, lidarr_client=client)

    metadata = TrackMetadata(
        source_path=source,
        artist_name="Artist",
        album_title="Album",
        track_title="Track",
        track_number=1,
        track_total=12,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2024",
    )

    async def fake_lookup(_artist: str, _album: str):
        return AlbumLookupResult(album_art_bytes=b"img", release_year="2024")

    monkeypatch.setattr(client, "fetch_album_lookup", fake_lookup)
    monkeypatch.setattr("music_monitor.services.processing.read_track_metadata", lambda _p: metadata)

    writes: dict[str, object] = {}

    def fake_write(_path: Path, _metadata: TrackMetadata, art: bytes | None) -> None:
        writes["art"] = art

    monkeypatch.setattr("music_monitor.services.processing.write_track_metadata", fake_write)

    await service._process_single_file(source)

    expected = config.output_path / "Artist/Album (2024)/Artist - Album - 01 - Track.mp3"
    assert expected.exists()
    assert not source.exists()
    assert not album_art.exists()
    assert not source_parent.exists()
    assert watch_path.exists()
    assert writes["art"] == b"img"


@pytest.mark.asyncio
async def test_process_with_retry_moves_when_destination_already_exists(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "track.mp3"
    source.write_bytes(b"x")

    config = AppConfig(
        watch_path=tmp_path,
        output_path=tmp_path / "library",
        backoff=BackoffConfig(initial_seconds=0.0, max_seconds=0.0, attempts=3),
    )
    client = LidarrClient(base_url="", api_key="")
    service = ProcessingService(config=config, lidarr_client=client)

    metadata = TrackMetadata(
        source_path=source,
        artist_name="Artist",
        album_title="Album",
        track_title="Track",
        track_number=1,
        track_total=12,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2024",
    )
    existing_destination = config.output_path / "Artist/Album (2024)/Artist - Album - 01 - Track.mp3"
    existing_destination.parent.mkdir(parents=True, exist_ok=True)
    existing_destination.write_bytes(b"existing")

    async def fake_lookup(_artist: str, _album: str):
        return AlbumLookupResult(album_art_bytes=None, release_year=None)

    monkeypatch.setattr(client, "fetch_album_lookup", fake_lookup)
    monkeypatch.setattr("music_monitor.services.processing.read_track_metadata", lambda _p: metadata)
    monkeypatch.setattr("music_monitor.services.processing.write_track_metadata", lambda *_args, **_kwargs: None)

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("music_monitor.services.processing.asyncio.sleep", fake_sleep)

    await service._process_with_retry(source)

    failed_destination = tmp_path / "failed" / "track.mp3"
    assert failed_destination.exists()
    assert existing_destination.read_bytes() == b"existing"
    assert sleep_calls == []


@pytest.mark.asyncio
async def test_process_with_retry_cleans_destination_when_copy_size_mismatch(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "track.mp3"
    source.write_bytes(b"abcdef")

    config = AppConfig(
        watch_path=tmp_path,
        output_path=tmp_path / "library",
        backoff=BackoffConfig(initial_seconds=0.0, max_seconds=0.0, attempts=1),
    )
    client = LidarrClient(base_url="", api_key="")
    service = ProcessingService(config=config, lidarr_client=client)

    metadata = TrackMetadata(
        source_path=source,
        artist_name="Artist",
        album_title="Album",
        track_title="Track",
        track_number=1,
        track_total=12,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2024",
    )

    async def fake_lookup(_artist: str, _album: str):
        return AlbumLookupResult(album_art_bytes=None, release_year=None)

    def fake_copyfileobj(source_file, destination_file, _length: int = 0) -> None:
        destination_file.write(source_file.read(2))

    monkeypatch.setattr(client, "fetch_album_lookup", fake_lookup)
    monkeypatch.setattr("music_monitor.services.processing.read_track_metadata", lambda _p: metadata)
    monkeypatch.setattr("music_monitor.services.processing.write_track_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("music_monitor.services.processing.shutil.copyfileobj", fake_copyfileobj)

    await service._process_with_retry(source)

    destination = config.output_path / "Artist/Album (2024)/Artist - Album - 01 - Track.mp3"
    failed_destination = tmp_path / "failed" / "track.mp3"
    assert not destination.exists()
    assert failed_destination.exists()


@pytest.mark.asyncio
async def test_process_with_retry_cleans_destination_when_source_unlink_fails(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "track.mp3"
    source.write_bytes(b"abcdef")

    config = AppConfig(
        watch_path=tmp_path,
        output_path=tmp_path / "library",
        backoff=BackoffConfig(initial_seconds=0.0, max_seconds=0.0, attempts=1),
    )
    client = LidarrClient(base_url="", api_key="")
    service = ProcessingService(config=config, lidarr_client=client)

    metadata = TrackMetadata(
        source_path=source,
        artist_name="Artist",
        album_title="Album",
        track_title="Track",
        track_number=1,
        track_total=12,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2024",
    )

    async def fake_lookup(_artist: str, _album: str):
        return AlbumLookupResult(album_art_bytes=None, release_year=None)

    original_unlink = Path.unlink

    def fake_unlink(path: Path, *args, **kwargs) -> None:
        if path == source:
            raise PermissionError("source still busy")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(client, "fetch_album_lookup", fake_lookup)
    monkeypatch.setattr("music_monitor.services.processing.read_track_metadata", lambda _p: metadata)
    monkeypatch.setattr("music_monitor.services.processing.write_track_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pathlib.Path.unlink", fake_unlink)

    await service._process_with_retry(source)

    destination = config.output_path / "Artist/Album (2024)/Artist - Album - 01 - Track.mp3"
    failed_destination = tmp_path / "failed" / "track.mp3"
    assert not destination.exists()
    assert failed_destination.exists()


@pytest.mark.asyncio
async def test_process_with_retry_handles_concurrent_destination_collision(
    monkeypatch, tmp_path: Path
) -> None:
    first_source = tmp_path / "first.mp3"
    second_source = tmp_path / "second.mp3"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")

    config = AppConfig(
        watch_path=tmp_path,
        output_path=tmp_path / "library",
        backoff=BackoffConfig(initial_seconds=0.0, max_seconds=0.0, attempts=1),
    )
    client = LidarrClient(base_url="", api_key="")
    service = ProcessingService(config=config, lidarr_client=client)

    metadata_by_source = {
        first_source: TrackMetadata(
            source_path=first_source,
            artist_name="Artist",
            album_title="Album",
            track_title="Track",
            track_number=1,
            track_total=10,
            medium_number=1,
            medium_total=1,
            medium_format="Disc",
            release_year="2024",
        ),
        second_source: TrackMetadata(
            source_path=second_source,
            artist_name="Artist",
            album_title="Album",
            track_title="Track",
            track_number=1,
            track_total=10,
            medium_number=1,
            medium_total=1,
            medium_format="Disc",
            release_year="2024",
        ),
    }

    lookup_started = asyncio.Event()

    async def fake_lookup(_artist: str, _album: str):
        lookup_started.set()
        await asyncio.sleep(0)
        return AlbumLookupResult(album_art_bytes=None, release_year=None)

    monkeypatch.setattr(client, "fetch_album_lookup", fake_lookup)
    monkeypatch.setattr(
        "music_monitor.services.processing.read_track_metadata", lambda source: metadata_by_source[source]
    )
    monkeypatch.setattr("music_monitor.services.processing.write_track_metadata", lambda *_args, **_kwargs: None)

    first_task = asyncio.create_task(service._process_with_retry(first_source))
    await lookup_started.wait()
    second_task = asyncio.create_task(service._process_with_retry(second_source))
    await asyncio.gather(first_task, second_task)

    destination = config.output_path / "Artist/Album (2024)/Artist - Album - 01 - Track.mp3"
    failed_file_names = {path.name for path in (tmp_path / "failed").glob("*.mp3")}

    assert destination.exists()
    assert destination.read_bytes() in {b"first", b"second"}
    assert failed_file_names in ({"first.mp3"}, {"second.mp3"})


@pytest.mark.asyncio
async def test_process_with_retry_skips_duplicate_snapshot(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "track.mp3"
    source.write_bytes(b"x")

    config = AppConfig(watch_path=tmp_path, output_path=tmp_path / "out")
    service = ProcessingService(config=config, lidarr_client=LidarrClient(base_url="", api_key=""))

    calls = {"count": 0}

    async def fake_process(_path: Path) -> None:
        calls["count"] += 1

    monkeypatch.setattr(service, "_process_single_file", fake_process)

    await service._process_with_retry(source)
    await service._process_with_retry(source)

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_process_single_file_updates_unknown_release_year(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "track.mp3"
    source.write_bytes(b"x")

    config = AppConfig(watch_path=tmp_path, output_path=tmp_path / "library")
    client = LidarrClient(base_url="", api_key="")
    service = ProcessingService(config=config, lidarr_client=client)

    metadata = TrackMetadata(
        source_path=source,
        artist_name="Artist",
        album_title="Album",
        track_title="Track",
        track_number=1,
        track_total=9,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="Unknown",
    )

    async def fake_lookup(_artist: str, _album: str):
        return AlbumLookupResult(album_art_bytes=None, release_year="2010")

    monkeypatch.setattr(client, "fetch_album_lookup", fake_lookup)
    monkeypatch.setattr("music_monitor.services.processing.read_track_metadata", lambda _p: metadata)
    monkeypatch.setattr("music_monitor.services.processing.write_track_metadata", lambda *_args, **_kwargs: None)

    await service._process_single_file(source)

    expected = config.output_path / "Artist/Album (2010)/Artist - Album - 01 - Track.mp3"
    assert expected.exists()


def test_ensure_unique_destination_appends_suffix(tmp_path: Path) -> None:
    destination = tmp_path / "song.mp3"
    destination.write_bytes(b"x")

    resolved = ensure_unique_destination(destination)

    assert resolved.name == "song (1).mp3"
