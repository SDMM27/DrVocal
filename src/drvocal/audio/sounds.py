from __future__ import annotations

import io
import logging
import threading
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

RATE = 22050
SOUND_NAMES = ("wake", "success", "failure", "done")


def _tone(freq: float, ms: int, volume: float) -> np.ndarray:
    t = np.arange(int(RATE * ms / 1000)) / RATE
    wave_ = np.sin(2 * np.pi * freq * t)
    fade = min(len(t) // 4, int(RATE * 0.015))  # fondu : pas de claquement
    envelope = np.ones(len(t))
    envelope[:fade] = np.linspace(0, 1, fade)
    envelope[-fade:] = np.linspace(1, 0, fade)
    return wave_ * envelope * volume


def _wav(samples: np.ndarray) -> bytes:
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def default_sounds() -> dict[str, bytes]:
    """Bips courts (< 200 ms), volume modere, en WAV mis en memoire."""
    return {
        "wake": _wav(np.concatenate([_tone(660, 70, 0.3), _tone(880, 90, 0.3)])),
        "success": _wav(_tone(1175, 110, 0.25)),
        "failure": _wav(np.concatenate([_tone(440, 80, 0.3), _tone(294, 100, 0.3)])),
        "done": _wav(_tone(523, 120, 0.12)),
    }


def _play_memory(data: bytes) -> None:
    """Lecture winsound sans prendre le focus. SND_ASYNC est refuse depuis la memoire :
    on joue en synchrone dans un fil a part, ce qui ne bloque pas l'appelant."""
    def run() -> None:
        try:
            import winsound

            winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        except Exception as exc:
            log.warning("lecture du son impossible (%s)", exc)

    threading.Thread(target=run, daemon=True).start()


class SoundPlayer:
    """Joue un son par nom. Ne leve jamais ; un fichier de surcharge illisible retombe sur le defaut."""

    def __init__(self, overrides: dict[str, Path] | None = None,
                 play: Callable[[bytes], None] = _play_memory) -> None:
        self._play = play
        self._sounds = default_sounds()
        for name, path in (overrides or {}).items():
            if name not in self._sounds:
                log.warning("son inconnu dans [sounds] : %s", name)
                continue
            try:
                data = Path(path).read_bytes()
                with wave.open(io.BytesIO(data)):  # verifie que c'est un WAV valide
                    pass
                self._sounds[name] = data
            except Exception as exc:
                log.warning("son %s illisible (%s), son par defaut", name, exc)

    def play(self, name: str) -> None:
        data = self._sounds.get(name)
        if data is None:
            log.warning("son inconnu : %s", name)
            return
        try:
            self._play(data)
        except Exception as exc:
            log.warning("lecture du son %s impossible (%s)", name, exc)
