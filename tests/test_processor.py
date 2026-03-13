from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from music_monitor.clients.lidarr import LidarrClient
from music_monitor.config import AppConfig, BackoffConfig, IngestConfig
from music_monitor.services.processing import ProcessingService, discover_audio_files, ensure_unique_destination
from music_monitor.types import AlbumLookupResult, NamingFormats, TrackMetadata


@pytest.mark.asyncio
async def test_process_with_retry_succeeds_after_retries(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"x")

    config = AppConfig(
        watch_path=tmp_path,
        output_path=tmp_path / "out",
        backoff=BackoffConfig(initial_seconds=0.01, max_seconds=0.02, attempts=3),
    )
    service = ProcessingService(config=config, lidarr_client=LidarrClient(base_url="", api_key=""))

    attempts = {"count": 0}

    async def flaky(_path: Path, source_cleanup_root: Path | None = None) -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("boom")

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(service, "_process_single_file", flaky)
    monkeypatch.setattr("music_monitor.services.processing.asyncio.sleep", fake_sleep)

    await service._process_with_retry(source)

    assert attempts["count"] == 3
    assert sleep_calls == [0.01, 0.02]


def test_discover_audio_files_does_not_recurse_into_subdirectories(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "Artist"
    album = root / "Album"
    root.mkdir()
    album.mkdir()
    root_audio = root / "single.mp3"
    nested_audio = album / "track.mp3"
    root_audio.write_bytes(b"x")
    nested_audio.write_bytes(b"x")
    monkeypatch.setattr("music_monitor.services.processing.mediafile.MediaFile", lambda _path: object())

    discovered = list(discover_audio_files(root))

    assert discovered == [root_audio]


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
async def test_process_with_retry_skips_missing_source_without_failed_move(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"x")

    config = AppConfig(
        watch_path=tmp_path,
        output_path=tmp_path / "out",
        backoff=BackoffConfig(initial_seconds=0.0, max_seconds=0.0, attempts=3),
    )
    service = ProcessingService(config=config, lidarr_client=LidarrClient(base_url="", api_key=""))

    async def fail_after_source_removed(path: Path, source_cleanup_root: Path | None = None) -> None:
        path.unlink()
        raise FileNotFoundError("gone")

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(service, "_process_single_file", fail_after_source_removed)
    monkeypatch.setattr("music_monitor.services.processing.asyncio.sleep", fake_sleep)

    await service._process_with_retry(source)

    assert not (tmp_path / "failed").exists()
    assert sleep_calls == []


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
    assert album_art.exists()
    assert source_parent.exists()
    assert watch_path.exists()
    assert writes["art"] == b"img"
    assert (expected.parent / "cover.jpg").exists()


@pytest.mark.asyncio
async def test_process_album_directory_removes_source_after_terminal_outcomes(monkeypatch, tmp_path: Path) -> None:
    watch_path = tmp_path / "watch"
    album_directory = watch_path / "Artist" / "Album"
    album_directory.mkdir(parents=True)
    first_track = album_directory / "01 - Track.mp3"
    second_track = album_directory / "02 - Track.mp3"
    sidecar_file = album_directory / "Folder.jpg"
    first_track.write_bytes(b"a")
    second_track.write_bytes(b"b")
    sidecar_file.write_bytes(b"img")

    config = AppConfig(
        watch_path=watch_path,
        output_path=tmp_path / "library",
        ingest=IngestConfig(settle_enabled=False),
    )
    client = LidarrClient(base_url="", api_key="")
    service = ProcessingService(config=config, lidarr_client=client)

    outcomes = iter(["processed", "processed"])

    async def fake_process_with_retry(audio_path: Path) -> str:
        audio_path.unlink()
        return next(outcomes)

    monkeypatch.setattr("music_monitor.services.processing.mediafile.MediaFile", lambda _path: object())
    monkeypatch.setattr(service, "_process_with_retry", fake_process_with_retry)

    await service.process_album_directory(album_directory)

    assert not album_directory.exists()
    assert watch_path.exists()


@pytest.mark.asyncio
async def test_process_with_retry_moves_cross_format_duplicates_to_failed(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "track.mp3"
    source.write_bytes(b"x")

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

    conflicting_destination = config.output_path / "Artist/Album (2024)/Artist - Album - 01 - Track.flac"
    conflicting_destination.parent.mkdir(parents=True, exist_ok=True)
    conflicting_destination.write_bytes(b"existing")

    async def fake_lookup(_artist: str, _album: str):
        return AlbumLookupResult(album_art_bytes=None, release_year=None)

    monkeypatch.setattr(client, "fetch_album_lookup", fake_lookup)
    monkeypatch.setattr("music_monitor.services.processing.read_track_metadata", lambda _p: metadata)
    monkeypatch.setattr("music_monitor.services.processing.write_track_metadata", lambda *_args, **_kwargs: None)

    await service._process_with_retry(source)

    failed_destination = tmp_path / "failed" / "track.mp3"
    assert failed_destination.exists()
    assert conflicting_destination.read_bytes() == b"existing"


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
async def test_process_with_retry_cleans_destination_when_copy_size_mismatch(monkeypatch, tmp_path: Path) -> None:
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
async def test_process_with_retry_cleans_destination_when_source_unlink_fails(monkeypatch, tmp_path: Path) -> None:
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
async def test_process_with_retry_handles_concurrent_destination_collision(monkeypatch, tmp_path: Path) -> None:
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

    async def fake_process(_path: Path, source_cleanup_root: Path | None = None) -> None:
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


@pytest.mark.asyncio
async def test_wait_for_album_files_to_settle_returns_true_when_disabled(tmp_path: Path) -> None:
    source = tmp_path / "track.mp3"
    source.write_bytes(b"x")
    service = ProcessingService(
        config=AppConfig(
            watch_path=tmp_path,
            output_path=tmp_path / "out",
            ingest=IngestConfig(settle_enabled=False),
        ),
        lidarr_client=LidarrClient(base_url="", api_key=""),
    )

    is_settled = await service._wait_for_album_files_to_settle([source], tmp_path)

    assert is_settled is True


@pytest.mark.asyncio
async def test_wait_for_album_files_to_settle_returns_true_when_snapshot_stabilizes(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "track.mp3"
    source.write_bytes(b"x")
    service = ProcessingService(
        config=AppConfig(
            watch_path=tmp_path,
            output_path=tmp_path / "out",
            ingest=IngestConfig(
                settle_enabled=True,
                poll_interval_seconds=0.01,
                stable_polls_required=2,
                max_wait_seconds=0.03,
            ),
        ),
        lidarr_client=LidarrClient(base_url="", api_key=""),
    )

    monkeypatch.setattr("music_monitor.services.processing._build_file_snapshot", lambda _path: (10, 100))

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("music_monitor.services.processing.asyncio.sleep", fake_sleep)

    is_settled = await service._wait_for_album_files_to_settle([source], tmp_path)

    assert is_settled is True
    assert sleep_calls == [0.01]


@pytest.mark.asyncio
async def test_wait_for_album_files_to_settle_times_out_for_changing_snapshot(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "track.mp3"
    source.write_bytes(b"x")
    service = ProcessingService(
        config=AppConfig(
            watch_path=tmp_path,
            output_path=tmp_path / "out",
            ingest=IngestConfig(
                settle_enabled=True,
                poll_interval_seconds=0.01,
                stable_polls_required=3,
                max_wait_seconds=0.03,
            ),
        ),
        lidarr_client=LidarrClient(base_url="", api_key=""),
    )

    snapshots = iter([(10, 100), (11, 101), (12, 102), (13, 103), (14, 104)])

    def fake_snapshot(_path: Path) -> tuple[int, int]:
        return next(snapshots)

    monkeypatch.setattr("music_monitor.services.processing._build_file_snapshot", fake_snapshot)

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("music_monitor.services.processing.asyncio.sleep", fake_sleep)

    is_settled = await service._wait_for_album_files_to_settle([source], tmp_path)

    assert is_settled is False


@pytest.mark.asyncio
async def test_process_album_directory_skips_processing_when_files_not_settled(monkeypatch, tmp_path: Path) -> None:
    album_directory = tmp_path / "Artist" / "Album"
    album_directory.mkdir(parents=True)
    source = album_directory / "track.mp3"
    source.write_bytes(b"x")

    service = ProcessingService(
        config=AppConfig(watch_path=tmp_path, output_path=tmp_path / "out"),
        lidarr_client=LidarrClient(base_url="", api_key=""),
    )

    monkeypatch.setattr("music_monitor.services.processing.mediafile.MediaFile", lambda _path: object())

    async def fake_wait(_audio_files: list[Path], _album_directory: Path) -> bool:
        return False

    calls = {"count": 0}

    async def fake_process(_path: Path) -> str:
        calls["count"] += 1
        return "processed"

    monkeypatch.setattr(service, "_wait_for_album_files_to_settle", fake_wait)
    monkeypatch.setattr(service, "_process_with_retry", fake_process)

    await service.process_album_directory(album_directory)

    assert calls["count"] == 0


@pytest.mark.asyncio
async def test_process_with_retry_moves_to_failed_when_artist_identity_unresolved(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "unknown-artist.flac"
    source.write_bytes(b"x")

    config = AppConfig(
        watch_path=tmp_path,
        output_path=tmp_path / "library",
        backoff=BackoffConfig(initial_seconds=0.0, max_seconds=0.0, attempts=1),
    )
    client = LidarrClient(base_url="", api_key="")
    service = ProcessingService(config=config, lidarr_client=client)

    unresolved_artist_metadata = TrackMetadata(
        source_path=source,
        artist_name=" ",
        album_title="Album",
        track_title="Track",
        track_number=1,
        track_total=1,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2024",
    )

    async def fake_lookup(_artist: str, _album: str):
        return AlbumLookupResult(album_art_bytes=None, release_year=None)

    monkeypatch.setattr(client, "fetch_album_lookup", fake_lookup)
    monkeypatch.setattr("music_monitor.services.processing.read_track_metadata", lambda _p: unresolved_artist_metadata)
    monkeypatch.setattr("music_monitor.services.processing.write_track_metadata", lambda *_args, **_kwargs: None)

    outcome = await service._process_with_retry(source)

    failed_destination = tmp_path / "failed" / "unknown-artist.flac"
    assert outcome == "failed"
    assert failed_destination.exists()
    assert not (config.output_path / "Unknown").exists()
