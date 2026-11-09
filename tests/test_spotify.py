from unittest.mock import MagicMock

import pytest
from spotipy import SpotifyException

from drvocal.actions import Catalogue, Outcome
from drvocal.actions_spotify import register_spotify
from drvocal.intent import Intent
from drvocal.secrets_store import SecretStore
from drvocal.spotify_aliases import Aliases

NO_DEVICE = SpotifyException(404, -1, "NO_ACTIVE_DEVICE")


def _search(tracks=(), artists=(), albums=(), playlists=()):
    wrap = lambda items: {"items": list(items)}
    return {"tracks": wrap(tracks), "artists": wrap(artists), "albums": wrap(albums),
            "playlists": wrap(playlists)}


def _item(name, uri):
    return {"name": name, "uri": uri}


def playing_what_was_asked(c) -> dict:
    """Spotify obeissant : lit ce que le dernier start_playback a demande."""
    kwargs = c.start_playback.call_args.kwargs if c.start_playback.call_args else {}
    state = {"is_playing": True, "device": {"name": "PC"}}
    if "context_uri" in kwargs:
        state["context"] = {"uri": kwargs["context_uri"]}
    if "uris" in kwargs:
        state["item"] = {"uri": kwargs["uris"][0]}
    return state


@pytest.fixture
def client():
    c = MagicMock()
    c.search.return_value = _search(tracks=[_item("Alors on danse", "spotify:track:1")])
    c.current_playback.side_effect = lambda: playing_what_was_asked(c)
    c.current_user_followed_artists.return_value = {"artists": {"items": []}}
    c.current_user_top_artists.return_value = {"items": []}
    c.current_user_playlists.return_value = {"items": []}
    c.current_user_saved_tracks.return_value = {"items": []}
    c.current_user_recently_played.return_value = {"items": []}
    c.current_user_top_tracks.return_value = {"items": []}
    return c


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    monkeypatch.setattr("drvocal.actions_spotify.CONFIRM_POLL", 0)
    monkeypatch.setattr("drvocal.actions_spotify.CONFIRM_TIMEOUT", 0.02)


async def run(client, action, launch=None, **args):
    cat = Catalogue()
    register_spotify(cat, client, launch=launch, preload=False)
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


async def test_play_close_artist_name_plays_artist_context(client):
    client.search.return_value = _search(
        tracks=[_item("Autre", "spotify:track:9")], artists=[_item("Stromae", "spotify:artist:5")])
    await run(client, "spotify.play", query="stromer")
    client.start_playback.assert_called_once_with(context_uri="spotify:artist:5")


async def test_play_distant_artist_name_plays_first_track(client):
    client.search.return_value = _search(
        tracks=[_item("Autre", "spotify:track:9")], artists=[_item("P!nk", "spotify:artist:5")])
    await run(client, "spotify.play", query="deftPink")
    client.start_playback.assert_called_once_with(uris=["spotify:track:9"])


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


async def test_no_device_opens_spotify_then_plays_on_it(client, monkeypatch):
    monkeypatch.setattr("drvocal.actions_spotify.LAUNCH_POLL", 0)
    client.devices.side_effect = [
        {"devices": []}, {"devices": []},
        {"devices": [{"id": "pc", "name": "MON-PC", "type": "Computer"}]}]
    client.start_playback.side_effect = [NO_DEVICE, None]
    launch = MagicMock()
    out = await run(client, "spotify.play", launch=launch, query="x")
    assert out.ok
    launch.assert_called_once_with()
    assert client.start_playback.call_args_list[1].kwargs["device_id"] == "pc"


async def test_opened_spotify_never_appears_returns_not_ok(client, monkeypatch):
    monkeypatch.setattr("drvocal.actions_spotify.LAUNCH_POLL", 0)
    monkeypatch.setattr("drvocal.actions_spotify.LAUNCH_TIMEOUT", 0.05)
    client.devices.return_value = {"devices": []}
    client.start_playback.side_effect = NO_DEVICE
    out = await run(client, "spotify.play", launch=MagicMock(), query="x")
    assert not out.ok and out.speak
    assert client.start_playback.call_count == 1


async def test_launch_failure_returns_not_ok(client):
    client.devices.return_value = {"devices": []}
    client.start_playback.side_effect = NO_DEVICE
    out = await run(client, "spotify.play", launch=MagicMock(side_effect=OSError), query="x")
    assert not out.ok and out.speak


