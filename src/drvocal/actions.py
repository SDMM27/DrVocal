"""Catalogue ferme des actions : seules les actions enregistrees ici peuvent s'executer."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from drvocal.intent import Intent

ACTION_NAMES = frozenset({
    "spotify.play",
    "spotify.pause",
    "spotify.resume",
    "spotify.next",
    "spotify.previous",
    "spotify.volume",
    "spotify.dj",
    "spotify.remember",
    "spotify.like",
    "spotify.add_to_playlist",
    "spotify.undo",
    "discord.mute_self",
    "discord.deafen_self",
    "discord.message",
    "discord.move_self",
    "discord.mute_member",
    "notes.start",
    "claude.prompt",
    "claude.continue",
    "claude.stop",
})


@dataclass(frozen=True)
class Outcome:
    ok: bool
    speak: str | None = None


Handler = Callable[[Intent], Awaitable[Outcome]]


class Catalogue:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, name: str, handler: Handler) -> None:
        if name not in ACTION_NAMES:
            raise ValueError(f"Action hors catalogue : {name}")
        self._handlers[name] = handler

    def names(self) -> list[str]:
        return sorted(self._handlers)

    async def run(self, intent: Intent) -> Outcome:
        handler = self._handlers.get(intent.action)
        if handler is None:
            return Outcome(False, "Je ne sais pas faire ça.")
        try:
            return await handler(intent)
        except Exception:
            return Outcome(False, "Je n'ai pas réussi.")
