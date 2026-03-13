# Contributing

This project welcomes focused, practical contributions that improve reliability, safety, and maintainability.

## Development Setup

- Python `3.12+`
- `uv` package manager

Install dependencies:

```bash
make dev
```

## Running Checks

Run these before opening a pull request:

```bash
make lint
make typecheck
make test
```

`make test` enforces a minimum total coverage of `85%` and writes `coverage.xml`. Pull requests should not reduce coverage below this threshold.

## Architecture Overview

`music-monitor` is a queue-based pipeline:

```text
watchfiles -> album_queue -> worker pool -> ProcessingService
    |                                         |
seed existing folders     read metadata -> MusicBrainz -> Lidarr fallback
                                              |
                    resolve art (CAA -> Lidarr) -> write tags/art -> move -> folder cleanup
```

Processing highlights:

- Per-folder progress is tracked across `processed`, `skipped`, and `failed` outcomes.
- Ingest settle checks wait for stable file snapshots before processing to reduce partial-upload corruption.
- Destination paths enforce artist-folder-first roots; album-only top-level templates are overridden to artist names.
- Files with unresolved artist identity fail as non-retryable and move to `failed/`.
- Source folder cleanup is deferred until all discovered files in that folder reach a terminal outcome.
- Moves are blocked when a destination file with the same stem but different extension already exists.

## Code Style

- Keep changes small and focused.
- Prefer clear function names and single-purpose helpers.
- Maintain typed interfaces and avoid introducing `Any` when possible.
- Keep behavior changes covered by tests.

## Pull Requests

- Use descriptive PR titles.
- Include what changed, why, and any migration/runtime notes.
- Mention any follow-up work explicitly if a change is intentionally partial.
