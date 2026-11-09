"""Vocabulaire passe a la transcription pour mieux reconnaitre les noms propres."""
from __future__ import annotations

import unicodedata
from collections.abc import Callable

from drvocal.config import Settings


def _key(term: str) -> str:
    decomposed = unicodedata.normalize("NFD", term.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


_KEPT_PUNCT = "'&-."
_EDGE = " " + _KEPT_PUNCT


def _latin(c: str) -> bool:
    return c.isdigit() or (c.isalpha() and "LATIN" in unicodedata.name(c, ""))


def clean_term(raw: str) -> str:
    """Garde lettres latines, chiffres et `' & - .` ; emojis, symboles et autres alphabets deviennent des espaces.

    Un nom de playlist comme "Metal 🤘" ou "𝐂𝐋𝐔𝐁" pousse Whisper
    a halluciner (emojis, autres langues) pendant une minute : NFKC ramene les lettres stylisees a l'ASCII.
    """
    text = unicodedata.normalize("NFKC", raw).replace("’", "'")
    kept = "".join(c if _latin(c) or c in _KEPT_PUNCT else " " for c in text)
    term = " ".join(kept.split()).strip(_EDGE)
    return term if any(c.isalpha() for c in term) else ""


def build_vocabulary(groups: list[list[str]], max_chars: int = 400) -> str:
    """Termes uniques (casse et accents ignores), groupes par priorite, au plus `max_chars` sans couper un terme."""
    seen: set[str] = set()
    out = ""
    for group in groups:
        for raw in group:
            term = clean_term(raw)
            key = _key(term)
            if not term or key in seen:
                continue
            seen.add(key)
            candidate = f"{out}, {term}" if out else term
            if len(candidate) > max_chars:
                return out
            out = candidate
    return out


def make_hotwords(settings: Settings, spotify_names: Callable[[], list[str]] | None = None) -> Callable[[], str]:
    def hotwords() -> str:
        groups = [
            list(settings.stt_vocabulary),
            list(settings.projects),
            list(settings.discord_channels),
            list(settings.discord_members),
        ]
        if spotify_names is not None:
            groups.append(spotify_names())
        return build_vocabulary(groups)

    return hotwords
