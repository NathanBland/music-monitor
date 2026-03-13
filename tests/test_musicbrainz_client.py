from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from music_monitor.clients.musicbrainz import (
    MusicBrainzClient,
    _build_lookup_result,
    _coerce_int,
    _extract_release_year,
    _first_artist_credit_id,
    _first_artist_credit_name,
)
from music_monitor.types import MusicBrainzLookupResult, TrackMetadata


def make_metadata() -> TrackMetadata:
    return TrackMetadata(
        source_path=Path("/tmp/source.mp3"),
        artist_name="Artist",
        album_title="Album",
        track_title="Track",
        track_number=1,
        track_total=10,
        medium_number=1,
        medium_total=1,
        medium_format="Disc",
        release_year="2024",
        musicbrainz_track_id="track-id",
        musicbrainz_album_id="album-id",
    )


@pytest.mark.asyncio
async def test_fetch_track_lookup_returns_empty_when_user_agent_blank() -> None:
    client = MusicBrainzClient(user_agent="  ")

    result = await client.fetch_track_lookup(make_metadata())

    assert result == MusicBrainzLookupResult()


@pytest.mark.asyncio
async def test_fetch_track_lookup_uses_id_then_release_then_search(monkeypatch) -> None:
    client = MusicBrainzClient(user_agent="music-monitor-tests")
    metadata = make_metadata()

    async def fake_lookup_by_ids(recording_id: str, release_id: str) -> MusicBrainzLookupResult:
        assert recording_id == "track-id"
        assert release_id == "album-id"
        return MusicBrainzLookupResult(musicbrainz_album_id=None)

    async def fake_lookup_by_release_id(release_id: str) -> MusicBrainzLookupResult:
        assert release_id == "album-id"
        return MusicBrainzLookupResult(musicbrainz_album_id=None)

    async def fake_lookup_by_search(artist_name: str, album_title: str) -> MusicBrainzLookupResult:
        assert artist_name == "Artist"
        assert album_title == "Album"
        return MusicBrainzLookupResult(musicbrainz_album_id="resolved")

    monkeypatch.setattr(client, "_lookup_by_ids", fake_lookup_by_ids)
    monkeypatch.setattr(client, "_lookup_by_release_id", fake_lookup_by_release_id)
    monkeypatch.setattr(client, "_lookup_by_search", fake_lookup_by_search)

    result = await client.fetch_track_lookup(metadata)

    assert result.musicbrainz_album_id == "resolved"


@pytest.mark.asyncio
async def test_lookup_helpers_return_empty_when_release_missing(monkeypatch) -> None:
    client = MusicBrainzClient(user_agent="ua")

    async def fake_get_release(_release_id: str):
        return None

    monkeypatch.setattr(client, "_get_release_by_id", fake_get_release)

    by_ids = await client._lookup_by_ids("recording", "release")
    by_release = await client._lookup_by_release_id("release")

    assert by_ids == MusicBrainzLookupResult()
    assert by_release == MusicBrainzLookupResult()


@pytest.mark.asyncio
async def test_lookup_by_search_branch_conditions(monkeypatch) -> None:
    client = MusicBrainzClient(user_agent="ua")

    assert await client._lookup_by_search(" ", "Album") == MusicBrainzLookupResult()
    assert await client._lookup_by_search("Artist", " ") == MusicBrainzLookupResult()

    async def none_result(_artist_name: str, _album_title: str):
        return None

    monkeypatch.setattr(client, "_search_release", none_result)
    assert await client._lookup_by_search("Artist", "Album") == MusicBrainzLookupResult()

    async def non_list_result(_artist_name: str, _album_title: str):
        return {"release-list": "bad"}

    monkeypatch.setattr(client, "_search_release", non_list_result)
    assert await client._lookup_by_search("Artist", "Album") == MusicBrainzLookupResult()

    async def empty_list_result(_artist_name: str, _album_title: str):
        return {"release-list": []}

    monkeypatch.setattr(client, "_search_release", empty_list_result)
    assert await client._lookup_by_search("Artist", "Album") == MusicBrainzLookupResult()

    async def no_id_result(_artist_name: str, _album_title: str):
        return {"release-list": [{}]}

    monkeypatch.setattr(client, "_search_release", no_id_result)
    assert await client._lookup_by_search("Artist", "Album") == MusicBrainzLookupResult()