async def test_pause_never_opens_spotify(client):
    client.devices.return_value = {"devices": []}
    client.pause_playback.side_effect = NO_DEVICE
    launch = MagicMock()
    out = await run(client, "spotify.pause", launch=launch)
    assert not out.ok
    launch.assert_not_called()


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


def test_build_client_uses_pkce_with_library_scopes(tmp_path, monkeypatch):
    from drvocal import actions_spotify as mod
    seen = {}
    monkeypatch.setattr(mod.spotipy, "Spotify", lambda auth_manager: seen.update(am=auth_manager))
    mod.build_client("cid", mod.SecretStoreCacheHandler(SecretStore(tmp_path / "tok")))
    am = seen["am"]
    assert am.client_id == "cid"
    assert set(am.scope.split()) == {
        "user-read-playback-state", "user-modify-playback-state",
        "user-follow-read", "user-top-read", "playlist-read-private",
        "user-library-read", "user-read-recently-played",
        "user-library-modify", "playlist-modify-private", "playlist-modify-public"}
    assert am.redirect_uri == mod.REDIRECT_URI


def test_cache_handler_roundtrips_token_in_secret_store(tmp_path):
    from drvocal import actions_spotify as mod
    handler = mod.SecretStoreCacheHandler(SecretStore(tmp_path))
    assert handler.get_cached_token() is None
    handler.save_token_to_cache({"access_token": "ACCES-SECRET", "refresh_token": "R"})
    assert handler.get_cached_token() == {"access_token": "ACCES-SECRET", "refresh_token": "R"}
    assert b"ACCES-SECRET" not in b"".join(p.read_bytes() for p in tmp_path.iterdir())


def test_cache_handler_ignores_garbage_token(tmp_path):
    from drvocal import actions_spotify as mod
    store = SecretStore(tmp_path)
    store.set("spotify_token", "pas du json")
    assert mod.SecretStoreCacheHandler(store).get_cached_token() is None


def _library(client, followed=(), top=(), playlists=()):
    client.current_user_followed_artists.return_value = {"artists": {"items": list(followed)}}
    client.current_user_top_artists.return_value = {"items": list(top)}
    client.current_user_playlists.return_value = {"items": list(playlists)}


@pytest.mark.parametrize("query", ["d'Ariano", "daryana", "Daria Na"])
async def test_library_artist_matches_approximate_name(client, query):
    _library(client, followed=[_item("daryana", "spotify:artist:dar")])
    out = await run(client, "spotify.play", query=query)
    assert out.ok
    client.start_playback.assert_called_once_with(context_uri="spotify:artist:dar")


async def test_exact_library_name_skips_search(client):
    _library(client, followed=[_item("daryana", "spotify:artist:dar")])
    await run(client, "spotify.play", query="Daryana")
    client.search.assert_not_called()


async def test_exact_catalogue_name_beats_approximate_library_name(client):
    _library(client, followed=[_item("Ange", "spotify:artist:ange")])
    client.search.return_value = _search(artists=[_item("Angèle", "spotify:artist:angele")])
    await run(client, "spotify.play", query="Angèle")
    client.start_playback.assert_called_once_with(context_uri="spotify:artist:angele")


async def test_library_close_to_misheard_name_plays_it(client):
    _library(client, top=[_item("Daft Punk", "spotify:artist:dp")])
    await run(client, "spotify.play", query="deft pink")
    client.start_playback.assert_called_once_with(context_uri="spotify:artist:dp")


async def test_library_playlist_and_dedup(client):
    _library(client, followed=[None, _item("Daft Punk", "spotify:artist:dp")],
             top=[_item("Daft Punk", "spotify:artist:dp")],
             playlists=[None, _item("Sport", "spotify:playlist:s")])
    await run(client, "spotify.play", query="sport")
    client.start_playback.assert_called_once_with(context_uri="spotify:playlist:s")


async def test_library_without_match_uses_normal_search(client):
    _library(client, followed=[_item("Daft Punk", "spotify:artist:dp"), _item("daryana", "spotify:artist:dar")])
    await run(client, "spotify.play", query="musique")
    client.search.assert_called_once()
    client.start_playback.assert_called_once_with(uris=["spotify:track:1"])


async def test_library_failure_does_not_block_playback_or_playlists(client):
    _library(client, playlists=[_item("Sport", "spotify:playlist:s")])
    client.current_user_followed_artists.side_effect = SpotifyException(403, -1, "Insufficient client scope")
    out = await run(client, "spotify.play", query="sport")
    assert out.ok
    client.start_playback.assert_called_once_with(context_uri="spotify:playlist:s")


