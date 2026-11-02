"""Actions Discord (micro, sourdine) par simulation des raccourcis clavier globaux deja configures."""
import asyncio
import ctypes
from collections.abc import Callable
from ctypes import wintypes

from drvocal.actions import Catalogue, Outcome
from drvocal.config import Settings
from drvocal.intent import Intent

_MODIFIERS = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
_NAMED = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
          "backspace": 0x08, "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
          "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}


def _key_code(name: str) -> int | None:
    if len(name) == 1 and name.isascii() and name.isalnum():
        return ord(name.upper())
    if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return 0x70 + int(name[1:]) - 1
    return _NAMED.get(name)


def parse_combo(text: str) -> list[int]:
    """'ctrl+shift+m' -> codes de touches virtuelles (modificateurs puis touche). ValueError si invalide."""
    parts = [p.strip().lower() for p in text.split("+")]
    *mods, key = parts
    codes = []
    for m in mods:
        if m not in _MODIFIERS or _MODIFIERS[m] in codes:
            raise ValueError(f"Modificateur invalide : {m!r}")
        codes.append(_MODIFIERS[m])
    code = _key_code(key)
    if code is None:
        raise ValueError(f"Touche inconnue : {key!r}")
    return [*codes, code]


_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_EXTENDED = {0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x5B}


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def send_keys(combo: str) -> None:
    """Appuie les modificateurs puis la touche, relache dans l'ordre inverse. Windows uniquement."""
    codes = parse_combo(combo)
    events = [(c, 0) for c in codes] + [(c, _KEYEVENTF_KEYUP) for c in reversed(codes)]
    inputs = (_INPUT * len(events))()
    for i, (vk, flags) in enumerate(events):
        if vk in _EXTENDED:
            flags |= 0x0001  # KEYEVENTF_EXTENDEDKEY
        inputs[i].type = _INPUT_KEYBOARD
        inputs[i].ki = _KEYBDINPUT(vk, 0, flags, 0, 0)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    sent = user32.SendInput(len(events), inputs, ctypes.sizeof(_INPUT))
    if sent != len(events):
        raise OSError(f"SendInput a injecte {sent}/{len(events)} evenements "
                      f"(erreur {ctypes.get_last_error()})")


def register_hotkeys(catalogue: Catalogue, send: Callable[[str], None], settings: Settings) -> None:
    def make(action: str, key: str, done: str):
        async def handler(intent: Intent) -> Outcome:
            if not settings.simulated_hotkeys_enabled:
                return Outcome(False, "Les raccourcis simulés sont désactivés.")
            combo = settings.discord_hotkeys.get(key)
            if not combo:
                return Outcome(False, f"Aucun raccourci {key} n'est configuré.")
            try:
                parse_combo(combo)
            except ValueError:
                return Outcome(False, f"Le raccourci {key} est invalide.")
            await asyncio.to_thread(send, combo)
            return Outcome(True, done)
        catalogue.register(action, handler)

    make("discord.mute_self", "mute", "Micro basculé.")
    make("discord.deafen_self", "deafen", "Sourdine basculée.")
