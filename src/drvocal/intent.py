"""Comprehension : transforme une transcription en Intent via des regles (sans reseau, sans LLM)."""
import re
import unicodedata
from dataclasses import dataclass

from drvocal.config import Settings


@dataclass(frozen=True)
class Intent:
    action: str
    args: dict[str, str]


def _fold(text: str) -> str:
    """Minuscules, sans accents, apostrophes droites ; meme longueur que le texte d'origine."""
    out = []
    for c in text:
        if c in "’‘ʼ`":
            out.append("'")
            continue
        low = c.lower()
        c = low if len(low) == 1 else c
        out.append(unicodedata.normalize("NFD", c)[0])
    return "".join(out)


def _rx(pattern: str) -> re.Pattern[str]:
    # ' ' = espaces ; '~' = espace ou trait d'union (mets-moi / mets moi).
    return re.compile(pattern.replace(" ", r"\s+").replace("~", r"[-\s]+"))


_DE = r"(?:(?:de|que)\s+|d'|qu')?"

# Ordre significatif : les regles specifiques passent avant "mets <query>".
_SIMPLE_RULES = [
    ("discord.deafen_self", _rx(r"^(?:mets~moi en sourdine|mets~moi sourd)$")),
    ("discord.mute_self", _rx(r"^(?:(?:coupe|mute|desactive) (?:mon|le) micro|(?:coupe|mute)~moi)$")),
    ("spotify.pause", _rx(r"^(?:pause|mets (?:la musique )?en pause|arrete la musique)$")),
    # DJ de Spotify ; "di-jay", "didjay" : transcriptions possibles de "DJ".
    ("spotify.dj", _rx(r"^(?:je )?(?:(?:lance|mets|joue|demarre|active|ouvre) )?(?:le |mon )?(?:dj|di~jay|didjay)"
                       r"(?: (?:sur|de|dans) spotify)?$")),
    ("spotify.resume", _rx(r"^(?:(?:reprends|reprend|relance) (?:la )?(?:musique|lecture)"
                           r"|(?:je )?(?:mets|lance|joue) (?:de la |la )?musique(?: sur spotify)?)$")),
    ("spotify.next", _rx(r"^(?:musique suivante|chanson suivante|morceau suivant|suivant|passe la (?:musique|chanson))$")),
    ("spotify.previous", _rx(r"^(?:musique precedente|chanson precedente|morceau precedent|precedent)$")),
    ("spotify.undo", _rx(r"^(?:(?:annule|annuler)(?: ca| cela| le dernier(?: ajout| like)?)?|retire~(?:le|la|ca))$")),
    ("notes.start", _rx(r"^(?:prends|prend|fais|ecris) une note$")),
    ("journal.open", _rx(r"^(?:ouvre|ouvrir|montre|affiche|afficher)(?:~moi)? (?:le )?journal"
                         r"(?: (?:de|du) (?:dr\.?|docteur|doc)~?vocal)?$")),
    ("claude.stop", _rx(r"^(?:arrete|arretes|stop|stoppe|annule|coupe|termine) (?:la |cette )?(?:session )?(?:de )?"
                        r"claude(?: agent)?$")),
]
# "ce titre" et ses variantes ; "ca" seul reste possible ("ajoute ca a ma playlist X").
_THIS = r"(?:ce|le|cet) (?:titre|morceau|son|son-la|truc)|cette (?:chanson|musique|piste)|celui~ci|celle~ci|ca"
_FAVORITES = r"(?:titres? likes?|likes?|favoris?|coups? de coeur)"
_LIKE = _rx(rf"^(?:(?:like|liker)(?: (?:{_THIS}))?"
            rf"|(?:ajoute|ajouter|rajoute|mets|met) (?:(?:{_THIS}) )?(?:(?:a|aux|dans) (?:mes |les |mon )?|en ){_FAVORITES}"
            rf"|j'?aime (?:{_THIS}))$")
_ADD_TO_PLAYLIST = _rx(rf"^(?:ajoute|ajouter|rajoute|mets|met) (?:(?:{_THIS}) )?(?:a|dans|sur) (?:ma|mes|la|une|ta) playlists? (.+)$")
# Tout ordre "ajoute ..." qui n'est pas compris ne doit jamais lancer de musique.
_ADD_VERB = _rx(r"^(?:ajoute|ajouter|rajoute|rajouter)(?:\s|$)")
_VOLUME = _rx(r"^(?:(?:mets|regle|monte|baisse|descends) )?(?:le )?volume (?:a )?(\d{1,3})\s*(?:%|pour\s*cent)?"
              r"(?: (?:sur|de|dans) spotify)?$")
