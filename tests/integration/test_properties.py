import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")

_VALID_PROPERTIES = {
    "trackName": "Test",
    "artistName": "Artist",
    "collectionName": "Album",
    "artworkUrl100": "https://example.com/art.jpg",
    "primaryGenreName": "Pop",
    "trackNumber": 1,
    "trackCount": 10,
    "collectionId": "12345",
    "discNumber": 1,
    "discCount": 1,
    "releaseDate": "2020-01-01",
    "releaseDateKey": "2020-01-01",
}


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post("/v1/auth/login", json={"username": user.username, "password": "testpass123"})
    return dict(resp.cookies)


async def test_search_properties(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/properties/", params={"query": "test"}, cookies=cookies)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_put_properties(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        "/v1/properties/",
        json={"song_id": sample_song.uuid, "properties": _VALID_PROPERTIES},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["song_id"] == sample_song.uuid