async def test_library_total_failure_falls_back_to_search(client):
    for m in (client.current_user_followed_artists, client.current_user_top_artists,
              client.current_user_playlists, client.current_user_saved_tracks,
              client.current_user_recently_played, client.current_user_top_tracks):
        m.side_effect = ConnectionError("down")
    out = await run(client, "spotify.play", query="stromae")
    assert out.ok
    client.start_playback.assert_called_once_with(uris=["spotify:track:1"])


async def test_library_loaded_once_for_two_plays(client):
    cat = Catalogue()
    register_spotify(cat, client, launch=None, preload=False)
    await cat.run(Intent("spotify.play", {"query": "a"}))
    await cat.run(Intent("spotify.play", {"query": "b"}))
    client.current_user_followed_artists.assert_called_once()
    assert client.current_user_top_artists.call_count == 2  # moyen et court terme
    client.current_user_playlists.assert_called_once()
    client.current_user_saved_tracks.assert_called_once()
    client.current_user_recently_played.assert_called_once()
    assert client.current_user_top_tracks.call_count == 2


async def test_library_reloaded_after_ttl(client, monkeypatch):
    monkeypatch.setattr("drvocal.actions_spotify.LIBRARY_TTL", -1)
    cat = Catalogue()
    register_spotify(cat, client, launch=None, preload=False)
    await cat.run(Intent("spotify.play", {"query": "a"}))
    await cat.run(Intent("spotify.play", {"query": "b"}))
    assert client.current_user_followed_artists.call_count == 2


async def test_play_retries_on_local_device_when_not_playing(client, monkeypatch):
    monkeypatch.setattr("drvocal.actions_spotify.CONFIRM_TIMEOUT", 0)  # un seul sondage par verification
    client.current_playback.side_effect = [{}, {"is_playing": False, "device": {"name": "PC"}},
                                           {"is_playing": True, "item": {"uri": "spotify:track:1"}}]
    client.devices.return_value = {"devices": [{"id": "pc", "name": "PC", "type": "Computer"}]}
    out = await run(client, "spotify.play", query="x")
    assert out.ok
    calls = client.start_playback.call_args_list
    assert len(calls) == 2 and calls[1].kwargs == {"uris": ["spotify:track:1"], "device_id": "pc"}


async def test_play_never_starting_returns_not_ok(client):
    client.current_playback.side_effect = None
    client.current_playback.return_value = None
    client.devices.return_value = {"devices": [{"id": "pc", "name": "PC", "type": "Computer"}]}
    out = await run(client, "spotify.play", query="x")
    assert not out.ok and out.speak == "Spotify n'a pas lancé la lecture, je remets ta musique."
    assert client.start_playback.call_count == 2


async def test_resume_confirms_and_retries(client):
    client.current_playback.side_effect = None
    client.current_playback.return_value = {"is_playing": False}
    client.devices.return_value = {"devices": [{"id": "pc", "name": "PC", "type": "Computer"}]}
    out = await run(client, "spotify.resume")
    assert not out.ok
    assert client.start_playback.call_args_list[1].kwargs == {"device_id": "pc"}


async def test_old_song_still_playing_is_not_a_success(client):
    client.current_playback.side_effect = None
    client.current_playback.return_value = {"is_playing": True, "item": {"uri": "spotify:track:ancien"}}
    client.devices.return_value = {"devices": [{"id": "pc", "name": "PC", "type": "Computer"}]}
    out = await run(client, "spotify.play", query="x")
    assert not out.ok
    assert client.start_playback.call_count == 3  # essai, nouvelle tentative, restauration de l'ancien
    assert client.start_playback.call_args.kwargs["uris"] == ["spotify:track:ancien"]


async def test_relinked_track_counts_as_requested(client):
    client.current_playback.side_effect = None
    client.current_playback.return_value = {
        "is_playing": True, "item": {"uri": "spotify:track:fr", "linked_from": {"uri": "spotify:track:1"}}}
    assert (await run(client, "spotify.play", query="x")).ok
    assert client.start_playback.call_count == 1


async def test_artist_reported_without_context_counts_as_requested(client):
    # Spotify ne rapporte pas de contexte pour un artiste : on regarde les artistes du titre.
    _library(client, followed=[_item("daryana", "spotify:artist:dar")])
    client.current_playback.side_effect = None
    client.current_playback.return_value = {
        "is_playing": True, "context": None,
        "item": {"uri": "spotify:track:juice", "artists": [{"uri": "spotify:artist:dar"}]}}
    assert (await run(client, "spotify.play", query="daryana")).ok
    assert client.start_playback.call_count == 1


