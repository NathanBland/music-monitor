from __future__ import annotations

from pathlib import Path

from music_monitor.config import load_config


def test_load_config_defaults_when_file_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.toml"

    config = load_config(config_path)

    assert config.watch_path == Path("./watch").resolve()
    assert config.output_path == (Path("./output").resolve())
    assert config.backoff.max_seconds == 30.0
    assert config.backoff.attempts == 10
    assert config.ingest.settle_enabled is True
    assert config.ingest.poll_interval_seconds == 2.0
    assert config.ingest.stable_polls_required == 3
    assert config.ingest.max_wait_seconds == 300.0


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
                "",
                "[ingest]",
                "settle_enabled = false",
                "poll_interval_seconds = 0.5",
                "stable_polls_required = 2",
                "max_wait_seconds = 90.0",
            ]
        )
    )

    monkeypatch.setenv("LIDARR_API_KEY", "env-key")
    monkeypatch.setenv("MUSIC_MONITOR_WORKERS", "0")
    monkeypatch.setenv("BACKOFF_ATTEMPTS", "0")
    monkeypatch.setenv("INGEST_SETTLE_ENABLED", "true")
    monkeypatch.setenv("INGEST_STABLE_POLLS_REQUIRED", "0")

    config = load_config(config_path)

    assert config.lidarr.api_key == "env-key"
    assert config.workers == 1
    assert config.backoff.attempts == 1
    assert config.backoff.max_seconds == 20.0
    assert config.ingest.settle_enabled is True
    assert config.ingest.poll_interval_seconds == 0.5
    assert config.ingest.stable_polls_required == 1
    assert config.ingest.max_wait_seconds == 90.0


def test_load_config_rejects_overlapping_watch_and_output_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    shared_root = tmp_path / "library"
    config_path.write_text(
        "\n".join(
            [
                f'watch_path = "{shared_root}"',
                f'output_path = "{shared_root / "organized"}"',
            ]
        )
    )

    try:
        load_config(config_path)
    except ValueError as error:
        assert "inside watch_path" in str(error)
    else:
        raise AssertionError("Expected load_config to reject overlapping watch/output roots")


def test_load_config_reads_dry_run_from_environment(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('watch_path = "./watch"\noutput_path = "./out"\n')
    monkeypatch.setenv("MUSIC_MONITOR_DRY_RUN", "true")

    config = load_config(config_path)

    assert config.dry_run is True
