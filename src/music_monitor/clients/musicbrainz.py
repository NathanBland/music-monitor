from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import musicbrainzngs

from music_monitor.types import MusicBrainzLookupResult, TrackMetadata

LOGGER = logging.getLogger(__name__)
MUSICBRAINZ_DEFAULT_URL = "https://musicbrainz.org"
MUSICBRAINZ_DEFAULT_RATE_LIMIT_SECONDS = 1.0


@dataclass
class MusicBrainzClient:
    """Async adapter for MusicBrainz metadata lookups with built-in throttling."""

    user_agent: str
    rate_limit_seconds: float = MUSICBRAINZ_DEFAULT_RATE_LIMIT_SECONDS
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last_request_monotonic: float = 0.0

    def __post_init__(self) -> None:
        normalized_user_agent = self.user_agent.strip()
        if not normalized_user_agent:
            LOGGER.info("musicbrainz_not_configured")
            return

        musicbrainzngs.set_useragent(normalized_user_agent, "0.1.0", MUSICBRAINZ_DEFAULT_URL)

    async def fetch_track_lookup(self, metadata: TrackMetadata) -> MusicBrainzLookupResult:
        """Resolve metadata from MusicBrainz track/release IDs or text search fallback."""
        normalized_user_agent = self.user_agent.strip()
        if not normalized_user_agent:
            return MusicBrainzLookupResult()

        if metadata.musicbrainz_track_id and metadata.musicbrainz_album_id:
            lookup_by_ids = await self._lookup_by_ids(
                recording_id=metadata.musicbrainz_track_id,
                release_id=metadata.musicbrainz_album_id,
            )
            if lookup_by_ids.musicbrainz_album_id:
                return lookup_by_ids

        if metadata.musicbrainz_album_id:
            lookup_by_release = await self._lookup_by_release_id(metadata.musicbrainz_album_id)
            if lookup_by_release.musicbrainz_album_id:
                return lookup_by_release

        return await self._lookup_by_search(artist_name=metadata.artist_name, album_title=metadata.album_title)

    async def _lookup_by_ids(self, recording_id: str, release_id: str) -> MusicBrainzLookupResult:
        release_data = await self._get_release_by_id(release_id)
        if release_data is None:
            return MusicBrainzLookupResult()

        recording_data = await self._get_recording_by_id(recording_id)
        return _build_lookup_result(release_data, recording_data, recording_id=recording_id)

    async def _lookup_by_release_id(self, release_id: str) -> MusicBrainzLookupResult:
        release_data = await self._get_release_by_id(release_id)
        if release_data is None:
            return MusicBrainzLookupResult()

        return _build_lookup_result(release_data, recording_data=None, recording_id=None)

    async def _lookup_by_search(self, artist_name: str, album_title: str) -> MusicBrainzLookupResult:
        query_artist = artist_name.strip()
        query_album = album_title.strip()
        if not query_artist or not query_album:
            return MusicBrainzLookupResult()

        query_result = await self._search_release(query_artist, query_album)
        if query_result is None:
            return MusicBrainzLookupResult()

        release_list = query_result.get("release-list")
        if not isinstance(release_list, list) or not release_list:
            return MusicBrainzLookupResult()

        first_release = release_list[0]
        if not isinstance(first_release, dict):
            return MusicBrainzLookupResult()

        release_id = str(first_release.get("id") or "").strip()
        if not release_id:
            return MusicBrainzLookupResult()

        release_data = await self._get_release_by_id(release_id)
        if release_data is None:
            return MusicBrainzLookupResult()

        return _build_lookup_result(release_data, recording_data=None, recording_id=None)

    async def _search_release(self, artist_name: str, album_title: str) -> dict[str, object] | None:
        return await self._run_request(
            musicbrainzngs.search_releases,
            artist=artist_name,
            release=album_title,
            limit=1,
        )

    async def _get_release_by_id(self, release_id: str) -> dict[str, object] | None:
        response = await self._run_request(
            musicbrainzngs.get_release_by_id,
            release_id,
            includes=["artists", "recordings", "media"],
        )
        if not isinstance(response, dict):
            return None

        release_data = response.get("release")
        if not isinstance(release_data, dict):
            return None
        return release_data

    async def _get_recording_by_id(self, recording_id: str) -> dict[str, object] | None:
        response = await self._run_request(
            musicbrainzngs.get_recording_by_id,
            recording_id,
            includes=["artists", "releases"],
        )
        if not isinstance(response, dict):
            return None

        recording_data = response.get("recording")
        if not isinstance(recording_data, dict):
            return None
        return recording_data

    async def _run_request(self, function, *args, **kwargs):
        try:
            await self._respect_rate_limit()
            return await asyncio.to_thread(function, *args, **kwargs)
        except musicbrainzngs.NetworkError as error:
            LOGGER.warning("musicbrainz_network_error", extra={"error": str(error)})
            return None
        except musicbrainzngs.ResponseError as error:
            LOGGER.warning("musicbrainz_response_error", extra={"error": str(error)})
            return None

    async def _respect_rate_limit(self) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            elapsed_seconds = now - self._last_request_monotonic
            if self._last_request_monotonic > 0 and elapsed_seconds < self.rate_limit_seconds:
                await asyncio.sleep(self.rate_limit_seconds - elapsed_seconds)
            self._last_request_monotonic = asyncio.get_running_loop().time()


