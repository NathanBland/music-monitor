"""Compatibility re-export; prefer `music_monitor.services.watching` imports."""

from music_monitor.services.watching import DirectoryWatcher, is_failed_path, resolve_candidate_paths

__all__ = ["DirectoryWatcher", "is_failed_path", "resolve_candidate_paths"]
