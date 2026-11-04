"""Vocabulaire passe a la transcription pour mieux reconnaitre les noms propres."""
from __future__ import annotations

import unicodedata
from collections.abc import Callable

from drvocal.config import Settings


def _key(term: str) -> str:
    decomposed = unicodedata.normalize("NFD", term.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def build_vocabulary(groups: list[list[str]], max_chars: int = 400) -> str:
    """Termes uniques (casse et accents ignores), groupes par priorite, au plus `max_chars` sans couper un terme."""
    seen: set[str] = set()
    out = ""
    for group in groups:
        for raw in group:
            term = raw.strip()
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
