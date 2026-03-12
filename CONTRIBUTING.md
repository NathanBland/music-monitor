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

## Architecture Overview

`music-monitor` is a queue-based pipeline:

```text
watchfiles -> album_queue -> worker pool -> ProcessingService
    |                                         |
seed existing folders                read metadata -> Lidarr lookup
                                              |
                              write metadata -> build path -> copy+verify -> cleanup
```

## Code Style

- Keep changes small and focused.
- Prefer clear function names and single-purpose helpers.
- Maintain typed interfaces and avoid introducing `Any` when possible.
- Keep behavior changes covered by tests.

## Pull Requests

- Use descriptive PR titles.
- Include what changed, why, and any migration/runtime notes.
- Mention any follow-up work explicitly if a change is intentionally partial.