async def test_dj_starts_the_dj_playlist(client):
    assert (await run(client, "spotify.dj")).ok
    client.start_playback.assert_called_once_with(context_uri="spotify:playlist:37i9dQZF1EYkqdzj48dyYq")


async def test_my_playlist_searches_only_my_playlists_first(client):
    _library(client, followed=[_item("Disco", "spotify:artist:disco")],
             playlists=[_item("Rital List 🇮🇹", "spotify:playlist:rital")])
    await run(client, "spotify.play", query="Rital list", kind="playlist")
    client.start_playback.assert_called_once_with(context_uri="spotify:playlist:rital")
    client.search.assert_not_called()


async def test_unknown_playlist_falls_back_to_close_catalogue_playlist(client):
    client.search.return_value = _search(playlists=[None, _item("Disco 80", "spotify:playlist:d80")])
    await run(client, "spotify.play", query="disco", kind="playlist")
    assert client.search.call_args.kwargs["type"] == "playlist"
    client.start_playback.assert_called_once_with(context_uri="spotify:playlist:d80")


async def test_all_playlist_pages_are_loaded(client):
    page2 = {"items": [_item("Rital List", "spotify:playlist:rital")], "next": None}
    client.current_user_playlists.return_value = {"items": [_item("Autre", "spotify:playlist:a")], "next": "url"}
    client.next.return_value = page2
    await run(client, "spotify.play", query="Rital List", kind="playlist")
    client.start_playback.assert_called_once_with(context_uri="spotify:playlist:rital")


async def test_cyrillic_playlist_matches_its_spoken_latin_transcription(client):
    _library(client, playlists=[_item("🕺Дискотека 🚗", "spotify:playlist:disko"),
                                _item("Rital List", "spotify:playlist:rital")])
    await run(client, "spotify.play", query="Disco tier 4", kind="playlist")
    client.start_playback.assert_called_once_with(context_uri="spotify:playlist:disko")


def _stuck_on_old_song(client, context=None):
    """Spotify continue l'ancien titre puis refuse le nouveau : il ne lit jamais la demande."""
    client.current_playback.side_effect = None
    client.current_playback.return_value = {
        "is_playing": True, "progress_ms": 61000, "context": context,
        "item": {"uri": "spotify:track:ancien", "artists": []}}
    client.devices.return_value = {"devices": [{"id": "pc", "name": "PC", "type": "Computer"}]}


async def test_failed_play_restores_previous_track_in_its_playlist(client):
    _stuck_on_old_song(client, {"uri": "spotify:playlist:p", "type": "playlist"})
    out = await run(client, "spotify.play", query="x")
    assert not out.ok
    assert client.start_playback.call_args.kwargs == {
        "context_uri": "spotify:playlist:p", "offset": {"uri": "spotify:track:ancien"}, "position_ms": 61000}


async def test_failed_play_restores_previous_track_without_context(client):
    _stuck_on_old_song(client)
    await run(client, "spotify.play", query="x")
    assert client.start_playback.call_args.kwargs == {"uris": ["spotify:track:ancien"], "position_ms": 61000}


async def test_failed_play_with_nothing_playing_restores_nothing(client):
    client.current_playback.side_effect = None
    client.current_playback.return_value = {"is_playing": False}
    client.devices.return_value = {"devices": [{"id": "pc", "name": "PC", "type": "Computer"}]}
    await run(client, "spotify.play", query="x")
    assert client.start_playback.call_count == 2  # essai + nouvelle tentative, pas de restauration


async def test_restore_failure_is_not_fatal(client):
    _stuck_on_old_song(client)
    client.start_playback.side_effect = [None, None, SpotifyException(403, -1, "restricted")]
    out = await run(client, "spotify.play", query="x")
    assert not out.ok and out.speak


PAO = {"name": "Mc Pao", "uri": "spotify:artist:pao"}
RICHESSE = {"name": "Fausse Richesse", "uri": "spotify:track:richesse", "artists": [PAO]}


def _liked(*tracks):
    return {"items": [{"track": t} for t in tracks]}


async def test_liked_track_is_played_by_artist_and_title(client):
    client.current_user_saved_tracks.return_value = _liked(RICHESSE)
    out = await run(client, "spotify.play", query="MCPOW, fausse richesse")
    assert out.ok
    client.start_playback.assert_called_once_with(uris=["spotify:track:richesse"])
    client.search.assert_not_called()


async def test_artist_of_liked_track_is_played_as_artist(client):
    client.current_user_saved_tracks.return_value = _liked(RICHESSE)
    await run(client, "spotify.play", query="MC Pao")
    client.start_playback.assert_called_once_with(context_uri="spotify:artist:pao")


