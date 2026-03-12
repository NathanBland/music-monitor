from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from music_monitor.config import AppConfig
from music_monitor.services.application import MusicMonitorApp


@pytest.mark.asyncio
async def test_reserve_and_release_directory(tmp_path: Path) -> None:
    app = MusicMonitorApp(AppConfig(watch_path=tmp_path, output_path=tmp_path / "out"))
    directory = tmp_path / "album"

    first = await app._reserve_directory(directory)
    second = await app._reserve_directory(directory)

    assert first is True
    assert second is False

    await app._release_directory(directory)
    third = await app._reserve_directory(directory)
    assert third is True


@pytest.mark.asyncio
async def test_worker_loop_processes_queue_item(tmp_path: Path, monkeypatch) -> None:
    app = MusicMonitorApp(AppConfig(watch_path=tmp_path, output_path=tmp_path / "out"))
    directory = tmp_path / "album"

    processed: list[Path] = []

    async def fake_process(path: Path) -> None:
        processed.append(path)
        raise asyncio.CancelledError

    monkeypatch.setattr(app.processing_service, "process_album_directory", fake_process)

    await app.album_queue.put(directory)

    with pytest.raises(asyncio.CancelledError):
        await app._worker_loop(1)

    assert processed == [directory]


@pytest.mark.asyncio
async def test_run_initializes_naming_and_seeding(tmp_path: Path, monkeypatch) -> None:
    app = MusicMonitorApp(AppConfig(watch_path=tmp_path, output_path=tmp_path / "out", workers=1))

    async def fake_fetch_naming_formats():
        return None

    seeded = {"value": False}

    async def fake_seed() -> None:
        seeded["value"] = True

    async def fake_watch() -> None:
        raise asyncio.CancelledError

    async def fake_worker(_index: int) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(app.lidarr_client, "fetch_naming_formats", fake_fetch_naming_formats)
    monkeypatch.setattr(app.watcher, "seed_existing_albums", fake_seed)
    monkeypatch.setattr(app.watcher, "watch", fake_watch)
    monkeypatch.setattr(app, "_worker_loop", fake_worker)

    with pytest.raises(asyncio.CancelledError):
        await app.run()

    assert seeded["value"] is True