@pytest.mark.asyncio
async def test_get_release_and_recording_by_id_shape_checks(monkeypatch) -> None:
    client = MusicBrainzClient(user_agent="ua")

    async def fake_run_request(function, *args, **kwargs):
        if function.__name__ == "get_release_by_id":
            return {"release": {"id": "release-id", "title": "Album"}}
        return {"recording": {"id": "recording-id", "title": "Track"}}

    monkeypatch.setattr(client, "_run_request", fake_run_request)

    release = await client._get_release_by_id("release-id")
    recording = await client._get_recording_by_id("recording-id")

    assert release == {"id": "release-id", "title": "Album"}
    assert recording == {"id": "recording-id", "title": "Track"}


@pytest.mark.asyncio
async def test_run_request_handles_network_and_response_errors(monkeypatch) -> None:
    import musicbrainzngs

    client = MusicBrainzClient(user_agent="ua")

    def raising_network(*_args, **_kwargs):
        raise musicbrainzngs.NetworkError("offline")

    def raising_response(*_args, **_kwargs):
        raise musicbrainzngs.ResponseError("bad response")

    assert await client._run_request(raising_network) is None
    assert await client._run_request(raising_response) is None


@pytest.mark.asyncio
async def test_respect_rate_limit_sleeps_when_requests_are_too_close(monkeypatch) -> None:
    client = MusicBrainzClient(user_agent="ua", rate_limit_seconds=1.0)
    client._last_request_monotonic = 10.0

    class FakeLoop:
        def __init__(self) -> None:
            self.times = [10.4, 11.4]

        def time(self) -> float:
            return self.times.pop(0)

    sleep_durations: list[float] = []

    async def fake_sleep(duration: float) -> None:
        sleep_durations.append(duration)

    fake_loop = FakeLoop()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: fake_loop)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    await client._respect_rate_limit()

    assert sleep_durations == pytest.approx([0.6])


def test_build_lookup_result_and_helpers_cover_parsing_paths() -> None:
    release_data = {
        "id": "release-id",
        "title": "Album",
        "date": "2018-01-02",
        "artist-credit": [{"artist": {"name": "Artist", "id": "artist-id"}}],
        "release-group": {"first-release-date": "2017-01-01"},
        "medium-list": [
            {
                "position": "2",
                "track-list": [
                    {"number": "05", "title": "Track A", "recording": {"id": "recording-a", "title": "Track A"}},
                    {"number": "06", "title": "Track B", "recording": {"id": "recording-b", "title": "Track B"}},
                ],
            }
        ],
    }

    lookup = _build_lookup_result(release_data, recording_data=None, recording_id="recording-b")

    assert lookup.artist_name == "Artist"
    assert lookup.album_title == "Album"
    assert lookup.track_title == "Track B"
    assert lookup.track_number == 6
    assert lookup.track_total == 2
    assert lookup.medium_number == 2
    assert lookup.medium_total == 1
    assert lookup.release_year == "2018"
    assert lookup.musicbrainz_track_id == "recording-b"
    assert lookup.musicbrainz_album_id == "release-id"
    assert lookup.musicbrainz_artist_id == "artist-id"
    assert lookup.musicbrainz_album_artist_id == "artist-id"

    fallback_lookup = _build_lookup_result(
        {
            "id": "release-2",
            "title": "Album 2",
            "artist-credit": ["invalid"],
            "medium-list": [{"track-list": [{"recording": {"title": "Fallback"}}]}],
        },
        recording_data={"id": "recording-c", "title": "FromRecording"},
        recording_id=None,
    )

    assert fallback_lookup.track_title == "Fallback"
    assert fallback_lookup.track_number == 1
    assert fallback_lookup.musicbrainz_track_id == "recording-c"

    assert _first_artist_credit_name([{"artist": {"name": "Name"}}]) == "Name"
    assert _first_artist_credit_name([{"artist": {"name": " "}}]) is None
    assert _first_artist_credit_id([{"artist": {"id": "artist-1"}}]) == "artist-1"
    assert _first_artist_credit_id([{"artist": {"id": " "}}]) is None

    assert _extract_release_year("2020-11-10") == "2020"
    assert _extract_release_year("bad") is None
    assert _extract_release_year("") is None

    assert _coerce_int("12") == 12
    assert _coerce_int("disc 09") == 9
    assert _coerce_int("no digits") is None
    assert _coerce_int(None) is None
