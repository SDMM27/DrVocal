from unittest.mock import MagicMock

import pytest
from spotipy import SpotifyException

from drvocal.actions import Catalogue
from drvocal.actions_spotify import register_spotify
from drvocal.intent import Intent

NO_DEVICE = SpotifyException(404, -1, "NO_ACTIVE_DEVICE")


def _search(tracks=(), artists=(), albums=(), playlists=()):
    wrap = lambda items: {"items": list(items)}
    return {"tracks": wrap(tracks), "artists": wrap(artists), "albums": wrap(albums),
            "playlists": wrap(playlists)}


def _item(name, uri):
    return {"name": name, "uri": uri}


@pytest.fixture
def client():
    c = MagicMock()
    c.search.return_value = _search(tracks=[_item("Alors on danse", "spotify:track:1")])
    return c


async def run(client, action, **args):
    cat = Catalogue()
    register_spotify(cat, client)
    return await cat.run(Intent(action, args))


async def test_play_searches_then_starts_first_result(client):
    out = await run(client, "spotify.play", query="stromae")
    assert out.ok
    assert client.search.call_args.kwargs["limit"] <= 10
    client.start_playback.assert_called_once_with(uris=["spotify:track:1"])


async def test_play_exact_artist_match_plays_artist_context(client):
    client.search.return_value = _search(
        tracks=[_item("Autre", "spotify:track:9")],
        artists=[_item("Stromae", "spotify:artist:5")])
    out = await run(client, "spotify.play", query="stromae")
    assert out.ok
    client.start_playback.assert_called_once_with(context_uri="spotify:artist:5")


async def test_play_exact_album_match_plays_album_context(client):
    client.search.return_value = _search(
        tracks=[_item("x", "spotify:track:9")], albums=[_item("Racine carrée", "spotify:album:7")])
    await run(client, "spotify.play", query="Racine Carrée")
    client.start_playback.assert_called_once_with(context_uri="spotify:album:7")


async def test_play_no_result_returns_not_ok(client):
    client.search.return_value = _search()
    out = await run(client, "spotify.play", query="zzzz")
    assert not out.ok and out.speak
    client.start_playback.assert_not_called()


async def test_no_active_device_starts_on_local_spotify_device(client, monkeypatch):
    monkeypatch.setattr("drvocal.actions_spotify.socket.gethostname", lambda: "MON-PC")
    client.devices.return_value = {"devices": [
        {"id": "phone", "name": "iPhone", "type": "Smartphone"},
        {"id": "pc", "name": "MON-PC", "type": "Computer"}]}
    client.start_playback.side_effect = [NO_DEVICE, None]
    out = await run(client, "spotify.play", query="x")
    assert out.ok
    assert client.start_playback.call_args_list[1].kwargs["device_id"] == "pc"


async def test_no_active_device_falls_back_to_first_computer(client):
    client.devices.return_value = {"devices": [
        {"id": "phone", "name": "iPhone", "type": "Smartphone"},
        {"id": "pc2", "name": "Autre", "type": "Computer"}]}
    client.pause_playback.side_effect = [NO_DEVICE, None]
    out = await run(client, "spotify.pause")
    assert out.ok
    assert client.pause_playback.call_args_list[1].kwargs["device_id"] == "pc2"


async def test_no_device_at_all_returns_not_ok(client):
    client.devices.return_value = {"devices": []}
    client.start_playback.side_effect = NO_DEVICE
    out = await run(client, "spotify.play", query="x")
    assert not out.ok and out.speak
    assert client.start_playback.call_count == 1


async def test_network_error_returns_not_ok(client):
    client.search.side_effect = ConnectionError("down")
    out = await run(client, "spotify.play", query="x")
    assert not out.ok and out.speak


async def test_rate_limit_returns_not_ok(client):
    client.next_track.side_effect = SpotifyException(429, -1, "rate limit")
    assert not (await run(client, "spotify.next")).ok


@pytest.mark.parametrize("action,method", [
    ("spotify.pause", "pause_playback"),
    ("spotify.next", "next_track"),
    ("spotify.previous", "previous_track"),
])
async def test_simple_controls(client, action, method):
    assert (await run(client, action)).ok
    getattr(client, method).assert_called_once_with()


async def test_resume_starts_playback_without_arguments(client):
    assert (await run(client, "spotify.resume")).ok
    client.start_playback.assert_called_once_with()


@pytest.mark.parametrize("level,expected", [("40", 40), ("400", 100), ("0", 0)])
async def test_volume_is_clamped(client, level, expected):
    assert (await run(client, "spotify.volume", level=level)).ok
    client.volume.assert_called_once_with(expected)


async def test_non_numeric_volume_is_not_ok(client):
    out = await run(client, "spotify.volume", level="fort")
    assert not out.ok
    client.volume.assert_not_called()


def test_build_client_uses_pkce_with_minimal_scopes(tmp_path, monkeypatch):
    from drvocal import actions_spotify as mod
    seen = {}
    monkeypatch.setattr(mod.spotipy, "Spotify", lambda auth_manager: seen.update(am=auth_manager))
    mod.build_client("cid", tmp_path / "tok" / "cache.json")
    am = seen["am"]
    assert am.client_id == "cid"
    assert set(am.scope.split()) == {"user-read-playback-state", "user-modify-playback-state"}
    assert am.redirect_uri == mod.REDIRECT_URI
