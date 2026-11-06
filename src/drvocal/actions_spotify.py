"""Actions Spotify (Web API, Premium) : lecture, pause, suivant, precedent, volume."""
# spotipy annote ses reponses JSON comme optionnelles alors qu'un echec leve SpotifyException.
# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
import asyncio
import difflib
import logging
import os
import socket
import threading
import time
import unicodedata
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import spotipy
from spotipy import SpotifyException
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyPKCE

from drvocal.actions import Catalogue, Outcome
from drvocal.intent import Intent

log = logging.getLogger(__name__)

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = ("user-read-playback-state user-modify-playback-state "
          "user-follow-read user-top-read playlist-read-private "
          "user-library-read user-read-recently-played")
SEARCH_LIMIT = 10  # maximum autorise par l'API depuis fevrier 2026
LAUNCH_TIMEOUT = 20.0  # s : le temps que l'application ouverte apparaisse dans les appareils
LAUNCH_POLL = 1.0
ARTIST_SIMILARITY = 0.75  # "stromer" -> Stromae, "Daft Pog" -> Daft Punk (transcription approximative)
CONFIRM_TIMEOUT = 3.0  # s : le temps que Spotify passe reellement en lecture apres un 204
CONFIRM_POLL = 0.5
LIBRARY_TTL = 3600.0  # s : duree avant de recharger la bibliotheque
NOT_STARTED = "Spotify n'a pas lancé la lecture, je remets ta musique."
DJ_URI = "spotify:playlist:37i9dQZF1EYkqdzj48dyYq"  # le DJ de Spotify, lance comme une playlist
MAX_PLAYLISTS = 1000
MAX_SAVED_TRACKS = 1000
# Entrees "faibles" (likes, ecoutes recentes) : avec ~3000 noms, 0.6 trouve de faux voisins
# ("d'Ariano" -> Aria au lieu de daryana). Les "fortes" (suivis, top, playlists) gardent 0.6
# et un bonus de classement.
WEAK_SIMILARITY = 0.75
STRONG_BONUS = 0.05
VARIANT_PENALTY = 0.05  # "d'ariano" -> "ariano" est une supposition : moins sure que la requete telle quelle
TRACK_SIMILARITY = 0.75  # titres : bien plus nombreux, un titre court ("Pink") ne doit pas capter "deft pink"
LIBRARY_SIMILARITY = 0.6  # "d'Ariano" -> daryana : seuil bas, la bibliotheque est un petit ensemble connu
LIBRARY_EXACT = 0.9  # au-dessus, la bibliotheque passe avant la recherche


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


def launch_spotify_app() -> None:
    """Ouvre l'application Spotify de ce PC (protocole spotify:, installe par l'application)."""
    os.startfile("spotify:")


def _find_computer(client: spotipy.Spotify) -> str | None:
    devices = client.devices().get("devices", [])
    host = socket.gethostname().casefold()
    computers = [d for d in devices if d.get("type") == "Computer"]
    for d in computers:
        if d.get("name", "").casefold() == host:
            return d["id"]
    return computers[0]["id"] if computers else None


def _local_device_id(client: spotipy.Spotify, launch: Callable[[], None] | None) -> str:
    """Appareil de ce PC ; sans lui, ouvre l'application et attend qu'elle apparaisse."""
    if device := _find_computer(client):
        return device
    if launch is None:
        raise NoDevice
    try:
        launch()
    except OSError:
        log.exception("Impossible d'ouvrir l'application Spotify")
        raise NoDevice from None
    deadline = time.monotonic() + LAUNCH_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(LAUNCH_POLL)
        if device := _find_computer(client):
            return device
    raise NoDevice


def _with_device_fallback(client: spotipy.Spotify, call: Callable[..., object], *args,
                          launch: Callable[[], None] | None = None, **kwargs) -> None:
    """Appelle l'API ; sans appareil actif (404), recommence sur l'appareil local."""
    try:
        call(*args, **kwargs)
    except SpotifyException as e:
        if e.http_status != 404:
            raise
        call(*args, device_id=_local_device_id(client, launch), **kwargs)


def _name_matches(items: list[dict | None], query: str) -> dict | None:
    top = next((i for i in items if i), None)
    if top and top.get("name", "").casefold() == query.casefold():
        return top
    return None


# Cyrillique -> lettres latines a la francaise : "Дискотека" dit a voix haute est transcrit
# "Disco tier 4" par Whisper, la comparaison doit se faire en lettres latines.
_CYRILLIC = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "j", "з": "z",
    "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "ou", "ф": "f", "х": "h", "ц": "ts", "ч": "tch", "ш": "ch", "щ": "ch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "iou", "я": "ia",
})


