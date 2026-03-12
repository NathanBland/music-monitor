"""Compatibility re-export; prefer `music_monitor.metadata.beets_writer` imports."""

from music_monitor.metadata.beets_writer import read_track_metadata, write_track_metadata

__all__ = ["read_track_metadata", "write_track_metadata"]