async def test_recent_and_top_tracks_enter_the_library(client):
    client.current_user_recently_played.return_value = _liked(RICHESSE)
    client.current_user_top_tracks.return_value = {"items": [
        {"name": "Alors", "uri": "spotify:track:alors", "artists": [{"name": "Stromae", "uri": "spotify:artist:stro"}]}]}
    await run(client, "spotify.play", query="Stromae")
    client.start_playback.assert_called_once_with(context_uri="spotify:artist:stro")
    client.start_playback.reset_mock()
    await run(client, "spotify.play", query="fausse richesse")
    client.start_playback.assert_called_once_with(uris=["spotify:track:richesse"])


async def test_short_track_name_does_not_capture_a_misheard_artist(client):
    client.current_user_saved_tracks.return_value = _liked(
        {"name": "Pink", "uri": "spotify:track:pink", "artists": []})
    await run(client, "spotify.play", query="deft pink")
    client.start_playback.assert_called_once_with(uris=["spotify:track:1"])  # premier resultat de recherche


async def test_local_tracks_are_ignored(client):
    client.current_user_saved_tracks.return_value = _liked(
        {"name": "Fausse Richesse", "uri": "spotify:local:x", "is_local": True, "artists": [PAO]}, None)
    client.current_user_saved_tracks.return_value["items"].append({"track": None})
    await run(client, "spotify.play", query="fausse richesse")
    client.search.assert_called_once()
    client.start_playback.assert_called_once_with(uris=["spotify:track:1"])


async def test_liked_tracks_pages_are_loaded(client):
    other = {"name": "Autre", "uri": "spotify:track:autre", "artists": []}
    client.current_user_saved_tracks.return_value = {**_liked(other), "next": "url"}
    client.next.return_value = {**_liked(RICHESSE), "next": None}
    await run(client, "spotify.play", query="fausse richesse")
    client.start_playback.assert_called_once_with(uris=["spotify:track:richesse"])


async def test_liked_tracks_failure_keeps_other_sources(client):
    _library(client, playlists=[_item("Sport", "spotify:playlist:s")])
    client.current_user_saved_tracks.side_effect = SpotifyException(403, -1, "Insufficient client scope")
    out = await run(client, "spotify.play", query="sport")
    assert out.ok
    client.start_playback.assert_called_once_with(context_uri="spotify:playlist:s")


def test_library_entries_have_no_duplicate_name_for_one_uri(client):
    from drvocal.actions_spotify import Library
    client.current_user_saved_tracks.return_value = _liked(RICHESSE, RICHESSE)
    client.current_user_recently_played.return_value = _liked(RICHESSE)
    entries = Library(client).entries()
    assert len(entries) == len(set(entries)) == 3  # titre, "artiste titre", artiste


def test_preload_loads_library_without_any_action(client):
    import threading
    cat = Catalogue()
    register_spotify(cat, client, launch=None)
    for t in threading.enumerate():
        if t.name == "spotify-library":
            t.join(5)
    client.current_user_followed_artists.assert_called_once()
    client.current_user_saved_tracks.assert_called_once()
    client.start_playback.assert_not_called()


def test_library_match_is_fast_on_3000_names():
    import random
    import string
    import time

    from drvocal.actions_spotify import _library_match
    rnd = random.Random(1)
    entries = [("".join(rnd.choice(string.ascii_lowercase + " ") for _ in range(rnd.randint(15, 30))),
                f"spotify:track:{i}") for i in range(3000)]
    _library_match(entries, "warmup")
    start = time.perf_counter()
    _library_match(entries, "d'mcpow fausse richesse")
    assert time.perf_counter() - start < 0.5


async def test_weak_neighbour_does_not_beat_strong_artist_on_guessed_variant(client):
    # "d'Ariano" : sans "d'", "ariano" ressemble a Aria (titre like) ; daryana est suivie.
    tracks = [{"track": {"uri": "spotify:track:a", "name": "Song", "artists": [_item("Aria", "spotify:artist:aria")]}}]
    _library(client, followed=[_item("daryana", "spotify:artist:dar")])
    client.current_user_saved_tracks.return_value = {"items": tracks}
    await run(client, "spotify.play", query="d'Ariano")
    client.start_playback.assert_called_once_with(context_uri="spotify:artist:dar")