@lru_cache(maxsize=32768)  # les noms de la bibliotheque sont compares a chaque commande
def _letters(text: str) -> str:
    latin = unicodedata.normalize("NFD", text.casefold().translate(_CYRILLIC))
    return "".join(c for c in latin if c.isalnum())


def _close_artist(artists: list[dict | None], query: str) -> dict | None:
    """Artiste au nom proche de la requete, parmi les premiers resultats."""
    target = _letters(query)
    for artist in (a for a in artists[:3] if a):
        if difflib.SequenceMatcher(None, _letters(artist.get("name", "")), target).ratio() >= ARTIST_SIMILARITY:
            return artist
    return None


def _playback(client: spotipy.Spotify) -> dict:
    """Etat du lecteur ; aucun lecteur ou erreur API = etat vide."""
    try:
        return client.current_playback() or {}
    except SpotifyException:
        return {}


def _item_uri(state: dict) -> str | None:
    return (state.get("item") or {}).get("uri")


def _plays_requested(state: dict, play_kwargs: dict, before: str | None = None) -> bool:
    """En lecture, et sur ce qui a ete demande (sinon l'ancien morceau passerait pour un succes).

    Pour un artiste, Spotify ne rapporte aucun contexte : on regarde les artistes du titre.
    Sans contexte rapporte, un titre different de `before` (celui d'avant) suffit.
    """
    if not state.get("is_playing"):
        return False
    item = state.get("item") or {}
    if uri := play_kwargs.get("context_uri"):
        context = (state.get("context") or {}).get("uri")
        if context == uri or uri in {a.get("uri") for a in item.get("artists") or []}:
            return True
        return context is None and item.get("uri") is not None and item.get("uri") != before
    if uris := play_kwargs.get("uris"):
        return item.get("uri") in uris or (item.get("linked_from") or {}).get("uri") in uris
    return True


def _confirm_playing(client: spotipy.Spotify, play_kwargs: dict, before: str | None = None) -> bool:
    """Attend que Spotify lise ce qui a ete demande (un 204 sur play ne garantit rien)."""
    deadline = time.monotonic() + CONFIRM_TIMEOUT
    while True:
        state = _playback(client)
        if _plays_requested(state, play_kwargs, before):
            return True
        if time.monotonic() >= deadline:
            log.warning("Spotify ne lit pas la demande apres start_playback (is_playing=%s, appareil=%s)",
                        bool(state.get("is_playing")), (state.get("device") or {}).get("name", "?"))
            return False
        time.sleep(CONFIRM_POLL)


def _restore(client: spotipy.Spotify, state: dict) -> None:
    """Remet ce qui jouait avant un echec (meme titre, meme position) : un echec ne coupe pas la musique."""
    item, context = _item_uri(state), state.get("context") or {}
    if not state.get("is_playing") or not item:
        return
    position = state.get("progress_ms") or 0
    try:
        if context.get("uri") and context.get("type") in ("playlist", "album"):
            client.start_playback(context_uri=context["uri"], offset={"uri": item}, position_ms=position)
        else:
            client.start_playback(uris=[item], position_ms=position)
    except Exception as e:
        log.warning("Impossible de remettre la musique precedente (%s)", e)


def _start(client: spotipy.Spotify, launch: Callable[[], None] | None, **play_kwargs) -> bool:
    """Lance la lecture, verifie qu'elle demarre, sinon retente une fois sur l'appareil local.

    En cas d'echec final, la musique d'avant est remise.
    """
    previous = _playback(client)
    before = _item_uri(previous)
    _with_device_fallback(client, client.start_playback, launch=launch, **play_kwargs)
    if _confirm_playing(client, play_kwargs, before):
        return True
    client.start_playback(device_id=_local_device_id(client, launch), **play_kwargs)
    if _confirm_playing(client, play_kwargs, before):
        return True
    _restore(client, previous)
    return False


