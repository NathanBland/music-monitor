from __future__ import annotations

import pytest

from music_monitor.clients.lidarr import LidarrClient


@pytest.mark.asyncio
async def test_fetch_naming_formats_returns_none_without_configuration() -> None:
    client = LidarrClient(base_url="", api_key="")

    result = await client.fetch_naming_formats()

    assert result is None


@pytest.mark.asyncio
async def test_fetch_naming_formats_from_payload(monkeypatch) -> None:
    client = LidarrClient(base_url="http://lidarr", api_key="key")

    async def fake_get(endpoint: str, params=None):
        assert endpoint == "/api/v1/config/naming"
        return {
            "artistFolderFormat": "{Artist Name}",
            "standardTrackFormat": "{Album Title}/{Track Title}",
            "multiDiscTrackFormat": "{Album Title}/{Medium Format} {medium:00}/{Track Title}",
        }

    monkeypatch.setattr(client, "_get", fake_get)

    naming = await client.fetch_naming_formats()

    assert naming is not None
    assert naming.artist_folder_format == "{Artist Name}"


@pytest.mark.asyncio
async def test_fetch_album_art_uses_first_cover(monkeypatch) -> None:
    client = LidarrClient(base_url="http://lidarr", api_key="key")

    async def fake_get(endpoint: str, params=None):
        assert endpoint == "/api/v1/search"
        assert params == {"term": "Artist Album"}
        return [{"albumTitle": "Album", "remoteCovers": ["http://img"]}]

    async def fake_download(url: str):
        assert url == "http://img"
        return b"img"

    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(client, "_download_binary", fake_download)

    result = await client.fetch_album_art("Artist", "Album")

    assert result == b"img"


@pytest.mark.asyncio
async def test_fetch_album_lookup_extracts_release_year(monkeypatch) -> None:
    client = LidarrClient(base_url="http://lidarr", api_key="key")

    async def fake_get(endpoint: str, params=None):
        assert endpoint == "/api/v1/search"
        return [
            {
                "albumTitle": "Album",
                "remoteCovers": ["http://img"],
                "releaseDate": "2011-02-03T00:00:00Z",
            }
        ]

    async def fake_download(_url: str):
        return b"img"

    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(client, "_download_binary", fake_download)

    lookup = await client.fetch_album_lookup("Artist", "Album")

    assert lookup.album_art_bytes == b"img"
    assert lookup.release_year == "2011"


@pytest.mark.asyncio
async def test_fetch_album_lookup_returns_year_without_cover(monkeypatch) -> None:
    client = LidarrClient(base_url="http://lidarr", api_key="key")

    async def fake_get(endpoint: str, params=None):
        assert endpoint == "/api/v1/search"
        return [{"albumTitle": "Album", "year": 2008}]

    monkeypatch.setattr(client, "_get", fake_get)

    lookup = await client.fetch_album_lookup("Artist", "Album")

    assert lookup.album_art_bytes is None
    assert lookup.release_year == "2008"


@pytest.mark.asyncio
async def test_fetch_album_lookup_reads_nested_album_release_date(monkeypatch) -> None:
    client = LidarrClient(base_url="http://lidarr", api_key="key")

    async def fake_get(endpoint: str, params=None):
        assert endpoint == "/api/v1/search"
        return [{"albumTitle": "Album", "album": {"releaseDate": "2007-12-18T00:00:00Z"}}]

    monkeypatch.setattr(client, "_get", fake_get)

    lookup = await client.fetch_album_lookup("Artist", "Album")

    assert lookup.album_art_bytes is None
    assert lookup.release_year == "2007"