def _build_lookup_result(
    release_data: dict[str, object],
    recording_data: dict[str, object] | None,
    recording_id: str | None,
) -> MusicBrainzLookupResult:
    release_group_data = release_data.get("release-group")
    release_group = release_group_data if isinstance(release_group_data, dict) else {}

    media_list_data = release_data.get("medium-list")
    media_list = media_list_data if isinstance(media_list_data, list) else []

    artist_credit_data = release_data.get("artist-credit")
    artist_credit = artist_credit_data if isinstance(artist_credit_data, list) else []

    album_artist_id = _first_artist_credit_id(artist_credit)
    artist_name = _first_artist_credit_name(artist_credit)
    release_year = _extract_release_year(
        str(release_data.get("date") or "") or str(release_group.get("first-release-date") or "")
    )

    track_title: str | None = None
    track_number: int | None = None
    track_total: int | None = None
    medium_number: int | None = None
    medium_total = len(media_list) if media_list else None

    for medium_index, medium in enumerate(media_list, start=1):
        if not isinstance(medium, dict):
            continue

        track_list_data = medium.get("track-list")
        track_list = track_list_data if isinstance(track_list_data, list) else []
        for track_index, track in enumerate(track_list, start=1):
            if not isinstance(track, dict):
                continue

            current_recording_data = track.get("recording")
            current_recording = current_recording_data if isinstance(current_recording_data, dict) else {}
            current_recording_id = str(current_recording.get("id") or "").strip()
            if recording_id and current_recording_id != recording_id:
                continue

            track_title = str(track.get("title") or current_recording.get("title") or "").strip() or None
            track_number = _coerce_int(track.get("number")) or track_index
            track_total = len(track_list) if track_list else None
            medium_number = _coerce_int(medium.get("position")) or medium_index
            break

        if recording_id is None and track_list:
            first_track = track_list[0]
            if isinstance(first_track, dict):
                first_recording_data = first_track.get("recording")
                first_recording = first_recording_data if isinstance(first_recording_data, dict) else {}
                track_title = str(first_track.get("title") or first_recording.get("title") or "").strip() or None
                track_number = _coerce_int(first_track.get("number")) or 1
                track_total = len(track_list)
                medium_number = _coerce_int(medium.get("position")) or medium_index
            break

        if track_title:
            break

    resolved_recording_id = recording_id
    if resolved_recording_id is None and recording_data is not None:
        resolved_recording_id = str(recording_data.get("id") or "").strip() or None
    if track_title is None and recording_data is not None:
        track_title = str(recording_data.get("title") or "").strip() or None

    return MusicBrainzLookupResult(
        artist_name=artist_name,
        album_title=str(release_data.get("title") or "").strip() or None,
        track_title=track_title,
        track_number=track_number,
        track_total=track_total,
        medium_number=medium_number,
        medium_total=medium_total,
        release_year=release_year,
        musicbrainz_track_id=resolved_recording_id,
        musicbrainz_album_id=str(release_data.get("id") or "").strip() or None,
        musicbrainz_artist_id=album_artist_id,
        musicbrainz_album_artist_id=album_artist_id,
    )


def _first_artist_credit_name(artist_credit: list[object]) -> str | None:
    for credit in artist_credit:
        if not isinstance(credit, dict):
            continue
        artist_data = credit.get("artist")
        if not isinstance(artist_data, dict):
            continue
        artist_name = str(artist_data.get("name") or "").strip()
        if artist_name:
            return artist_name
    return None


def _first_artist_credit_id(artist_credit: list[object]) -> str | None:
    for credit in artist_credit:
        if not isinstance(credit, dict):
            continue
        artist_data = credit.get("artist")
        if not isinstance(artist_data, dict):
            continue
        artist_id = str(artist_data.get("id") or "").strip()
        if artist_id:
            return artist_id
    return None


def _extract_release_year(date_text: str) -> str | None:
    if not date_text:
        return None
    year_candidate = date_text.strip()[:4]
    if len(year_candidate) != 4 or not year_candidate.isdigit():
        return None
    return year_candidate


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    digits = "".join(character for character in text_value if character.isdigit())
    if not digits:
        return None
    return int(digits)
