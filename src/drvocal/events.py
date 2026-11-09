"""Evenement affiche sur le deuxieme ecran."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionEvent:
    kind: str  # "text", "done" ou "error"
    text: str
