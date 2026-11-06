import dataclasses
from unittest.mock import MagicMock

from drvocal.actions import Catalogue
from drvocal.actions_hotkeys import parse_combo, register_hotkeys
from drvocal.intent import Intent


def make(settings, hotkeys, enabled=True):
    s = dataclasses.replace(settings, discord_hotkeys=hotkeys, simulated_hotkeys_enabled=enabled)
    send = MagicMock()
    cat = Catalogue()
    register_hotkeys(cat, send, s)
    return cat, send


async def test_mute_sends_configured_combo(settings):
    cat, send = make(settings, {"mute": "ctrl+shift+m", "deafen": "ctrl+shift+d"})
    out = await cat.run(Intent("discord.mute_self", {}))
    assert out.ok
    send.assert_called_once_with("ctrl+shift+m")
    out = await cat.run(Intent("discord.deafen_self", {}))
    assert out.ok
    send.assert_called_with("ctrl+shift+d")


async def test_missing_hotkey_returns_not_ok(settings):
    cat, send = make(settings, {"mute": "ctrl+shift+m"})
    out = await cat.run(Intent("discord.deafen_self", {}))
    assert not out.ok and out.speak
    send.assert_not_called()


async def test_disabled_by_default_sends_nothing(settings):
    assert settings.simulated_hotkeys_enabled is False
    cat, send = make(settings, {"mute": "ctrl+shift+m"}, enabled=False)
    out = await cat.run(Intent("discord.mute_self", {}))
    assert not out.ok and out.speak
    send.assert_not_called()


async def test_invalid_combo_returns_not_ok(settings):
    cat, send = make(settings, {"mute": "ctrl+banane"})
    out = await cat.run(Intent("discord.mute_self", {}))
    assert not out.ok
    send.assert_not_called()


async def test_send_failure_returns_not_ok(settings):
    cat, send = make(settings, {"mute": "ctrl+m"})
    send.side_effect = OSError("SendInput")
    assert not (await cat.run(Intent("discord.mute_self", {}))).ok


def test_parse_combo_gives_virtual_keys():
    assert parse_combo("ctrl+shift+m") == [0x11, 0x10, 0x4D]
    assert parse_combo(" Ctrl + Alt + F5 ") == [0x11, 0x12, 0x74]
    assert parse_combo("f13") == [0x7C]
    assert parse_combo("win+7") == [0x5B, 0x37]


def test_parse_combo_rejects_invalid():
    for bad in ["", "ctrl+", "ctrl+banane", "m+ctrl", "ctrl+ctrl+m", "ctrl+shift", "a+b"]:
        try:
            parse_combo(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_example_config_flag_is_top_level_and_off():
    import tomllib
    from pathlib import Path
    data = tomllib.loads(Path("config.example.toml").read_text(encoding="utf-8"))
    assert data["simulated_hotkeys_enabled"] is False
    assert data["discord"]["hotkeys"]["deafen"]


def test_input_struct_size_matches_windows_abi():
    import ctypes

    from drvocal.actions_hotkeys import _INPUT
    assert ctypes.sizeof(_INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
