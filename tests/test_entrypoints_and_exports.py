from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import sys
from pathlib import Path

import pytest

import music_monitor.__main__ as cli_main
from music_monitor.config import AppConfig


def test_validate_startup_paths_rejects_missing_watch_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="watch_path does not exist"):
        cli_main._validate_startup_paths(tmp_path / "missing", tmp_path / "out")


def test_validate_startup_paths_rejects_non_directory_watch_path(tmp_path: Path) -> None:
    watch_file = tmp_path / "watch.txt"
    watch_file.write_text("x")

    with pytest.raises(ValueError, match="watch_path must be a directory"):
        cli_main._validate_startup_paths(watch_file, tmp_path / "out")


def test_validate_startup_paths_creates_output_directory(tmp_path: Path) -> None:
    watch_path = tmp_path / "watch"
    watch_path.mkdir()
    output_path = tmp_path / "organized"

    cli_main._validate_startup_paths(watch_path, output_path)

    assert output_path.exists()
    assert output_path.is_dir()


def test_main_loads_config_and_runs_app(monkeypatch, tmp_path: Path) -> None:
    watch_path = tmp_path / "watch"
    watch_path.mkdir()
    output_path = tmp_path / "out"
    config = AppConfig(watch_path=watch_path, output_path=output_path)

    seen: dict[str, object] = {}

    class FakeMusicMonitorApp:
        def __init__(self, app_config: AppConfig) -> None:
            seen["app_config"] = app_config

        async def run(self) -> None:
            seen["run_called"] = True

    def fake_load_config(config_path: Path | None) -> AppConfig:
        seen["config_path"] = config_path
        return config

    def fake_configure_logging(level: str, log_file: Path, max_bytes: int, backup_count: int) -> None:
        seen["logging"] = (level, log_file, max_bytes, backup_count)

    original_asyncio_run = asyncio.run

    def fake_asyncio_run(coroutine) -> None:
        original_asyncio_run(coroutine)

    monkeypatch.setattr(sys, "argv", ["music-monitor", "--config", str(tmp_path / "config.toml"), "--dry-run"])
    monkeypatch.setattr(cli_main, "load_config", fake_load_config)
    monkeypatch.setattr(cli_main, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(cli_main, "MusicMonitorApp", FakeMusicMonitorApp)
    monkeypatch.setattr(cli_main.asyncio, "run", fake_asyncio_run)

    cli_main.main()

    assert seen["config_path"] == tmp_path / "config.toml"
    assert config.dry_run is True
    assert seen["app_config"] is config
    assert seen["run_called"] is True


def test_package_version_fallback_when_distribution_missing(monkeypatch) -> None:
    import music_monitor

    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda _name: (_ for _ in ()).throw(importlib.metadata.PackageNotFoundError()),
    )
    reloaded = importlib.reload(music_monitor)

    assert reloaded.__version__ == "0.0.0"


def test_compatibility_re_exports() -> None:
    import music_monitor.app as app_module
    import music_monitor.beets_metadata as beets_metadata_module
    import music_monitor.lidarr_client as lidarr_module
    import music_monitor.path_mapper as path_mapper_module
    import music_monitor.processor as processor_module
    import music_monitor.watcher as watcher_module
    from music_monitor.clients.lidarr import LidarrClient
    from music_monitor.mapping.paths import build_destination_path
    from music_monitor.metadata.beets_writer import read_track_metadata, save_cover_art_sidecar, write_track_metadata
    from music_monitor.services.application import MusicMonitorApp
    from music_monitor.services.processing import ProcessingService, discover_audio_files, ensure_unique_destination
    from music_monitor.services.watching import DirectoryWatcher, is_failed_path, resolve_candidate_paths

    assert app_module.MusicMonitorApp is MusicMonitorApp
    assert beets_metadata_module.read_track_metadata is read_track_metadata
    assert beets_metadata_module.save_cover_art_sidecar is save_cover_art_sidecar
    assert beets_metadata_module.write_track_metadata is write_track_metadata
    assert lidarr_module.LidarrClient is LidarrClient
    assert path_mapper_module.build_destination_path is build_destination_path
    assert processor_module.ProcessingService is ProcessingService
    assert processor_module.discover_audio_files is discover_audio_files
    assert processor_module.ensure_unique_destination is ensure_unique_destination
    assert watcher_module.DirectoryWatcher is DirectoryWatcher
    assert watcher_module.is_failed_path is is_failed_path
    assert watcher_module.resolve_candidate_paths is resolve_candidate_paths