# Volume relatif. "montre le volume" : transcription frequente de "monte le volume".
_VOLUME_UP = _rx(r"^(?:(?:monte|montre|augmente|remonte|hausse) (?:un peu |encore )?(?:le )?(?:son|volume)"
                 r"(?: de la musique)?"
                 r"|(?:mets )?(?:le son |la musique )?(?:un peu |encore )?plus fort(?: le son| la musique)?)"
                 r"(?: (?:sur|de|dans) spotify)?$")
_VOLUME_DOWN = _rx(r"^(?:(?:baisse|diminue|descends|redescends) (?:un peu |encore )?(?:le )?(?:son|volume)"
                   r"(?: de la musique)?"
                   r"|(?:mets )?(?:le son |la musique )?(?:un peu |encore )?moins fort(?: le son| la musique)?)"
                   r"(?: (?:sur|de|dans) spotify)?$")
_MESSAGE = _rx(r"^(?:ecris|envoie) dans (?:le salon )?(.+)$")
_MOVE = _rx(r"^(?:va|vas|viens|mets~moi|deplace~moi) (?:dans|sur) (?:le )?(?:salon )?(.+)$")
_MUTE_MEMBER = _rx(r"^(?:mute|coupe le micro de|rends muet) (.+)$")
_CONTINUE = _rx(rf"^continue avec claude {_DE}(.+)$")
_PLAY = _rx(r"^(?:je )?(?:mets|joue|lance|ouvre|j'ouvre) (.+)$")  # "Je joue..." : Whisper ajoute parfois "Je"
# "ma playlist X" n'importe ou dans une phrase courte : le verbe est souvent mal transcrit
# ("J'ouvre ma playlist...", "Je vous ma playlist...").
_MY_PLAYLIST = _rx(r"(?:^|\s)(?P<det>ma|mes|la) playlists? (?P<q>.+)$")
# "retiens cette playlist sous le nom X" : apprend l'uri de ce qui joue (playlists invisibles a l'API).
_REMEMBER = _rx(r"^(?:retiens|retient|enregistre|memorise|appelle|nomme) "
                r"(?:(?:cette|la) (?:playlist|chanson)|ce (?:morceau|titre)|cet (?:album|artiste))"
                r"(?: qui (?:est jouee|joue|passe|tourne)(?: en ce moment| maintenant)?(?: sur spotify)?)?"
                r"(?: (?:sous le nom de|sous le nom|sous|en tant que|comme))? (.+)$")
_MY_PLAYLIST_MAX_WORDS = 10
_DJ_LAST = re.compile(r"(?:^|[\s'])dj$")
# "mets" mal transcrit par Whisper : "mais daft punk", "Medaft Punk" (colle au mot suivant).
# Seulement pour un ordre court, et apres toutes les autres regles.
_MISHEARD_MAX_WORDS = 4
_PLAY_MISHEARD = _rx(r"^(?:mais|mai|may|mes|met|me) (.+)$")
# Forme collee : au moins deux mots, sinon de vrais mots passeraient ("message" -> "sage").
_PLAY_GLUED = re.compile(r"^(?:mais|mai|may|mes|met|me)([a-z][\w']+\s+\S.*)$")
_ARTICLE = _rx(r"(?:du|des|de la|de) (?=\S)")  # sans ^ : appele avec une position
_ON_SPOTIFY = _rx(r" (?:sur|dans|avec|depuis) spotify$")  # "joue Daryana sur Spotify"


def _words(name: str) -> str:
    return r"\s+".join(re.escape(w) for w in _fold(name).split())


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip(".,;:!?…¿¡ ")).strip()


def _split_channel(rest: str, rest_orig: str, settings: Settings) -> tuple[str, str] | None:
    """Separe '<salon> <texte>' : salon connu (le plus long d'abord), sinon premier mot."""
    for name in sorted(settings.discord_channels, key=len, reverse=True):
        m = re.match(rf"({_words(name)})\s+(.+)$", rest)
        if m:
            return rest_orig[:m.end(1)], rest_orig[m.start(2):]
    m = re.match(r"(\S+)\s+(.+)$", rest)
    if m:
        return rest_orig[:m.end(1)], rest_orig[m.start(2):]
    return None


