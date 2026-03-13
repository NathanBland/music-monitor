from __future__ import annotations

import pytest

from music_monitor.clients.coverart import CoverArtArchiveClient


class FakeResponse:
    def __init__(self, content: bytes, should_fail: bool = False) -> None:
        self.content = content
        self._should_fail = should_fail

    def raise_for_status(self) -> None:
        if self._should_fail:
            raise RuntimeError("bad status")


class FakeAsyncClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requested_urls: list[str] = []

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str) -> FakeResponse:
        self.requested_urls.append(url)
        return self.response


@pytest.mark.asyncio
async def test_fetch_front_cover_returns_none_for_missing_release_id() -> None:
    client = CoverArtArchiveClient()

    assert await client.fetch_front_cover(None) is None
    assert await client.fetch_front_cover("  ") is None


@pytest.mark.asyncio
async def test_fetch_front_cover_returns_bytes(monkeypatch) -> None:
    fake_client = FakeAsyncClient(FakeResponse(b"cover-bytes"))

    monkeypatch.setattr(
        "music_monitor.clients.coverart.httpx.AsyncClient",
        lambda timeout: fake_client,
    )

    client = CoverArtArchiveClient(timeout_seconds=5.0)
    result = await client.fetch_front_cover(" release-id ")

    assert result == b"cover-bytes"
    assert fake_client.requested_urls == ["https://coverartarchive.org/release/release-id/front"]


@pytest.mark.asyncio
async def test_fetch_front_cover_returns_none_on_request_error(monkeypatch) -> None:
    fake_client = FakeAsyncClient(FakeResponse(b"", should_fail=True))

    monkeypatch.setattr(
        "music_monitor.clients.coverart.httpx.AsyncClient",
        lambda timeout: fake_client,
    )

    client = CoverArtArchiveClient()

    assert await client.fetch_front_cover("release-id") is None
