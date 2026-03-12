"""Compatibility re-export; prefer `music_monitor.services.processing` imports."""

from music_monitor.services.processing import (
    ProcessingService,
    discover_audio_files,
    ensure_unique_destination,
)

__all__ = ["ProcessingService", "discover_audio_files", "ensure_unique_destination"]
