# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [v0.2.0] - 2026-03-13

### Added
- Added MusicBrainz-first metadata enrichment with MB ID lookups and search fallback.
- Added Cover Art Archive client support with Lidarr artwork fallback.
- Added destination-side `cover.jpg` sidecar artwork writes when art is available.
- Added cross-format duplicate move blocking for same-stem destination collisions.
- Added ingest settle guard controls for waiting on stable file snapshots before processing.
- Added artist identity validation to fail moves when artist metadata cannot be resolved.

### Changed
- Updated processing to track per-folder progress (`processed`, `skipped`, `failed`) during album runs.
- Deferred source-folder cleanup until all discovered files in a folder reach a terminal outcome.
- Updated application/config wiring for MusicBrainz runtime settings and client initialization.
- Updated project documentation for MusicBrainz/CAA behavior, ingest settle guard behavior, and new environment variables.
- Updated destination path behavior to enforce artist-folder-first roots when top-level templates resolve to album-only paths.

## [v0.1.4] - 2026-03-12

### Security
- Added startup validation that rejects overlapping `watch_path`/`output_path` roots to prevent recursive self-processing loops.
- Added an upper collision bound for destination naming (`MAX_COLLISION_INDEX`) with explicit failure after exhaustion.
- Hardened container image defaults with a pinned `python:3.13-slim` base, OCI metadata labels, non-root runtime, and a process healthcheck.

### Runtime
- Added graceful shutdown handling for `SIGINT`/`SIGTERM` with coordinated watcher/worker teardown.
- Added startup preflight checks for `watch_path` existence and directory type, plus ensured output directory creation before runtime.
- Added dry-run execution mode via config and CLI (`--dry-run`) to log intended processing without metadata writes or file moves.
- Improved processing resilience with safer source/destination handling, bounded cleanup behavior, and quieter logging for expected non-audio files.

### DX
- Added `CONTRIBUTING.md` with setup, architecture, quality gates, and pull-request expectations.
- Added compatibility docstrings to top-level shim re-export modules and removed unused constants.
- Added strict lint/type tooling (`ruff`, `mypy`) and Make targets for `lint`, `format`, and `typecheck`.
- Synced runtime package version reporting through `importlib.metadata` and expanded package metadata/URLs in `pyproject.toml`.

### CI
- Added a dedicated CI workflow running lint, typecheck, and tests on pushes/PRs to `main`.
- Updated Docker image workflow to run tests before build/push and publish multi-arch images (`linux/amd64`, `linux/arm64`).
- Added Dependabot automation for Python and GitHub Actions dependency updates.
- Added a tag-driven GitHub release workflow for `v*` tags with changelog-backed release creation.

## [v0.1.3] - 2026-03-12

### Changed
- Added non-audio file cleanup handling in source directory removal flow.
- Expanded processing-path cleanup behavior for non-audio file scenarios.

### Tests
- Added test coverage for the new non-audio cleanup behavior in processing logic.

## [v0.1.2] - 2026-03-12

### Fixed
- Moved source file deletion to occur strictly inside the copy/verification success path.
- Added more comprehensive error logging in the processing pipeline.

### Tests
- Added regression tests for copy/verify/delete failure and logging-related processing paths.

## [v0.1.1] - 2026-03-12

### Added
- Added artist-folder support in destination path structure.
- Added config/docs updates for artist-folder output behavior.

### Changed
- Updated Docker image references and image consumption documentation to use explicit version tags.
- Improved processing robustness and file-handling behavior in move/collision paths.

### Tests
- Expanded mapping and processing tests for artist-folder path generation and robustness updates.

## [v0.1.0] - 2026-03-12

### Added
- Initial full `music-monitor` implementation:
  - recursive folder watching,
  - queue + worker orchestration,
  - Lidarr client integration,
  - metadata read/write pipeline using beets `mediafile`,
  - output path mapping and safe file move pipeline,
  - JSON logging, config loading, and retry/backoff behavior.
- Project packaging and developer tooling (`pyproject.toml`, `Makefile`, `pytest.ini`, `uv.lock`).
- Container and operations assets (`Dockerfile`, `.dockerignore`, `docker-compose.sample.yml`).
- CI workflow for Docker image build/publish and initial project documentation.
- Initial test suite across app, config, Lidarr client, mapping, metadata writer, processor, and watcher.

### Changed
- Replaced `uv`-based install in Docker build with `pip install .` for image build reliability.
- Switched container runtime to a non-root user and tightened related runtime defaults.
- Improved processing safety and path-handling behavior with corresponding test updates.
