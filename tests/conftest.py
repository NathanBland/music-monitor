from __future__ import annotations

from pathlib import Path

import pytest

from music_monitor.clients.lidarr import LidarrClient
from music_monitor.config import AppConfig


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    return AppConfig(watch_path=tmp_path / "watch", output_path=tmp_path / "out")


@pytest.fixture
def lidarr_client() -> LidarrClient:
    return LidarrClient(base_url="", api_key="")
