# music-monitor

`music-monitor` is a uv-based Python service that recursively watches a folder for music files, writes metadata using beets libraries, applies Lidarr naming mappings (v3.1 API) when available, and moves processed files into an organized output library.

## Disclaimer

This project is built with AI assistance and is shared as-is.
Treat the code accordingly, verify behavior in your environment, and use it at your own risk.
This is a _just for fun_ project.

## Features

- Recursive watch of a configurable input folder.
- Parallel processing with configurable worker count (default: CPU count).
- Audio-first pipeline (mp3/flac targeted, other supported beets formats accepted).
- Non-audio files are logged at debug level and skipped.
- Metadata write pipeline based on beets libraries (no standalone beets instance required).
- Metadata enrichment from Lidarr includes album art and fallback release year when tags are missing.
- Cover-art downloads are restricted to the configured Lidarr host (same scheme/host/port).
- Lidarr naming format lookup with fallback templates:
  - Standard track: `{Album Title} ({Release Year})/{Artist Name} - {Album Title} - {track:00} - {Track Title}`
  - Multi-disc: `{Album Title} ({Release Year})/{Medium Format} {medium:00}/{Artist Name} - {Album Title} - {track:00} - {Track Title}`
  - Artist folder: `{Artist Name}`
- Structured JSON logging to console + rolling file (1 MB max file size).
- Duplicate file events are suppressed using file snapshot tracking.
- Retry with exponential backoff (cap 30s); non-retryable failures and exhausted retries move files to `failed/`.
- File moves use copy-then-verify semantics and refuse destination overwrite/path escape.
- `failed/` is excluded from monitoring.
- Dry-run mode (`--dry-run`) logs intended operations without writing metadata or moving files.
- Graceful shutdown support for `SIGINT`/`SIGTERM`.

## Architecture

```text
watchfiles -> album_queue -> worker pool -> ProcessingService
    |                                         |
seed existing folders                read metadata -> Lidarr lookup
                                              |
                              write metadata -> build path -> copy+verify -> cleanup
```

## Requirements

- Linux (Docker-focused).
- Python 3.12+ for local development.
- `uv` package manager.
- A Lidarr instance (optional but recommended for mapping and cover art).

## Quick Start (Local)

1. Copy example config:

```bash
cp config.toml.example config.toml
```

2. Edit `config.toml` values (watch/output paths, Lidarr URL/API key).

3. Install dependencies:

```bash
make dev
```

4. Run service:

```bash
make run
```

## Configuration

Configuration can come from `config.toml` and environment variables. Environment variables override file values.

### Config file (`config.toml`)

Use `config.toml.example` as a template.

### Environment variables

- `MUSIC_MONITOR_WATCH_PATH`
- `MUSIC_MONITOR_OUTPUT_PATH`
- `MUSIC_MONITOR_FAILED_SUBDIR`
- `MUSIC_MONITOR_WORKERS`
- `MUSIC_MONITOR_DRY_RUN`
- `LIDARR_BASE_URL`
- `LIDARR_API_KEY`
- `LIDARR_TIMEOUT`
- `LOG_LEVEL` (`INFO` default; set `DEBUG` for verbose logs)
- `LOG_FILE`
- `LOG_MAX_BYTES` (default `1000000`)
- `LOG_BACKUP_COUNT` (default `3`)
- `BACKOFF_INITIAL` (default `1.0`)
- `BACKOFF_MAX` (default `30.0`)
- `BACKOFF_ATTEMPTS` (default `10`)

## Logging

The service emits JSON logs with events including:

- watch startup and seeded directories
- worker startup
- file processing attempts
- file moves
- non-audio/unsupported files
- retry and failure outcomes

File logs use rotation at 1 MB with backup files.

## Docker

### Build locally

```bash
docker build -t music-monitor:local .
```

### Run with Docker Compose

A sample is provided at `docker-compose.sample.yml`.

```yaml
services:
  music-monitor:
    image: ghcr.io/nathanbland/music-monitor:v0.1.0
    user: "1000:1000"
    container_name: music-monitor
    restart: unless-stopped
    volumes:
      - ./watch:/data/watch
      - ./output:/data/output
      - ./logs:/logs
      - ./config.toml:/app/config.toml:ro
    environment:
      LIDARR_BASE_URL: "http://lidarr:8686"
      LIDARR_API_KEY: "replace-with-your-lidarr-api-key"
      LOG_LEVEL: "INFO"
      MUSIC_MONITOR_WATCH_PATH: "/data/watch"
      MUSIC_MONITOR_OUTPUT_PATH: "/data/output"
    command: ["music-monitor", "--config", "/app/config.toml"]
```

The container runs as `appuser` (`uid=1000`, `gid=1000`). Ensure mounted paths are writable by `1000:1000` to avoid log/output permission errors.

```bash
sudo chown -R 1000:1000 ./watch ./output ./logs
```

## Container Image Tags

A GitHub Actions workflow is included at `.github/workflows/docker-image.yml`.

- Builds on pushes/PRs/workflow dispatch.
- Pushes to `ghcr.io/<owner>/<repo>` on non-PR events.
- Applies branch/tag/SHA metadata tags.
- Publishes `latest` for the default branch.

### Consume image tags

```bash
docker pull ghcr.io/nathanbland/music-monitor:v0.1.0
```

For rolling deployments, use:

```bash
docker pull ghcr.io/nathanbland/music-monitor:latest
```

In Docker Compose, pin a release tag for predictable deploys:

```yaml
services:
  music-monitor:
    image: ghcr.io/nathanbland/music-monitor:v0.1.0
    user: "1000:1000"
```

## Make Targets

- `make ensure-uv` — install `uv` if missing.
- `make install` — install runtime dependencies.
- `make dev` — install runtime + dev dependencies.
- `make run` — run monitor.
- `make check` — compile-check source.
- `make lint` — run ruff lint checks.
- `make format` — run ruff formatter.
- `make typecheck` — run strict mypy checks.
- `make test` — run unit tests.

## Testing

The test suite focuses on unit-level behavior for:

- configuration loading and env override behavior
- Lidarr client behavior via mocked HTTP calls
- path mapping and naming fallback logic
- watcher seeding and failed-path exclusion
- processing retries, backoff, and failed-folder handling
- app-level queue reservation and worker orchestration

Run tests with:

```bash
make test
```

Equivalent command:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q -p pytest_asyncio.plugin
```

## Notes

- Lidarr API target is v3.1.x (`https://lidarr.audio/docs/api/`).
- beets library documentation: `https://beets.readthedocs.io/en/stable/`.
- This project uses beets libraries directly for metadata operations; it does not run a beets-managed music library database.