class Library:
    """Artistes, playlists et titres de l'utilisateur (suivis, likes, ecoutes), charges une seule fois par heure."""

    def __init__(self, client: spotipy.Spotify):
        self._client = client
        self._entries: list[tuple[str, str]] = []
        self.strong: frozenset[str] = frozenset()  # uri des sources fortes (suivis, top, playlists)
        self._loaded_at: float | None = None
        self._lock = threading.Lock()

    def entries(self) -> list[tuple[str, str]]:
        with self._lock:  # prechargement et premiere commande peuvent se croiser : un seul chargement
            now = time.monotonic()
            if self._loaded_at is None or now - self._loaded_at > LIBRARY_TTL:
                self._entries = self._load()
                self._loaded_at = now
            return self._entries

    def preload(self) -> None:
        self.entries()

    def vocabulary(self, limit: int = 40) -> list[str]:
        """Noms d'artistes et de playlists forts, sans jamais charger ni attendre le reseau (playlists d'abord)."""
        entries, strong = self._entries, self.strong
        playlists = [n for n, uri in entries if uri in strong and uri.startswith("spotify:playlist:")]
        artists = [n for n, uri in entries if uri in strong and uri.startswith("spotify:artist:")]
        return (playlists + artists)[:limit]

    def _load(self) -> list[tuple[str, str]]:
        c = self._client
        sources = [
            # (libelle, appel, titres enveloppes ?, source forte ?)
            ("artistes suivis", lambda: c.current_user_followed_artists(limit=50)["artists"]["items"], False, True),
            ("top artistes (moyen terme)", lambda: c.current_user_top_artists(limit=50, time_range="medium_term")["items"], False, True),
            ("top artistes (court terme)", lambda: c.current_user_top_artists(limit=50, time_range="short_term")["items"], False, True),
            ("playlists", lambda: _all_items(c, c.current_user_playlists(limit=50), MAX_PLAYLISTS), False, True),
            ("titres likes", lambda: _all_items(c, c.current_user_saved_tracks(limit=50), MAX_SAVED_TRACKS), True, False),
            ("ecoutes recentes", lambda: c.current_user_recently_played(limit=50)["items"], True, False),
            ("top titres (moyen terme)", lambda: c.current_user_top_tracks(limit=50, time_range="medium_term")["items"], True, True),
            ("top titres (court terme)", lambda: c.current_user_top_tracks(limit=50, time_range="short_term")["items"], True, True),
        ]
        found: dict[tuple[str, str], str] = {}  # (nom normalise, uri) -> nom
        strong: set[str] = set()

        def add(name: str, uri: str, is_strong: bool) -> None:
            found.setdefault((_letters(name), uri), name)
            if is_strong:
                strong.add(uri)

        for label, fetch, tracks, is_strong in sources:
            try:
                items = fetch()
            except Exception as e:  # scope manquant (403), reseau... la lecture ne doit pas en pâtir
                log.warning("Bibliotheque Spotify : %s indisponibles (%s)", label, e)
                continue
            for item in items or []:
                if tracks:  # les likes et ecoutes recentes enveloppent le titre dans "track"
                    item = (item or {}).get("track", item)
                if not item or item.get("is_local") or not item.get("uri") or not item.get("name"):
                    continue
                add(item["name"], item["uri"], is_strong)
                if tracks:
                    artists = [a for a in item.get("artists") or [] if a and a.get("uri") and a.get("name")]
                    if artists:  # l'utilisateur dit souvent "artiste titre"
                        add(f"{artists[0]['name']} {item['name']}", item["uri"], is_strong)
                    for a in artists:  # artistes ecoutes sans etre suivis
                        add(a["name"], a["uri"], is_strong)
        self.strong = frozenset(strong)
        return [(name, uri) for (_, uri), name in found.items()]


def _all_items(client: spotipy.Spotify, page: dict | None, limit: int) -> list:
    """Items de toutes les pages d'un resultat pagine (champ `next`), au plus `limit`."""
    items: list = []
    while page:
        items += page.get("items") or []
        if len(items) >= limit or not page.get("next"):
            break
        page = client.next(page)
    return items[:limit]


def _query_variants(query: str) -> list[str]:
    """La requete et ses deformations courantes : "d'ariano" -> "ariano", "dariano"."""
    variants = [query]
    folded = query.strip().casefold()
    for prefix in ("d'", "d’"):
        if folded.startswith(prefix):
            variants.append(folded[len(prefix):])
    variants.append(query.replace("'", "").replace("’", ""))
    return variants


def _entry_limit(uri: str, threshold: float, is_strong: bool) -> float:
    """Seuil d'une entree : titres et sources faibles demandent plus de ressemblance."""
    if uri.startswith("spotify:track:"):
        return max(threshold, TRACK_SIMILARITY)
    return threshold if is_strong else max(threshold, WEAK_SIMILARITY)


def _library_match(entries: list[tuple[str, str]], query: str, threshold: float = LIBRARY_SIMILARITY,
                   strong: frozenset[str] | None = None) -> str | None:
    """Uri de l'entree de la bibliotheque la plus proche de la requete, si assez proche.

    Chaque entree doit passer son propre seuil (`_entry_limit`) ; au classement, les sources
    fortes recoivent `STRONG_BONUS`. `strong` absent : toutes les entrees comptent comme fortes.
    """
    targets: list[str] = []
    for t in map(_letters, _query_variants(query)):  # la premiere est la requete telle quelle
        if t and t not in targets:
            targets.append(t)
    matchers = []
    for i, t in enumerate(targets):
        m = difflib.SequenceMatcher()
        m.set_seq2(t)  # seq2 est mis en cache par difflib : on ne change que seq1
        matchers.append((m, VARIANT_PENALTY if i else 0.0))
    best, best_uri = 0.0, None
    for name, uri in entries:
        is_strong = strong is None or uri in strong
        bonus = STRONG_BONUS if is_strong and strong is not None else 0.0
        limit = _entry_limit(uri, threshold, is_strong)
        floor = max(best - bonus, limit) - 1e-9  # en dessous, inutile de calculer le ratio exact
        letters = _letters(name)
        ratio = 0.0
        for m, penalty in matchers:
            m.set_seq1(letters)
            if m.real_quick_ratio() - penalty > floor and m.quick_ratio() - penalty > floor:
                ratio = max(ratio, m.ratio() - penalty)
        if ratio >= limit and ratio + bonus > best:
            best, best_uri = ratio + bonus, uri
    return best_uri