def _unrepeat(text: str) -> str:
    """Whisper repete parfois l'enonce : "Mets X ! Mets X !" -> "Mets X"."""
    parts = [p for p in (_clean(x) for x in re.split(r"[.!?…]+", text)) if p]
    if len(parts) > 1 and len({_fold(p) for p in parts}) == 1:
        return parts[0]
    return text


_INNER_PUNCT = re.compile(r"[,;:!?…«»\"“”]")
_STRIP = " ,;:!?….«»\"“”"


def parse(text: str, settings: Settings) -> Intent | None:
    orig = _clean(_unrepeat(text))
    if not orig:
        return None
    t = _fold(orig)
    canonical = {_fold(_clean(k)): v for k, v in settings.synonyms.items()}
    if t in canonical:
        orig = _clean(canonical[t])
        t = _fold(orig)
    # Whisper ponctue a l'interieur des phrases ("Lance, ma playlist..."). On ne le voit que dans le
    # texte compare (meme longueur) ; les arguments sont toujours pris dans `orig`.
    t = _INNER_PUNCT.sub(" ", t)

    for action, rx in _SIMPLE_RULES:
        if rx.match(t):
            return Intent(action, {})

    if m := _VOLUME.match(t):
        return Intent("spotify.volume", {"level": m.group(1)})
    if _VOLUME_UP.match(t):
        return Intent("spotify.volume", {"step": "up"})
    if _VOLUME_DOWN.match(t):
        return Intent("spotify.volume", {"step": "down"})

    for name in sorted(settings.projects, key=len, reverse=True):
        key = _words(name)
        rx = _rx(rf"^(?:demande|dis) (?:a|à) claude (?:sur|dans|pour|avec) ({key}) {_DE}(.+)$")
        if m := rx.match(t):
            return Intent("claude.prompt", {"project": name, "prompt": orig[m.start(2):]})

    if m := _CONTINUE.match(t):
        return Intent("claude.continue", {"prompt": orig[m.start(1):]})

    if m := _MESSAGE.match(t):
        split = _split_channel(m.group(1), orig[m.start(1):], settings)
        if split:
            return Intent("discord.message", {"channel": split[0], "text": split[1]})
        return None

    if m := _MOVE.match(t):
        return Intent("discord.move_self", {"channel": orig[m.start(1):]})

    if m := _MUTE_MEMBER.match(t):
        return Intent("discord.mute_member", {"member": orig[m.start(1):]})

    # Ordre court finissant par "DJ" : le verbe est souvent deforme ("Laisse le DJ", "La c'est DJ").
    # "mets DJ Snake" reste une recherche : DJ n'y est pas le dernier mot.
    if len(t.split()) <= _MISHEARD_MAX_WORDS and _DJ_LAST.search(t):
        return Intent("spotify.dj", {})

    if _LIKE.match(t):
        return Intent("spotify.like", {})

    if m := _ADD_TO_PLAYLIST.match(t):
        return Intent("spotify.add_to_playlist", {"playlist": orig[m.start(1):].strip(_STRIP)})
    if _ADD_VERB.match(t):
        return None

    if m := _REMEMBER.match(t):
        return Intent("spotify.remember", {"name": orig[m.start(1):].strip(_STRIP)})

    if len(t.split()) <= _MY_PLAYLIST_MAX_WORDS and (m := _MY_PLAYLIST.search(t)):
        intent = _play(orig, t, m.start("q"))
        args = {**intent.args, "kind": "playlist"}
        if m.group("det") in ("ma", "mes"):
            args["mine"] = "1"  # "ma playlist" : jamais celle d'un inconnu dans le catalogue
        return Intent("spotify.play", args)

    if m := _PLAY.match(t):
        return _play(orig, t, m.start(1))

    if len(t.split()) <= _MISHEARD_MAX_WORDS:
        if m := _PLAY_MISHEARD.match(t) or _PLAY_GLUED.match(t):
            return _play(orig, t, m.start(1))

    return None


def _play(orig: str, folded: str, start: int) -> Intent:
    """Requete Spotify depuis `start`, sans article en tete ("mets du Daft Punk")."""
    if (a := _ARTICLE.match(folded, start)) and folded[a.end():].strip():
        start = a.end()
    end = len(folded)
    if (s := _ON_SPOTIFY.search(folded, start)) and s.start() > start:
        end = s.start()
    return Intent("spotify.play", {"query": orig[start:end].strip(_STRIP)})