async def test_weak_artist_needs_close_name(client):
    tracks = [{"track": {"uri": "spotify:track:a", "name": "Song", "artists": [_item("MC PR", "spotify:artist:mcpr")]}}]
    client.current_user_saved_tracks.return_value = {"items": tracks}
    client.search.return_value = _search(artists=[_item("Mc Pao", "spotify:artist:pao")])
    await run(client, "spotify.play", query="MC Pao")
    client.start_playback.assert_called_once_with(context_uri="spotify:artist:pao")


def test_library_vocabulary_never_loads_and_filters(client):
    from drvocal.actions_spotify import Library

    lib = Library(client)
    assert lib.vocabulary() == []
    client.current_user_followed_artists.assert_not_called()
    lib._entries = [("Zaz", "spotify:artist:1"), ("Mix", "spotify:playlist:1"), ("Faible", "spotify:artist:2"),
                    ("Titre", "spotify:track:1"), ("Autre", "spotify:artist:3")]
    lib._loaded_strong = frozenset({"spotify:artist:1", "spotify:playlist:1", "spotify:track:1", "spotify:artist:3"})
    assert lib.vocabulary() == ["Mix", "Zaz", "Autre"]
    assert lib.vocabulary(limit=2) == ["Mix", "Zaz"]
    client.current_user_followed_artists.assert_not_called()


def _aliased(client, tmp_path):
    cat, aliases = Catalogue(), Aliases(tmp_path / "aliases.json")
    register_spotify(cat, client, preload=False, aliases=aliases)
    return cat, aliases


async def test_remember_playlist_context_then_play_it_immediately(client, tmp_path):
    cat, aliases = _aliased(client, tmp_path)
    uri = "spotify:playlist:37i9dQZF1EpumwTEC0haas"
    client.current_playback.side_effect = None
    client.current_playback.return_value = {"is_playing": True, "context": {"uri": uri, "type": "playlist"},
                                            "item": {"uri": "spotify:track:1"}}
    out = await cat.run(Intent("spotify.remember", {"name": "En boucle"}))
    assert out == Outcome(True, "C'est noté : En boucle.")
    assert aliases.items() == [("En boucle", uri)]
    client.current_playback.side_effect = lambda: playing_what_was_asked(client)
    await cat.run(Intent("spotify.play", {"query": "en boucle", "kind": "playlist", "mine": "1"}))
    client.start_playback.assert_called_once_with(context_uri=uri)
    client.search.assert_not_called()
    client.current_user_playlists.assert_called_once()  # bibliotheque chargee avant l'alias, alias vu quand meme


async def test_remember_falls_back_to_current_track_and_plays_it(client, tmp_path):
    cat, _ = _aliased(client, tmp_path)
    client.current_playback.side_effect = None
    client.current_playback.return_value = {"is_playing": True, "item": {"uri": "spotify:track:77"}}
    assert (await cat.run(Intent("spotify.remember", {"name": "Mon tube"}))).ok
    client.current_playback.side_effect = lambda: playing_what_was_asked(client)
    await cat.run(Intent("spotify.play", {"query": "mon tube"}))
    client.start_playback.assert_called_once_with(uris=["spotify:track:77"])


async def test_remember_with_nothing_playing(client, tmp_path):
    cat, aliases = _aliased(client, tmp_path)
    client.current_playback.side_effect = None
    client.current_playback.return_value = None
    assert await cat.run(Intent("spotify.remember", {"name": "X"})) == Outcome(False, "Rien ne joue sur Spotify.")
    assert aliases.items() == []


async def test_cyrillic_alias_is_found_by_latin_query(client, tmp_path):
    cat, aliases = _aliased(client, tmp_path)
    aliases.add("На повторе", "spotify:playlist:37i9loop")
    await cat.run(Intent("spotify.play", {"query": "na povtore", "kind": "playlist", "mine": "1"}))
    client.start_playback.assert_called_once_with(context_uri="spotify:playlist:37i9loop")


async def test_my_unknown_playlist_never_searches_the_catalogue(client):
    out = await run(client, "spotify.play", query="inconnue", kind="playlist", mine="1")
    assert not out.ok
    assert "retiens cette playlist" in out.speak
    client.search.assert_not_called()
    client.start_playback.assert_not_called()


async def test_the_playlist_without_close_name_starts_nothing(client):
    client.search.return_value = _search(playlists=[_item("Totalement autre chose", "spotify:playlist:x")])
    out = await run(client, "spotify.play", query="sport", kind="playlist")
    assert not out.ok
    client.start_playback.assert_not_called()


# --- ecritures dans la bibliotheque : like, ajout a une playlist, annulation ---

TRACK = "spotify:track:42"


