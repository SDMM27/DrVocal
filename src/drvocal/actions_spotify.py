"""Actions Spotify (Web API, Premium) : lecture, pause, suivant, precedent, volume."""
import asyncio
import logging
import socket
from collections.abc import Callable
from pathlib import Path

import spotipy
from spotipy import SpotifyException
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyPKCE

from drvocal.actions import Catalogue, Outcome
from drvocal.intent import Intent

log = logging.getLogger(__name__)

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "user-read-playback-state user-modify-playback-state"
SEARCH_LIMIT = 10  # maximum autorise par l'API depuis fevrier 2026


class NoDevice(Exception):
    pass


def build_client(client_id: str, cache_path: Path) -> spotipy.Spotify:
    """Client PKCE ; le jeton est garde dans `cache_path` (a placer hors du depot)."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    auth = SpotifyPKCE(
        client_id=client_id,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        cache_handler=CacheFileHandler(cache_path=str(cache_path)),
    )
    return spotipy.Spotify(auth_manager=auth)


def _local_device_id(client: spotipy.Spotify) -> str:
    devices = client.devices().get("devices", [])
    host = socket.gethostname().casefold()
    computers = [d for d in devices if d.get("type") == "Computer"]
    for d in computers:
        if d.get("name", "").casefold() == host:
            return d["id"]
    if computers:
        return computers[0]["id"]
    raise NoDevice


def _with_device_fallback(client: spotipy.Spotify, call: Callable[..., object], *args, **kwargs) -> None:
    """Appelle l'API ; sans appareil actif (404), recommence sur l'appareil local."""
    try:
        call(*args, **kwargs)
    except SpotifyException as e:
        if e.http_status != 404:
            raise
        call(*args, device_id=_local_device_id(client), **kwargs)


def _name_matches(items: list[dict | None], query: str) -> dict | None:
    top = next((i for i in items if i), None)
    if top and top.get("name", "").casefold() == query.casefold():
        return top
    return None


def _play_query(client: spotipy.Spotify, query: str) -> bool:
    res = client.search(q=query, type="track,artist,album,playlist", limit=SEARCH_LIMIT)
    items = {k: (res.get(k) or {}).get("items") or [] for k in ("tracks", "artists", "albums", "playlists")}
    for kind in ("artists", "albums", "playlists"):
        if hit := _name_matches(items[kind], query):
            _with_device_fallback(client, client.start_playback, context_uri=hit["uri"])
            return True
    track = next((t for t in items["tracks"] if t), None)
    if track is None:
        return False
    _with_device_fallback(client, client.start_playback, uris=[track["uri"]])
    return True


def register_spotify(catalogue: Catalogue, client: spotipy.Spotify) -> None:
    def action(name: str, sync_fn: Callable[[Intent], Outcome]) -> None:
        async def handler(intent: Intent) -> Outcome:
            try:
                return await asyncio.to_thread(sync_fn, intent)
            except NoDevice:
                return Outcome(False, "Spotify n'est pas ouvert sur cet ordinateur.")
            except Exception:
                log.exception("Echec de l'action %s", name)
                return Outcome(False, "Spotify ne répond pas.")
        catalogue.register(name, handler)

    def simple(call: Callable[..., object]) -> Callable[[Intent], Outcome]:
        def run(_: Intent) -> Outcome:
            _with_device_fallback(client, call)
            return Outcome(True)
        return run

    def play(intent: Intent) -> Outcome:
        if _play_query(client, intent.args["query"]):
            return Outcome(True)
        return Outcome(False, "Je n'ai rien trouvé sur Spotify.")

    def volume(intent: Intent) -> Outcome:
        level = intent.args.get("level", "")
        if not level.isdecimal():
            return Outcome(False, "Je n'ai pas compris le volume.")
        _with_device_fallback(client, client.volume, min(int(level), 100))
        return Outcome(True)

    action("spotify.play", play)
    action("spotify.pause", simple(client.pause_playback))
    action("spotify.resume", simple(client.start_playback))
    action("spotify.next", simple(client.next_track))
    action("spotify.previous", simple(client.previous_track))
    action("spotify.volume", volume)
