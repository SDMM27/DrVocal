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


_DE = r"(?:(?:de|d'|que|qu')\s*)?"

# Ordre significatif : les regles specifiques passent avant "mets <query>".
_SIMPLE_RULES = [
    ("discord.deafen_self", _rx(r"^(?:mets~moi en sourdine|mets~moi sourd)$")),
    ("discord.mute_self", _rx(r"^(?:(?:coupe|mute|desactive) (?:mon|le) micro|(?:coupe|mute)~moi)$")),
    ("spotify.pause", _rx(r"^(?:pause|mets (?:la musique )?en pause|arrete la musique)$")),
    ("spotify.resume", _rx(r"^(?:reprends|reprend|relance) (?:la )?(?:musique|lecture)$")),
    ("spotify.next", _rx(r"^(?:musique suivante|chanson suivante|morceau suivant|suivant|passe la (?:musique|chanson))$")),
    ("spotify.previous", _rx(r"^(?:musique precedente|chanson precedente|morceau precedent|precedent)$")),
    ("notes.start", _rx(r"^(?:prends|prend|fais|ecris) une note$")),
]
_VOLUME = _rx(r"^volume (\d{1,3})\s*(?:%|pour\s*cent)?$")
_MESSAGE = _rx(r"^(?:ecris|envoie) dans (?:le salon )?(.+)$")
_MOVE = _rx(r"^(?:va|vas|viens|mets~moi|deplace~moi) (?:dans|sur) (?:le )?(?:salon )?(.+)$")
_MUTE_MEMBER = _rx(r"^(?:mute|coupe le micro de|rends muet) (.+)$")
_CONTINUE = _rx(rf"^continue avec claude {_DE}(.+)$")
_PLAY = _rx(r"^(?:mets|joue|lance) (.+)$")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip(".,;:!?…¿¡ ")).strip()


def _split_channel(rest: str, rest_orig: str, settings: Settings) -> tuple[str, str] | None:
    """Separe '<salon> <texte>' : salon connu (le plus long d'abord), sinon premier mot."""
    for name in sorted(settings.discord_channels, key=len, reverse=True):
        m = re.match(rf"({_fold(name).replace(' ', r'\s+')})\s+(.+)$", rest)
        if m:
            return rest_orig[:m.end(1)], rest_orig[m.start(2):]
    m = re.match(r"(\S+)\s+(.+)$", rest)
    if m:
        return rest_orig[:m.end(1)], rest_orig[m.start(2):]
    return None


def parse(text: str, settings: Settings) -> Intent | None:
    orig = _clean(text)
    if not orig:
        return None
    t = _fold(orig)

    for action, rx in _SIMPLE_RULES:
        if rx.match(t):
            return Intent(action, {})

    if m := _VOLUME.match(t):
        return Intent("spotify.volume", {"level": m.group(1)})

    for name in sorted(settings.projects, key=len, reverse=True):
        key = _fold(name).replace(" ", r"\s+")
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

    if m := _PLAY.match(t):
        return Intent("spotify.play", {"query": orig[m.start(1):]})

    return None