def _writable(client, playlists, me="moi"):
    client.me.return_value = {"id": me}
    client.current_user_playlists.return_value = {"items": list(playlists)}
    client.current_playback.side_effect = None
    client.current_playback.return_value = {"is_playing": True, "item": {"uri": TRACK, "name": "Alors on danse"}}
    client._post.return_value = {"snapshot_id": "snap1"}


def _pl(name, pid, owner="moi", collaborative=False):
    return {"name": name, "uri": f"spotify:playlist:{pid}", "owner": {"id": owner}, "collaborative": collaborative}


async def test_like_uses_library_endpoint_and_plays_nothing(client):
    _writable(client, [])
    out = await run(client, "spotify.like")
    assert out == Outcome(True, "Ajouté à tes titres likés : Alors on danse.")
    client._put.assert_called_once_with("me/library", uris=TRACK)
    client.current_user_saved_tracks_add.assert_not_called()
    client.start_playback.assert_not_called()


@pytest.mark.parametrize("state", [None, {"is_playing": True, "item": {"uri": "spotify:episode:1"}}])
async def test_like_without_track(client, state):
    client.current_playback.side_effect = None
    client.current_playback.return_value = state
    assert await run(client, "spotify.like") == Outcome(False, "Aucun titre en cours.")
    client._put.assert_not_called()


@pytest.mark.parametrize("query,name,pid", [
    ("Rital Liste", "Rital List", "rl"),
    ("na povtore", "На повторе", "np"),
])
async def test_add_to_owned_playlist_fuzzy(client, query, name, pid):
    _writable(client, [_pl("Rital List", "rl"), _pl("На повторе", "np"), _pl("Autre", "zz")])
    out = await run(client, "spotify.add_to_playlist", playlist=query)
    assert out == Outcome(True, f"Ajouté à {name}.")
    client._post.assert_called_once_with(f"playlists/{pid}/items", payload={"uris": [TRACK]})
    client.start_playback.assert_not_called()


async def test_add_to_collaborative_playlist(client):
    _writable(client, [_pl("Soirée", "so", owner="autre", collaborative=True)])
    assert (await run(client, "spotify.add_to_playlist", playlist="soirée")).ok


async def test_add_refused_for_foreign_playlist_and_for_alias(client, tmp_path):
    _writable(client, [_pl("Chill", "ch", owner="autre")])
    cat, aliases = _aliased(client, tmp_path)
    aliases.add("En boucle", "spotify:playlist:alias")
    for query in ("chill", "en boucle"):
        out = await cat.run(Intent("spotify.add_to_playlist", {"playlist": query}))
        assert out == Outcome(False, "Je ne trouve pas cette playlist parmi les tiennes.")
    client._post.assert_not_called()


async def test_add_without_profile_means_nothing_editable(client):
    _writable(client, [_pl("Rital List", "rl")])
    client.me.side_effect = SpotifyException(401, -1, "nope")
    out = await run(client, "spotify.add_to_playlist", playlist="Rital List")
    assert out.speak == "Je ne trouve pas cette playlist parmi les tiennes."


async def test_undo_like(client):
    _writable(client, [])
    cat = Catalogue()
    register_spotify(cat, client, preload=False)
    await cat.run(Intent("spotify.like", {}))
    assert await cat.run(Intent("spotify.undo", {})) == Outcome(True, "Annulé.")
    client._delete.assert_called_once_with("me/library", uris=TRACK)
    assert await cat.run(Intent("spotify.undo", {})) == Outcome(False, "Rien à annuler.")
    client._delete.assert_called_once()


async def test_undo_playlist_add_sends_snapshot(client):
    _writable(client, [_pl("Rital List", "rl")])
    cat = Catalogue()
    register_spotify(cat, client, preload=False)
    await cat.run(Intent("spotify.add_to_playlist", {"playlist": "rital list"}))
    assert await cat.run(Intent("spotify.undo", {})) == Outcome(True, "Annulé.")
    client._delete.assert_called_once_with(
        "playlists/rl/items", payload={"items": [{"uri": TRACK}], "snapshot_id": "snap1"})
    assert (await cat.run(Intent("spotify.undo", {}))).speak == "Rien à annuler."


async def test_undo_nothing_and_too_late(client, monkeypatch):
    _writable(client, [])
    cat = Catalogue()
    register_spotify(cat, client, preload=False)
    assert await cat.run(Intent("spotify.undo", {})) == Outcome(False, "Rien à annuler.")
    await cat.run(Intent("spotify.like", {}))
    monkeypatch.setattr("drvocal.actions_spotify.UNDO_WINDOW", -1.0)
    assert await cat.run(Intent("spotify.undo", {})) == Outcome(False, "Rien à annuler.")
    client._delete.assert_not_called()


