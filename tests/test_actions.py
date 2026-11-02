import re

import pytest

from drvocal.actions import ACTION_NAMES, Catalogue, Outcome
from drvocal.intent import Intent


async def test_catalogue_rejects_unregistered_action():
    assert (await Catalogue().run(Intent("system.shutdown", {}))).ok is False


async def test_catalogue_runs_registered_handler():
    async def handler(intent):
        return Outcome(True, f"ok {intent.args['query']}")

    cat = Catalogue()
    cat.register("spotify.play", handler)
    assert await cat.run(Intent("spotify.play", {"query": "x"})) == Outcome(True, "ok x")
    assert cat.names() == ["spotify.play"]


def test_register_refuses_name_outside_catalogue():
    async def handler(intent):
        return Outcome(True)

    with pytest.raises(ValueError):
        Catalogue().register("system.shutdown", handler)


async def test_handler_exception_gives_failed_outcome():
    async def boom(intent):
        raise RuntimeError("x")

    cat = Catalogue()
    cat.register("spotify.pause", boom)
    assert (await cat.run(Intent("spotify.pause", {}))).ok is False


def test_catalogue_contains_no_destructive_action():
    assert not [n for n in ACTION_NAMES if re.search("delete|close|kill|shutdown|remove", n)]


def test_action_names_are_the_expected_closed_set():
    assert ACTION_NAMES == frozenset({
        "spotify.play", "spotify.pause", "spotify.resume", "spotify.next", "spotify.previous",
        "spotify.volume", "discord.mute_self", "discord.deafen_self", "discord.message",
        "discord.move_self", "discord.mute_member", "notes.start", "claude.prompt",
        "claude.continue"})
