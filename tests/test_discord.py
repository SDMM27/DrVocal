import dataclasses
from unittest.mock import AsyncMock, MagicMock

import pytest

discord = pytest.importorskip("discord")

from drvocal.actions import Catalogue  # noqa: E402
from drvocal.actions_discord import BOT_PERMISSIONS, make_client, register_discord, run_bot  # noqa: E402
from drvocal.intent import Intent  # noqa: E402

OWNER = 99


def make_member(uid, name, voice_channel=None, mute=False, deaf=False):
    m = MagicMock(spec=discord.Member)
    m.id, m.display_name = uid, name
    m.edit, m.move_to = AsyncMock(), AsyncMock()
    if voice_channel is None:
        m.voice = None
    else:
        m.voice = MagicMock(channel=voice_channel, mute=mute, deaf=deaf)
    return m


def make_text(cid, name):
    c = MagicMock(spec=discord.TextChannel)
    c.id, c.name = cid, name
    c.send = AsyncMock()
    return c


def make_voice(cid, name):
    c = MagicMock(spec=discord.VoiceChannel)
    c.id, c.name = cid, name
    return c


def make_guild(members, channels):
    g = MagicMock(spec=discord.Guild)
    g.members = members
    g.channels = channels
    g.get_member.side_effect = lambda i: next((m for m in members if m.id == i), None)
    g.get_channel.side_effect = lambda i: next((c for c in channels if c.id == i), None)
    return g


class Env:
    def __init__(self, settings, owner_in_voice=True, extra_members=(), self_voice=True):
        self.general = make_text(1, "Général")
        self.salon = make_voice(2, "Salon de Jeu")
        self.ranked = make_voice(3, "Ranked")
        self.owner = make_member(OWNER, "Moi", self.salon if owner_in_voice else None)
        self.paul = make_member(10, "Paul", self.salon)
        members = [self.owner, self.paul, *extra_members]
        self.guild = make_guild(members, [self.general, self.salon, self.ranked])
        self.stranger_text = make_text(50, "Général")
        self.stranger_guild = make_guild([make_member(5, "Autre")], [self.stranger_text])
        self.bot = MagicMock(spec=discord.Client)
        self.bot.guilds = [self.stranger_guild, self.guild]
        self.speak = AsyncMock()
        self.wait_cancel = AsyncMock(return_value=False)
        self.cat = Catalogue()
        register_discord(self.cat, self.bot, settings, self.speak, self.wait_cancel, OWNER,
                         register_self_voice=self_voice)

    async def run(self, intent):
        return await self.cat.run(intent)


@pytest.fixture
def env(settings):
    return Env(settings)


async def test_message_is_read_back_then_sent(env):
    out = await env.run(Intent("discord.message", {"channel": "général", "text": "j'arrive"}))
    assert out.ok
    env.speak.assert_awaited_once()
    assert "j'arrive" in env.speak.await_args.args[0]
    env.wait_cancel.assert_awaited_once_with(4.0)
    env.general.send.assert_awaited_once()
    assert env.general.send.await_args.args == ("j'arrive",)


async def test_message_disallows_all_mentions(env):
    await env.run(Intent("discord.message", {"channel": "général", "text": "@everyone salut"}))
    env.general.send.assert_awaited_once()
    assert env.general.send.await_args.args == ("@everyone salut",)
    mentions = env.general.send.await_args.kwargs["allowed_mentions"]
    assert (mentions.everyone, mentions.users, mentions.roles, mentions.replied_user) == (
        False, False, False, False)


async def test_cancel_prevents_send(env):
    env.wait_cancel.return_value = True
    out = await env.run(Intent("discord.message", {"channel": "général", "text": "j'arrive"}))
    env.general.send.assert_not_awaited()
    assert out.ok and out.speak is None


async def test_unknown_channel_is_not_ok(env):
    out = await env.run(Intent("discord.message", {"channel": "inconnu", "text": "x"}))
    assert not out.ok and out.speak
    env.speak.assert_not_awaited()


async def test_message_does_not_target_voice_channels(env):
    out = await env.run(Intent("discord.message", {"channel": "ranked", "text": "x"}))
    assert not out.ok and out.speak


async def test_message_matches_discord_name_case_and_accent_insensitive(settings):
    env = Env(dataclasses.replace(settings, discord_channels={}))
    out = await env.run(Intent("discord.message", {"channel": "GENERAL", "text": "x"}))
    assert out.ok
    env.general.send.assert_awaited_once()


async def test_message_never_partial_match(settings):
    env = Env(dataclasses.replace(settings, discord_channels={}))
    out = await env.run(Intent("discord.message", {"channel": "gen", "text": "x"}))
    assert not out.ok
    env.general.send.assert_not_awaited()