@pytest.mark.parametrize("message,speak", [
    ("Insufficient client scope", "Spotify refuse : réautorise Dr Vocal avec tools/spotify_login.py."),
    ("Forbidden", "Spotify refuse de modifier cette playlist."),
])
async def test_forbidden_add_message(client, caplog, message, speak):
    _writable(client, [_pl("Rital List", "rl")])
    client._post.side_effect = SpotifyException(403, -1, message)
    out = await run(client, "spotify.add_to_playlist", playlist="rital list")
    assert out == Outcome(False, speak)
    assert "playlists/items" in caplog.text and "403" in caplog.text


async def test_forbidden_like_scope(client):
    _writable(client, [])
    client._put.side_effect = SpotifyException(403, -1, "Insufficient client scope")
    out = await run(client, "spotify.like")
    assert out.speak == "Spotify refuse : réautorise Dr Vocal avec tools/spotify_login.py."


@pytest.mark.parametrize("step,current,expected", [("up", 40, 55), ("down", 40, 25), ("up", 95, 100), ("down", 5, 0)])
async def test_relative_volume_moves_from_current_level(client, step, current, expected):
    client.current_playback.side_effect = None
    client.current_playback.return_value = {"device": {"volume_percent": current}}
    assert (await run(client, "spotify.volume", step=step)).ok
    client.volume.assert_called_once_with(expected)


async def test_relative_volume_without_known_level_is_not_ok(client):
    client.current_playback.side_effect = None
    client.current_playback.return_value = None
    assert not (await run(client, "spotify.volume", step="up")).ok
    client.volume.assert_not_called()


async def test_library_retries_soon_after_a_failed_source(client, monkeypatch):
    # 2026-11-06 : playlists en delai depasse au demarrage -> aucune playlist pendant une heure.
    monkeypatch.setattr("drvocal.actions_spotify.LIBRARY_RETRY", -1)
    client.current_user_playlists.side_effect = [TimeoutError("read timed out"), {"items": []}]
    cat = Catalogue()
    register_spotify(cat, client, launch=None, preload=False)
    await cat.run(Intent("spotify.play", {"query": "a"}))
    await cat.run(Intent("spotify.play", {"query": "b"}))
    assert client.current_user_playlists.call_count == 2


async def test_library_keeps_the_hourly_reload_when_everything_loaded(client, monkeypatch):
    monkeypatch.setattr("drvocal.actions_spotify.LIBRARY_RETRY", -1)
    cat = Catalogue()
    register_spotify(cat, client, launch=None, preload=False)
    await cat.run(Intent("spotify.play", {"query": "a"}))
    await cat.run(Intent("spotify.play", {"query": "b"}))
    client.current_user_playlists.assert_called_once()


def test_library_retry_delay_doubles_while_spotify_keeps_failing(monkeypatch):
    from drvocal.actions_spotify import LIBRARY_RETRY, LIBRARY_TTL, Library
    c = MagicMock()
    c.me.return_value = {"id": "me"}
    c.current_user_playlists.side_effect = TimeoutError("read timed out")
    lib = Library(c)
    delays = []
    for _ in range(4):
        lib._loaded_at = None  # force le rechargement suivant
        lib.entries()
        delays.append(lib._ttl)
    assert delays == [LIBRARY_RETRY, LIBRARY_RETRY * 2, LIBRARY_RETRY * 4, LIBRARY_RETRY * 8]
    c.current_user_playlists.side_effect = None
    c.current_user_playlists.return_value = {"items": []}
    lib._loaded_at = None
    lib.entries()
    assert lib._ttl == LIBRARY_TTL  # retour a la normale apres un chargement complet


def test_all_items_stops_on_a_page_that_brings_nothing():
    # Une page vide qui annonce une suite faisait boucler sans fin (et saturer la memoire).
    from drvocal.actions_spotify import _all_items
    c = MagicMock()
    empty = {"items": [], "next": "https://api.spotify.com/next"}
    c.next.return_value = empty
    assert _all_items(c, empty, 1000) == []
    assert c.next.call_count == 0


def test_all_items_caps_the_number_of_pages():
    from drvocal.actions_spotify import MAX_PAGES, _all_items
    c = MagicMock()
    page = {"items": [{"id": 1}], "next": "https://api.spotify.com/next"}
    c.next.return_value = page
    assert len(_all_items(c, page, 10_000)) == MAX_PAGES
