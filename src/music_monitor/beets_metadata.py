"""Compatibility re-export; prefer `music_monitor.metadata.beets_writer` imports."""

from music_monitor.metadata.beets_writer import read_track_metadata, save_cover_art_sidecar, write_track_metadata

__all__ = ["read_track_metadata", "save_cover_art_sidecar", "write_track_metadata"]
