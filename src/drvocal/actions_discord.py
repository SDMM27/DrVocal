"""Actions Discord via un bot personnel : message, deplacement vocal, sourdine de membre.

Le bot n'agit que dans les serveurs ou le proprietaire est membre et ne repond a aucun
message, commande ou mention : aucun evenement n'est ecoute, pas d'intent message_content.
"""
import unicodedata
from collections.abc import Awaitable, Callable
from typing import Any

import discord

from drvocal.actions import Catalogue, Outcome
from drvocal.config import Settings
from drvocal.intent import Intent

CANCEL_DELAY = 4.0
# View Channels, Send Messages, Mute Members, Deafen Members, Move Members, Connect.
BOT_PERMISSIONS = 30411776


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


class _Refused(Exception):
    """Echec previsible, avec la raison a dire a voix haute."""


def make_client() -> discord.Client:
    """Client aux intents minimaux, sans aucun gestionnaire d'evenement."""
    intents = discord.Intents.none()
    intents.guilds = True
    intents.voice_states = True
    intents.members = True
    return discord.Client(intents=intents)


async def run_bot(token: str, client: discord.Client) -> None:
    """Demarre le bot (bloquant jusqu'a l'arret). Le jeton n'est jamais journalise."""
    await client.start(token)


def register_discord(catalogue: Catalogue, bot: discord.Client, settings: Settings,
                     speak: Callable[[str], Awaitable[None]],
                     wait_cancel: Callable[[float], Awaitable[bool]],
                     owner_id: int, register_self_voice: bool = False) -> None:
    def owner_guilds() -> list[discord.Guild]:
        return [g for g in bot.guilds if g.get_member(owner_id) is not None]

    def voice_guild() -> tuple[discord.Guild, discord.Member]:
        for guild in owner_guilds():
            owner = guild.get_member(owner_id)
            if owner is not None and owner.voice is not None and owner.voice.channel is not None:
                return guild, owner
        raise _Refused("Tu n'es dans aucun salon vocal.")

    def pick(candidates: list, kind: str, name: str):
        if not candidates:
            raise _Refused(f"Je ne trouve pas {kind} {name}.")
        if len(candidates) > 1:
            raise _Refused(f"Plusieurs correspondances pour {name}, je ne fais rien.")
        return candidates[0]

    def find_channel(name: str, kinds: tuple[type, ...], guilds: list[discord.Guild]):
        key = _norm(name)
        configured = {_norm(k): v for k, v in settings.discord_channels.items()}
        found = []
        if key in configured:
            found = [c for g in guilds if isinstance(c := g.get_channel(configured[key]), kinds)]
        if not found:
            found = [c for g in guilds for c in g.channels
                     if isinstance(c, kinds) and _norm(c.name) == key]
        return pick(found, "le salon", name)

    def find_member(name: str, guilds: list[discord.Guild]) -> discord.Member:
        key = _norm(name)
        configured = {_norm(k): v for k, v in settings.discord_members.items()}
        found = []
        if key in configured:
            found = [m for g in guilds if (m := g.get_member(configured[key])) is not None]
        if not found:
            found = [m for g in guilds for m in g.members if _norm(m.display_name) == key]
        return pick(found, "le membre", name)

    def guarded(fn):
        async def handler(intent: Intent) -> Outcome:
            try:
                return await fn(intent)
            except _Refused as e:
                return Outcome(False, str(e))
            except discord.Forbidden:
                return Outcome(False, "Je n'ai pas la permission sur Discord.")
            except discord.DiscordException:
                return Outcome(False, "Discord a refusé l'action.")
        return handler

    async def message(intent: Intent) -> Outcome:
        text = str(intent.args.get("text", "")).strip()
        name = str(intent.args.get("channel", "")).strip()
        if not text or not name:
            raise _Refused("Il me manque le salon ou le message.")
        channel = find_channel(name, (discord.TextChannel,), owner_guilds())
        await speak(f"Message pour {name} : {text}. Je l'envoie dans quatre secondes.")
        if await wait_cancel(CANCEL_DELAY):
            return Outcome(True)
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        return Outcome(True, "Message envoyé.")

    async def move_self(intent: Intent) -> Outcome:
        guild, owner = voice_guild()
        channel = find_channel(str(intent.args.get("channel", "")).strip(),
                               (discord.VoiceChannel, discord.StageChannel), [guild])
        await owner.move_to(channel)
        return Outcome(True, "Déplacé.")

    async def mute_member(intent: Intent) -> Outcome:
        member = find_member(str(intent.args.get("member", "")).strip(), owner_guilds())
        if member.voice is None:
            raise _Refused(f"{member.display_name} n'est pas en vocal.")
        await member.edit(mute=True)
        return Outcome(True, f"{member.display_name} est muté.")

    def self_toggle(attr: str, kw: str, done: str):
        async def toggle(intent: Intent) -> Outcome:
            _, owner = voice_guild()
            change: dict[str, Any] = {kw: not getattr(owner.voice, attr)}
            await owner.edit(**change)
            return Outcome(True, done)
        return toggle

    catalogue.register("discord.message", guarded(message))
    catalogue.register("discord.move_self", guarded(move_self))
    catalogue.register("discord.mute_member", guarded(mute_member))
    if register_self_voice:
        catalogue.register("discord.mute_self",
                           guarded(self_toggle("mute", "mute", "Micro basculé.")))
        catalogue.register("discord.deafen_self",
                           guarded(self_toggle("deaf", "deafen", "Sourdine basculée.")))
