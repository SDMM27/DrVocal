from unittest.mock import MagicMock

import pytest
from spotipy import SpotifyException

from drvocal.actions import Catalogue
from drvocal.actions_spotify import register_spotify
from drvocal.intent import Intent
from drvocal.secrets_store import SecretStore

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
        "user-library-read", "user-read-recently-played"}
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


async def test_unknown_playlist_falls_back_to_catalogue_playlists(client):
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
    lib.strong = frozenset({"spotify:artist:1", "spotify:playlist:1", "spotify:track:1", "spotify:artist:3"})
    assert lib.vocabulary() == ["Mix", "Zaz", "Autre"]
    assert lib.vocabulary(limit=2) == ["Mix", "Zaz"]
    client.current_user_followed_artists.assert_not_called()
