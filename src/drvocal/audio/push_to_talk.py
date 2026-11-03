from __future__ import annotations

import ctypes
from collections.abc import Callable

import numpy as np

from drvocal.actions_hotkeys import _key_code

_MOUSE = {"mouse3": 0x04, "mouse4": 0x05, "mouse5": 0x06}  # milieu, XBUTTON1, XBUTTON2


def resolve_key(name: str) -> int | None:
    """Nom de touche ou de bouton -> code de touche virtuelle, None si inconnu."""
    name = name.strip().lower()
    return _MOUSE.get(name) or _key_code(name)


def _async_key_down(vk: int) -> bool:
    """Etat physique de la touche (lecture passive, rien n'est envoye ni intercepte)."""
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


class KeyTrigger:
    """Moteur de reveil par touche a maintenir (implemente WakeEngine).

    `process` renvoie True une seule fois, sur le front montant de la touche.
    """

    def __init__(self, key: str, is_down: Callable[[int], bool] = _async_key_down) -> None:
        vk = resolve_key(key)
        if vk is None:
            raise ValueError(f"Touche inconnue : {key!r}")
        self._vk = vk
        self._is_down = is_down
        self._was_down = False

    def held(self) -> bool:
        return bool(self._is_down(self._vk))

    def process(self, frame: np.ndarray) -> bool:
        down = self.held()
        rising = down and not self._was_down
        self._was_down = down
        return rising