async def test_message_never_goes_to_guild_without_owner(settings):
    env = Env(dataclasses.replace(settings, discord_channels={"général": 50}))
    out = await env.run(Intent("discord.message", {"channel": "général", "text": "x"}))
    env.stranger_text.send.assert_not_awaited()
    env.general.send.assert_awaited_once()  # repli par nom dans le serveur du proprietaire
    assert out.ok


async def test_ambiguous_member_does_nothing(settings):
    env = Env(dataclasses.replace(settings, discord_members={}),
              extra_members=[make_member(11, "paul", None)])
    out = await env.run(Intent("discord.mute_member", {"member": "Paul"}))
    assert not out.ok and out.speak
    env.paul.edit.assert_not_awaited()


async def test_mute_uses_server_mute(env):
    out = await env.run(Intent("discord.mute_member", {"member": "paul"}))
    assert out.ok
    env.paul.edit.assert_awaited_once_with(mute=True)


async def test_mute_member_not_in_voice_is_not_ok(env):
    env.paul.voice = None
    out = await env.run(Intent("discord.mute_member", {"member": "paul"}))
    assert not out.ok and out.speak
    env.paul.edit.assert_not_awaited()


async def test_unknown_member_is_not_ok(env):
    out = await env.run(Intent("discord.mute_member", {"member": "zoe"}))
    assert not out.ok and out.speak


async def test_move_self(env):
    out = await env.run(Intent("discord.move_self", {"channel": "ranked"}))
    assert out.ok
    env.owner.move_to.assert_awaited_once_with(env.ranked)


async def test_move_does_not_target_text_channels(env):
    out = await env.run(Intent("discord.move_self", {"channel": "général"}))
    assert not out.ok
    env.owner.move_to.assert_not_awaited()


async def test_move_when_owner_not_in_voice_is_not_ok(settings):
    env = Env(settings, owner_in_voice=False)
    out = await env.run(Intent("discord.move_self", {"channel": "ranked"}))
    assert not out.ok and out.speak
    env.owner.move_to.assert_not_awaited()


async def test_missing_permission_is_not_ok(env):
    env.paul.edit.side_effect = discord.Forbidden(MagicMock(status=403, reason="x"), "Missing Permissions")
    out = await env.run(Intent("discord.mute_member", {"member": "paul"}))
    assert not out.ok and out.speak


async def test_send_failure_is_not_ok(env):
    env.general.send.side_effect = discord.HTTPException(MagicMock(status=500, reason="x"), "boom")
    out = await env.run(Intent("discord.message", {"channel": "général", "text": "x"}))
    assert not out.ok and out.speak


async def test_self_voice_toggles_server_mute_and_deaf(env):
    out = await env.run(Intent("discord.mute_self", {}))
    assert out.ok
    env.owner.edit.assert_awaited_once_with(mute=True)
    env.owner.voice.deaf = True
    await env.run(Intent("discord.deafen_self", {}))
    env.owner.edit.assert_awaited_with(deafen=False)


async def test_self_voice_when_not_in_voice_is_not_ok(settings):
    env = Env(settings, owner_in_voice=False)
    out = await env.run(Intent("discord.mute_self", {}))
    assert not out.ok and out.speak
    env.owner.edit.assert_not_awaited()


async def test_self_voice_not_registered_when_disabled(settings):
    env = Env(settings, self_voice=False)
    assert "discord.mute_self" not in env.cat.names()
    assert "discord.deafen_self" not in env.cat.names()
    assert {"discord.message", "discord.move_self", "discord.mute_member"} <= set(env.cat.names())


async def test_no_double_registration(settings):
    cat = Catalogue()
    cat.register = MagicMock(wraps=cat.register)
    bot = MagicMock(spec=discord.Client)
    bot.guilds = []
    register_discord(cat, bot, settings, AsyncMock(), AsyncMock(), OWNER, register_self_voice=True)
    names = [c.args[0] for c in cat.register.call_args_list]
    assert len(names) == len(set(names)) == 5


def test_client_has_minimal_intents_and_no_message_content():
    intents = make_client().intents
    assert intents.guilds and intents.voice_states and intents.members
    assert not intents.message_content and not intents.messages and not intents.presences


async def test_run_bot_starts_client_with_token():
    client = MagicMock()
    client.start = AsyncMock()
    await run_bot("tok", client)
    client.start.assert_awaited_once_with("tok")


def test_bot_permissions_constant_matches_flags():
    expected = discord.Permissions(
        view_channel=True, send_messages=True, mute_members=True,
        deafen_members=True, move_members=True, connect=True)
    assert BOT_PERMISSIONS == expected.value == 30411776
