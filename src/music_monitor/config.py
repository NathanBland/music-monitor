from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CONFIG_PATH = Path("config.toml")


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file_path: Path = Path("logs/music-monitor.log")
    max_bytes: int = 1_000_000
    backup_count: int = 3


@dataclass
class BackoffConfig:
    initial_seconds: float = 1.0
    max_seconds: float = 30.0
    attempts: int = 10


@dataclass
class LidarrConfig:
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: float = 10.0


@dataclass
class AppConfig:
    watch_path: Path
    output_path: Path
    failed_subdir: str = "failed"
    workers: int = os.cpu_count() or 4
    lidarr: LidarrConfig = field(default_factory=LidarrConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    backoff: BackoffConfig = field(default_factory=BackoffConfig)


def _read_file(path: Path) -> Mapping[str, Any]:
    """Load TOML configuration from disk, or return an empty mapping if missing."""
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _env_override(key: str, default: str | None = None) -> str | None:
    """Return an environment variable value, falling back to the provided default."""
    value = os.getenv(key)
    if value is None:
        return default
    return value


def _coerce_int(value: str | None, fallback: int) -> int:
    """Convert a value to `int` or return `fallback` when conversion fails."""
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def _coerce_float(value: str | None, fallback: float) -> float:
    """Convert a value to `float` or return `fallback` when conversion fails."""
    if value is None:
        return fallback
    try:
        return float(value)
    except ValueError:
        return fallback


def load_config(config_path: Path | None = None) -> AppConfig:
    """Build application configuration from TOML file values and env overrides."""
    path = config_path or DEFAULT_CONFIG_PATH
    data = _read_file(path)

    watch_path = Path(_env_override("MUSIC_MONITOR_WATCH_PATH") or data.get("watch_path") or ".")
    output_path = Path(_env_override("MUSIC_MONITOR_OUTPUT_PATH") or data.get("output_path") or "./output")
    failed_subdir = _env_override("MUSIC_MONITOR_FAILED_SUBDIR", data.get("failed_subdir", "failed"))

    workers_default = data.get("workers") or (os.cpu_count() or 4)
    workers = _coerce_int(_env_override("MUSIC_MONITOR_WORKERS"), workers_default)

    lidarr_section = data.get("lidarr", {})
    lidarr_base = _env_override("LIDARR_BASE_URL", lidarr_section.get("base_url", ""))
    lidarr_key = _env_override("LIDARR_API_KEY", lidarr_section.get("api_key", ""))
    lidarr_timeout = _coerce_float(_env_override("LIDARR_TIMEOUT"), lidarr_section.get("timeout_seconds", 10.0))

    log_section = data.get("logging", {})
    log_level = _env_override("LOG_LEVEL", log_section.get("level", "INFO"))
    log_file = Path(_env_override("LOG_FILE", log_section.get("file_path", "logs/music-monitor.log")))
    log_max_bytes = _coerce_int(_env_override("LOG_MAX_BYTES"), log_section.get("max_bytes", 1_000_000))
    log_backup_count = _coerce_int(_env_override("LOG_BACKUP_COUNT"), log_section.get("backup_count", 3))

    backoff_section = data.get("backoff", {})
    backoff_initial = _coerce_float(_env_override("BACKOFF_INITIAL"), backoff_section.get("initial_seconds", 1.0))
    backoff_max = _coerce_float(_env_override("BACKOFF_MAX"), backoff_section.get("max_seconds", 30.0))
    backoff_attempts = _coerce_int(_env_override("BACKOFF_ATTEMPTS"), backoff_section.get("attempts", 10))
    workers = max(1, workers)
    backoff_attempts = max(1, backoff_attempts)

    return AppConfig(
        watch_path=watch_path.expanduser().resolve(),
        output_path=output_path.expanduser().resolve(),
        failed_subdir=failed_subdir,
        workers=workers,
        lidarr=LidarrConfig(
            base_url=lidarr_base,
            api_key=lidarr_key,
            timeout_seconds=lidarr_timeout,
        ),
        logging=LoggingConfig(
            level=log_level,
            file_path=log_file,
            max_bytes=log_max_bytes,
            backup_count=log_backup_count,
        ),
        backoff=BackoffConfig(
            initial_seconds=backoff_initial,
            max_seconds=backoff_max,
            attempts=backoff_attempts,
        ),
    )