def _play_uri(start: Callable[..., Outcome], uri: str) -> Outcome:
    """Un titre se lit par `uris`, le reste (artiste, playlist, album) par `context_uri`."""
    return start(uris=[uri]) if uri.startswith("spotify:track:") else start(context_uri=uri)


def _play_playlist(client: spotipy.Spotify, query: str, start: Callable[..., Outcome],
                   library: Library | None) -> Outcome:
    """ "ma playlist X" : d'abord les playlists de l'utilisateur, puis le catalogue."""
    mine = [(n, u) for n, u in (library.entries() if library else []) if u.startswith("spotify:playlist:")]
    if uri := _library_match(mine, query, strong=library.strong if library else None):
        return start(context_uri=uri)
    res = client.search(q=query, type="playlist", limit=SEARCH_LIMIT)
    found = [p for p in ((res.get("playlists") or {}).get("items") or []) if p]
    if not found:
        return Outcome(False, "Je n'ai pas trouvé cette playlist.")
    hit = _name_matches(found, query) or found[0]
    return start(context_uri=hit["uri"])


def _play_query(client: spotipy.Spotify, query: str, launch: Callable[[], None] | None,
                library: Library | None = None, kind: str | None = None) -> Outcome:
    def start(**play_kwargs) -> Outcome:
        return Outcome(True) if _start(client, launch, **play_kwargs) else Outcome(False, NOT_STARTED)

    if kind == "playlist":
        return _play_playlist(client, query, start, library)

    # Ordre : nom quasi exact de la bibliotheque, nom exact du catalogue, puis seulement
    # nom approximatif de la bibliotheque (sinon un nom bien transcrit serait detourne).
    entries = library.entries() if library else []
    strong = library.strong if library else None
    if uri := _library_match(entries, query, LIBRARY_EXACT, strong):
        return _play_uri(start, uri)
    res = client.search(q=query, type="track,artist,album,playlist", limit=SEARCH_LIMIT)
    items = {k: (res.get(k) or {}).get("items") or [] for k in ("tracks", "artists", "albums", "playlists")}
    for kind in ("artists", "albums", "playlists"):
        if hit := _name_matches(items[kind], query):
            return start(context_uri=hit["uri"])
    if uri := _library_match(entries, query, strong=strong):
        return _play_uri(start, uri)
    if hit := _close_artist(items["artists"], query):
        return start(context_uri=hit["uri"])
    track = next((t for t in items["tracks"] if t), None)
    if track is None:
        return Outcome(False, "Je n'ai rien trouvé sur Spotify.")
    return start(uris=[track["uri"]])


def register_spotify(catalogue: Catalogue, client: spotipy.Spotify,
                     launch: Callable[[], None] | None = launch_spotify_app, preload: bool = True) -> Library:
    """`launch` ouvre l'application quand aucun appareil n'est la (lancer une musique seulement).

    `preload` charge la bibliotheque en arriere-plan pour que la premiere commande n'attende pas.
    """
    library = Library(client)
    if preload:
        threading.Thread(target=library.preload, daemon=True, name="spotify-library").start()

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
        return _play_query(client, intent.args["query"], launch, library, intent.args.get("kind"))

    def volume(intent: Intent) -> Outcome:
        level = intent.args.get("level", "")
        if not level.isdecimal():
            return Outcome(False, "Je n'ai pas compris le volume.")
        _with_device_fallback(client, client.volume, min(int(level), 100))
        return Outcome(True)

    action("spotify.play", play)
    action("spotify.pause", simple(client.pause_playback))
    def resume(_: Intent) -> Outcome:
        if _start(client, launch):
            return Outcome(True)
        return Outcome(False, NOT_STARTED)

    action("spotify.resume", resume)

    def dj(_: Intent) -> Outcome:
        return Outcome(True) if _start(client, launch, context_uri=DJ_URI) else Outcome(False, NOT_STARTED)

    action("spotify.dj", dj)
    action("spotify.next", simple(client.next_track))
    action("spotify.previous", simple(client.previous_track))
    action("spotify.volume", volume)
    return library
