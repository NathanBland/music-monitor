from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import SplitResult, urlsplit

import httpx

from music_monitor.types import AlbumLookupResult, NamingFormats

LOGGER = logging.getLogger(__name__)
NAMING_CONFIG_ENDPOINT = "/api/v1/config/naming"
SEARCH_ENDPOINT = "/api/v1/search"


@dataclass
class LidarrClient:
    """Small async client for Lidarr naming and album-art endpoints."""

    base_url: str
    api_key: str
    timeout_seconds: float = 10.0

    async def fetch_naming_formats(self) -> NamingFormats | None:
        """Fetch and validate Lidarr naming templates used for destination paths."""
        if not self.base_url or not self.api_key:
            LOGGER.info("lidarr_not_configured")
            return None

        payload = await self._get(NAMING_CONFIG_ENDPOINT)
        if not payload:
            return None

        entry = payload[0] if isinstance(payload, list) else payload
        standard_track_format = entry.get("standardTrackFormat")
        multi_disc_track_format = entry.get("multiDiscTrackFormat")
        artist_folder_format = entry.get("artistFolderFormat")

        if not (standard_track_format and multi_disc_track_format and artist_folder_format):
            LOGGER.warning("lidarr_naming_formats_incomplete", extra={"response": entry})
            return None

        return NamingFormats(
            artist_folder_format=artist_folder_format,
            standard_track_format=standard_track_format,
            multi_disc_track_format=multi_disc_track_format,
        )

    async def fetch_album_art(self, artist_name: str, album_title: str) -> bytes | None:
        """Search Lidarr for a matching album and return first available cover image bytes."""
        lookup_result = await self.fetch_album_lookup(artist_name, album_title)
        return lookup_result.album_art_bytes

    async def fetch_album_lookup(self, artist_name: str, album_title: str) -> AlbumLookupResult:
        """Fetch album art and release year metadata for a matched album search result."""
        if not self.base_url or not self.api_key:
            return AlbumLookupResult(album_art_bytes=None, release_year=None)

        search_term = f"{artist_name} {album_title}".strip()
        results = await self._get(SEARCH_ENDPOINT, params={"term": search_term})
        if not isinstance(results, list):
            return AlbumLookupResult(album_art_bytes=None, release_year=None)

        for result in results:
            result_album_title = str(result.get("albumTitle") or "").strip().lower()
            if result_album_title and result_album_title != album_title.lower():
                continue

            release_year = _extract_release_year(result)
            remote_covers = result.get("remoteCover") or result.get("remoteCovers") or []
            if isinstance(remote_covers, str):
                remote_covers = [remote_covers]

            if not remote_covers:
                if release_year:
                    return AlbumLookupResult(album_art_bytes=None, release_year=release_year)
                continue

            image_url = str(remote_covers[0])
            if not self._is_allowed_remote_url(image_url):
                LOGGER.warning("lidarr_art_url_not_allowed", extra={"url": image_url})
                if release_year:
                    return AlbumLookupResult(album_art_bytes=None, release_year=release_year)
                continue

            image_bytes = await self._download_binary(image_url, include_api_key=self._is_lidarr_url(image_url))
            if image_bytes or release_year:
                return AlbumLookupResult(album_art_bytes=image_bytes, release_year=release_year)

        return AlbumLookupResult(album_art_bytes=None, release_year=None)

    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Perform an authenticated GET request against the Lidarr API."""
        url = f"{self.base_url.rstrip('/')}{endpoint}"
        headers = {"X-Api-Key": self.api_key}

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
        except Exception as error:
            LOGGER.error("lidarr_request_failed", extra={"url": url, "error": str(error)})
            return None

        return response.json()

    async def _download_binary(self, url: str, include_api_key: bool = False) -> bytes | None:
        """Download binary content from a URL using Lidarr credentials."""
        headers: dict[str, str] = {}
        if include_api_key:
            headers["X-Api-Key"] = self.api_key

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
        except Exception as error:
            LOGGER.warning("lidarr_art_download_failed", extra={"url": url, "error": str(error)})
            return None

        return response.content

    def _is_allowed_remote_url(self, url: str) -> bool:
        """Return whether a remote URL is eligible for download."""
        parsed_url = urlsplit(url)
        if parsed_url.scheme not in {"http", "https"}:
            return False
        return self._is_lidarr_url(url)

    def _is_lidarr_url(self, url: str) -> bool:
        """Return whether a URL points to the configured Lidarr host and port."""
        parsed_url = urlsplit(url)
        parsed_base_url = urlsplit(self.base_url)
        return (
            parsed_url.scheme == parsed_base_url.scheme
            and parsed_url.hostname == parsed_base_url.hostname
            and _normalized_port(parsed_url) == _normalized_port(parsed_base_url)
        )


def _extract_release_year(result: dict[str, Any]) -> str | None:
    """Extract a release year from direct year fields or an ISO release date."""
    album_data = result.get("album")
    if not isinstance(album_data, dict):
        album_data = {}

    year_value = result.get("year", album_data.get("year"))
    if year_value is not None:
        try:
            return str(int(year_value))
        except (TypeError, ValueError):
            pass

    release_date = result.get("releaseDate", album_data.get("releaseDate"))
    if not release_date:
        return None

    try:
        parsed_date = datetime.fromisoformat(str(release_date).replace("Z", "+00:00"))
    except ValueError:
        return None

    return str(parsed_date.year)


def _normalized_port(parsed_url: SplitResult) -> int:
    """Return explicit URL port, or the default port for the parsed scheme."""
    if parsed_url.port is not None:
        return parsed_url.port
    if parsed_url.scheme == "https":
        return 443
    return 80
