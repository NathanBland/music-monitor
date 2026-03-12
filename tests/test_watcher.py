from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from music_monitor.config import AppConfig
from music_monitor.services.watching import DirectoryWatcher, is_failed_path, resolve_candidate_paths


@pytest.mark.asyncio
async def test_seed_existing_albums_enqueues_unique_directories(tmp_path: Path) -> None:
    watch = tmp_path / "watch"
    album_a = watch / "Artist" / "AlbumA"
    album_b = watch / "Artist" / "AlbumB"
    album_a.mkdir(parents=True)
    album_b.mkdir(parents=True)
    (album_a / "01.mp3").write_bytes(b"a")
    (album_a / "02.flac").write_bytes(b"a")
    (album_b / "01.mp3").write_bytes(b"a")

    queue: asyncio.Queue[Path] = asyncio.Queue()
    watcher = DirectoryWatcher(AppConfig(watch_path=watch, output_path=tmp_path / "out"), queue)

    await watcher.seed_existing_albums()

    enqueued = {queue.get_nowait(), queue.get_nowait()}
    assert enqueued == {album_a, album_b}


def test_resolve_candidate_paths_for_file_and_directory(tmp_path: Path) -> None:
    album = tmp_path / "album"
    album.mkdir()
    file_path = album / "01.mp3"
    file_path.write_bytes(b"a")

    assert resolve_candidate_paths(file_path) == [file_path]
    assert resolve_candidate_paths(album) == [file_path]


def test_is_failed_path_detects_failed_tree(tmp_path: Path) -> None:
    watch = tmp_path / "watch"
    failed = watch / "failed"
    failed.mkdir(parents=True)
    file_path = failed / "bad.mp3"
    file_path.write_bytes(b"x")

    config = AppConfig(watch_path=watch, output_path=tmp_path / "out")

    assert is_failed_path(file_path, config)
