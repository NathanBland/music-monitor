from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

LOGGER = logging.getLogger(__name__)
COVER_ART_ARCHIVE_BASE_URL = "https://coverartarchive.org"


@dataclass
class CoverArtArchiveClient:
    """Fetch front cover art from the MusicBrainz Cover Art Archive."""

    timeout_seconds: float = 10.0

    async def fetch_front_cover(self, release_id: str | None) -> bytes | None:
        """Return front cover bytes for a release ID when available."""
        if release_id is None:
            return None

        normalized_release_id = release_id.strip()
        if not normalized_release_id:
            return None

        url = f"{COVER_ART_ARCHIVE_BASE_URL}/release/{normalized_release_id}/front"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url)
                response.raise_for_status()
        except Exception as error:
            LOGGER.info(
                "cover_art_archive_fetch_failed",
                extra={"release_id": normalized_release_id, "error": str(error)},
            )
            return None

        return response.content
