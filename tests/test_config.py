from __future__ import annotations

from pathlib import Path

from music_monitor.config import load_config


def test_load_config_defaults_when_file_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.toml"

    config = load_config(config_path)

    assert config.watch_path == Path(".").resolve()
    assert config.output_path == (Path("./output").resolve())
    assert config.backoff.max_seconds == 30.0
    assert config.backoff.attempts == 10


def test_load_config_from_toml_and_env_override(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'watch_path = "./watch"',
                'output_path = "./out"',
                "workers = 2",
                "",
                "[lidarr]",
                'base_url = "http://lidarr:8686"',
                'api_key = "file-key"',
                "",
                "[logging]",
                'level = "INFO"',
                'file_path = "./logs/app.log"',
                "",
                "[backoff]",
                "initial_seconds = 2.0",
                "max_seconds = 20.0",
                "attempts = 4",
            ]
        )
    )

    monkeypatch.setenv("LIDARR_API_KEY", "env-key")
    monkeypatch.setenv("MUSIC_MONITOR_WORKERS", "0")
    monkeypatch.setenv("BACKOFF_ATTEMPTS", "0")

    config = load_config(config_path)

    assert config.lidarr.api_key == "env-key"
    assert config.workers == 1
    assert config.backoff.attempts == 1
    assert config.backoff.max_seconds == 20.0
