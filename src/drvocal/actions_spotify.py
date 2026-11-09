"""Actions Spotify (Web API, Premium) : lecture, pause, suivant, precedent, volume, likes et playlists."""
# spotipy annote ses reponses JSON comme optionnelles alors qu'un echec leve SpotifyException.
# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
import asyncio
import difflib
import json
import logging
import os
import socket
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import spotipy
from spotipy import SpotifyException
from spotipy.cache_handler import CacheHandler
from spotipy.oauth2 import SpotifyPKCE

from drvocal.actions import Catalogue, Outcome
from drvocal.intent import Intent
from drvocal.spotify_aliases import Aliases

log = logging.getLogger(__name__)

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = ("user-read-playback-state user-modify-playback-state "
          "user-follow-read user-top-read playlist-read-private "
          "user-library-read user-read-recently-played "
          "user-library-modify playlist-modify-private playlist-modify-public")
SEARCH_LIMIT = 10  # maximum autorise par l'API depuis fevrier 2026
LAUNCH_TIMEOUT = 20.0  # s : le temps que l'application ouverte apparaisse dans les appareils
LAUNCH_POLL = 1.0
ARTIST_SIMILARITY = 0.75  # "stromer" -> Stromae, "Daft Pog" -> Daft Punk (transcription approximative)
CONFIRM_TIMEOUT = 3.0  # s : le temps que Spotify passe reellement en lecture apres un 204
CONFIRM_POLL = 0.5
LIBRARY_TTL = 3600.0  # s : duree avant de recharger la bibliotheque
LIBRARY_RETRY = 30.0  # s : rechargement anticipe si une source a echoue (delai depasse, 429...),
# double a chaque echec consecutif (jusqu'a LIBRARY_TTL) pour ne pas aggraver une limitation de debit.
NOT_STARTED = "Spotify n'a pas lancé la lecture, je remets ta musique."
DJ_URI = "spotify:playlist:37i9dQZF1EYkqdzj48dyYq"  # le DJ de Spotify, lance comme une playlist
UNDO_WINDOW = 120.0  # s : delai pendant lequel la derniere ecriture (like, ajout) peut etre annulee
NO_TRACK = "Aucun titre en cours."
REAUTH = "Spotify refuse : réautorise Dr Vocal avec tools/spotify_login.py."
MAX_PLAYLISTS = 1000
MAX_SAVED_TRACKS = 1000
MAX_PAGES = 40  # garde-fou de pagination : 40 pages de 50 couvrent largement les maximums ci-dessus
# Entrees "faibles" (likes, ecoutes recentes) : avec ~3000 noms, 0.6 trouve de faux voisins
# ("d'Ariano" -> Aria au lieu de daryana). Les "fortes" (suivis, top, playlists) gardent 0.6
# et un bonus de classement.
WEAK_SIMILARITY = 0.75
STRONG_BONUS = 0.05
VARIANT_PENALTY = 0.05  # "d'ariano" -> "ariano" est une supposition : moins sure que la requete telle quelle
TRACK_SIMILARITY = 0.75  # titres : bien plus nombreux, un titre court ("Pink") ne doit pas capter "deft pink"
LIBRARY_SIMILARITY = 0.6  # "d'Ariano" -> daryana : seuil bas, la bibliotheque est un petit ensemble connu
VOLUME_STEP = 15  # "monte le volume" / "baisse le volume", en points de pourcentage
LIBRARY_EXACT = 0.9  # au-dessus, la bibliotheque passe avant la recherche


class NoDevice(Exception):
    pass


class SecretStoreCacheHandler(CacheHandler):
    """Jeton spotipy garde chiffre dans le SecretStore (nom `spotify_token`), jamais dans un fichier clair."""

    def __init__(self, store):
        self.store = store

    def get_cached_token(self) -> dict | None:
        raw = self.store.get("spotify_token")
        if not raw:
            return None
        try:
            token = json.loads(raw)
        except ValueError:
            log.warning("jeton Spotify illisible, nouvelle autorisation necessaire")
            return None
        return token if isinstance(token, dict) else None

    def save_token_to_cache(self, token_info: dict) -> None:
        try:
            self.store.set("spotify_token", json.dumps(token_info))
        except OSError as exc:
            log.warning("jeton Spotify non enregistre (%s)", type(exc).__name__)


def build_client(client_id: str, cache_handler: CacheHandler) -> spotipy.Spotify:
    """Client PKCE ; le jeton est garde par `cache_handler` (SecretStoreCacheHandler en production)."""
    auth = SpotifyPKCE(
        client_id=client_id,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        cache_handler=cache_handler,
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

    def __init__(self, client: spotipy.Spotify, aliases: Aliases | None = None):
        self._client = client
        self._aliases = aliases
        self._entries: list[tuple[str, str]] = []
        self._loaded_strong: frozenset[str] = frozenset()
        self._loaded_at: float | None = None
        self._ttl = LIBRARY_TTL
        self._load_failed = False
        self._failures = 0
        self._editable: frozenset[str] = frozenset()
        self._me_id: str | None = None
        self._lock = threading.Lock()

    def entries(self) -> list[tuple[str, str]]:
        with self._lock:  # prechargement et premiere commande peuvent se croiser : un seul chargement
            now = time.monotonic()
            if self._loaded_at is None or now - self._loaded_at > self._ttl:
                self._load_failed = False
                self._entries = self._load()
                self._loaded_at = now
                # Un echec partiel (ex. playlists en delai depasse) ne doit pas durer une heure.
                self._failures = self._failures + 1 if self._load_failed else 0
                self._ttl = min(LIBRARY_RETRY * 2 ** (self._failures - 1), LIBRARY_TTL) if self._failures else LIBRARY_TTL
            return self._with_aliases(self._entries)

    @property
    def strong(self) -> frozenset[str]:
        """Uri des sources fortes (suivis, top, playlists) et des alias appris a la voix."""
        return self._loaded_strong | {uri for _, uri in self._alias_items()}

    def editable_playlists(self) -> list[tuple[str, str]]:
        """(nom, uri) des playlists ou l'on peut ajouter : les siennes et les collaboratives. Sans alias."""
        self.entries()
        return [(n, u) for n, u in self._entries if u in self._editable]

    def _current_user_id(self) -> str | None:
        if self._me_id is None:
            try:
                self._me_id = self._client.me()["id"]
            except Exception as e:  # sans identifiant, aucune playlist n'est modifiable
                log.warning("Bibliotheque Spotify : profil indisponible (%s)", type(e).__name__)
        return self._me_id

    def _alias_items(self) -> list[tuple[str, str]]:
        return self._aliases.items() if self._aliases else []

    def _with_aliases(self, entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
        # lus a chaque appel : un alias qui vient d'etre appris sert tout de suite, sans rechargement
        return entries + self._alias_items()

    def preload(self) -> None:
        self.entries()

    def vocabulary(self, limit: int = 40) -> list[str]:
        """Noms d'artistes et de playlists forts, sans jamais charger ni attendre le reseau (playlists d'abord)."""
        entries, strong = self._with_aliases(self._entries), self.strong
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
        editable: set[str] = set()
        me_id = self._current_user_id()
        if me_id is None:
            self._load_failed = True

        def add(name: str, uri: str, is_strong: bool) -> None:
            found.setdefault((_letters(name), uri), name)
            if is_strong:
                strong.add(uri)

        for label, fetch, tracks, is_strong in sources:
            try:
                items = fetch()
            except Exception as e:  # scope manquant (403), reseau... la lecture ne doit pas en pâtir
                log.warning("Bibliotheque Spotify : %s indisponibles (%s)", label, e)
                self._load_failed = True
                continue
            for item in items or []:
                if tracks:  # les likes et ecoutes recentes enveloppent le titre dans "track"
                    item = (item or {}).get("track", item)
                if not item or item.get("is_local") or not item.get("uri") or not item.get("name"):
                    continue
                add(item["name"], item["uri"], is_strong)
                if label == "playlists" and (
                        item.get("collaborative") or (me_id and (item.get("owner") or {}).get("id") == me_id)):
                    editable.add(item["uri"])
                if tracks:
                    artists = [a for a in item.get("artists") or [] if a and a.get("uri") and a.get("name")]
                    if artists:  # l'utilisateur dit souvent "artiste titre"
                        add(f"{artists[0]['name']} {item['name']}", item["uri"], is_strong)
                    for a in artists:  # artistes ecoutes sans etre suivis
                        add(a["name"], a["uri"], is_strong)
        self._loaded_strong = frozenset(strong)
        self._editable = frozenset(editable)
        return [(name, uri) for (_, uri), name in found.items()]


def _all_items(client: spotipy.Spotify, page: dict | None, limit: int) -> list:
    """Items de toutes les pages d'un resultat pagine (champ `next`), au plus `limit`.

    S'arrete aussi sur une page qui n'apporte rien et apres MAX_PAGES pages : une reponse
    anormale (page vide qui annonce une suite) ne doit jamais faire tourner la boucle sans fin.
    """
    items: list = []
    pages = 0
    while page and pages < MAX_PAGES:
        pages += 1
        before = len(items)
        items += page.get("items") or []
        if len(items) == before or len(items) >= limit or not page.get("next"):
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


def _close_name(items: list[dict | None], query: str) -> dict | None:
    """Element au nom proche de la requete (meilleure ressemblance, seuil ARTIST_SIMILARITY)."""
    target = _letters(query)
    best, best_ratio = None, ARTIST_SIMILARITY
    for item in (i for i in items if i):
        ratio = difflib.SequenceMatcher(None, _letters(item.get("name", "")), target).ratio()
        if ratio >= best_ratio:
            best, best_ratio = item, ratio
    return best


def _play_playlist(client: spotipy.Spotify, query: str, start: Callable[..., Outcome],
                   library: Library | None, mine: bool = False) -> Outcome:
    """ "ma playlist X" : bibliotheque et alias seulement ; "la playlist X" : puis le catalogue, si le nom est proche."""
    own = [(n, u) for n, u in (library.entries() if library else []) if u.startswith("spotify:playlist:")]
    if uri := _library_match(own, query, strong=library.strong if library else None):
        return start(context_uri=uri)
    if mine:  # jamais la playlist d'un inconnu pour "ma playlist"
        return Outcome(False, "Je ne trouve pas cette playlist dans ta bibliothèque. "
                              "Lance-la puis dis : retiens cette playlist sous le nom …")
    res = client.search(q=query, type="playlist", limit=SEARCH_LIMIT)
    found = [p for p in ((res.get("playlists") or {}).get("items") or []) if p]
    hit = _name_matches(found, query) or _close_name(found, query)
    if hit is None:
        return Outcome(False, "Je n'ai pas trouvé cette playlist.")
    return start(context_uri=hit["uri"])


def _play_query(client: spotipy.Spotify, query: str, launch: Callable[[], None] | None,
                library: Library | None = None, kind: str | None = None, mine: bool = False) -> Outcome:
    def start(**play_kwargs) -> Outcome:
        return Outcome(True) if _start(client, launch, **play_kwargs) else Outcome(False, NOT_STARTED)

    if kind == "playlist":
        return _play_playlist(client, query, start, library, mine)

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


@dataclass(frozen=True)
class _Write:
    """Derniere ecriture dans la bibliotheque, de quoi l'annuler."""
    kind: str  # "like" ou "playlist"
    uri: str
    at: float
    playlist_id: str = ""
    snapshot_id: str | None = None


def _refusal(e: SpotifyException, endpoint: str, what: str) -> Outcome | None:
    """403 -> message dit (journal : endpoint et statut, jamais le jeton) ; autre erreur : None."""
    if e.http_status != 403:
        return None
    log.warning("Spotify refuse l'ecriture : %s (statut %s)", endpoint, e.http_status)
    text = str(e).casefold()
    if "scope" in text or "insufficient" in text:
        return Outcome(False, REAUTH)
    return Outcome(False, what)


def register_spotify(catalogue: Catalogue, client: spotipy.Spotify,
                     launch: Callable[[], None] | None = launch_spotify_app, preload: bool = True,
                     aliases: Aliases | None = None) -> Library:
    """`launch` ouvre l'application quand aucun appareil n'est la (lancer une musique seulement).

    `preload` charge la bibliotheque en arriere-plan pour que la premiere commande n'attende pas.
    `aliases` : noms appris a la voix ("retiens cette playlist sous le nom ..."), entrees fortes de la bibliotheque.
    """
    library = Library(client, aliases)
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
        return _play_query(client, intent.args["query"], launch, library, intent.args.get("kind"), "mine" in intent.args)

    def remember(intent: Intent) -> Outcome:
        assert aliases is not None  # enregistree seulement avec des alias
        state = _playback(client)
        uri = (state.get("context") or {}).get("uri") or _item_uri(state)
        if not uri:
            return Outcome(False, "Rien ne joue sur Spotify.")
        name = intent.args["name"]
        aliases.add(name, uri)
        return Outcome(True, f"C'est noté : {name}.")

    last_write: list[_Write] = []  # zero ou une ecriture annulable
    write_lock = threading.Lock()

    def current_track() -> tuple[str, str] | None:
        item = _playback(client).get("item") or {}
        uri = item.get("uri") or ""
        return (uri, item.get("name") or "ce titre") if uri.startswith("spotify:track:") else None

    def like(_: Intent) -> Outcome:
        if (track := current_track()) is None:
            return Outcome(False, NO_TRACK)
        uri, name = track
        try:
            client._put("me/library", uris=uri)  # fevrier 2026 : /me/tracks est remplace par /me/library
        except SpotifyException as e:
            if out := _refusal(e, "PUT me/library", "Spotify refuse de modifier tes titres likés."):
                return out
            raise
        with write_lock:
            last_write[:] = [_Write("like", uri, time.monotonic())]
        return Outcome(True, f"Ajouté à tes titres likés : {name}.")

    def add_to_playlist(intent: Intent) -> Outcome:
        if (track := current_track()) is None:
            return Outcome(False, NO_TRACK)
        uri = track[0]
        names = {u: n for n, u in library.editable_playlists()}
        playlist = _library_match([(n, u) for u, n in names.items()], intent.args.get("playlist", ""))
        if playlist is None:
            return Outcome(False, "Je ne trouve pas cette playlist parmi les tiennes.")
        playlist_id = playlist.rsplit(":", 1)[-1]
        try:
            # fevrier 2026 : /playlists/{id}/tracks est remplace par /playlists/{id}/items
            res = client._post(f"playlists/{playlist_id}/items", payload={"uris": [uri]})
        except SpotifyException as e:
            if out := _refusal(e, "POST playlists/items", "Spotify refuse de modifier cette playlist."):
                return out
            raise
        snapshot = res.get("snapshot_id") if isinstance(res, dict) else None
        with write_lock:
            last_write[:] = [_Write("playlist", uri, time.monotonic(), playlist_id, snapshot)]
        return Outcome(True, f"Ajouté à {names[playlist]}.")

    def undo(_: Intent) -> Outcome:
        with write_lock:
            write = last_write[0] if last_write else None
            if write is None or time.monotonic() - write.at > UNDO_WINDOW:
                last_write.clear()
                return Outcome(False, "Rien à annuler.")
        endpoint = "me/library" if write.kind == "like" else "playlists/items"
        try:
            if write.kind == "like":
                client._delete("me/library", uris=write.uri)
            else:
                body: dict = {"items": [{"uri": write.uri}]}
                if write.snapshot_id:
                    body["snapshot_id"] = write.snapshot_id
                client._delete(f"playlists/{write.playlist_id}/items", payload=body)
        except SpotifyException as e:
            if out := _refusal(e, f"DELETE {endpoint}", "Spotify refuse d'annuler cet ajout."):
                return out
            raise
        with write_lock:
            if last_write and last_write[0] is write:
                last_write.clear()
        return Outcome(True, "Annulé.")

    def volume(intent: Intent) -> Outcome:
        step = intent.args.get("step")
        if step in ("up", "down"):  # relatif : depuis le volume actuel de l'appareil
            device = (client.current_playback() or {}).get("device") or {}
            current = device.get("volume_percent")
            if not isinstance(current, int):
                return Outcome(False, "Je ne connais pas le volume actuel.")
            target = current + VOLUME_STEP if step == "up" else current - VOLUME_STEP
            _with_device_fallback(client, client.volume, max(0, min(target, 100)))
            return Outcome(True)
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
    if aliases is not None:
        action("spotify.remember", remember)
    action("spotify.like", like)
    action("spotify.add_to_playlist", add_to_playlist)
    action("spotify.undo", undo)
    action("spotify.next", simple(client.next_track))
    action("spotify.previous", simple(client.previous_track))
    action("spotify.volume", volume)
    return library
