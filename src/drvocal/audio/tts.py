from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

Synth = Callable[[str], tuple[np.ndarray, int]]
Play = Callable[[np.ndarray, int], None]


def _play_default(audio: np.ndarray, rate: int) -> None:
    import sounddevice as sd

    sd.play(audio, rate)
    sd.wait()


class Speaker:
    """Voix Piper : synthese puis lecture, une phrase a la fois, hors de la boucle asyncio.

    Voix absente ou erreur : avertissement journalise, retour silencieux.
    """

    def __init__(self, voice_path: Path, synth: Synth | None = None, play: Play | None = None) -> None:
        self._path = Path(voice_path)
        self._voice = None
        self._synth = synth or self._piper_synth
        self._play = play or _play_default
        self._lock = asyncio.Lock()

    def _piper_synth(self, text: str) -> tuple[np.ndarray, int]:
        if self._voice is None:
            from piper import PiperVoice

            self._voice = PiperVoice.load(self._path)
        chunks = list(self._voice.synthesize(text))
        audio = np.concatenate([c.audio_int16_array for c in chunks])
        return audio, chunks[0].sample_rate

    def _speak_blocking(self, text: str) -> None:
        audio, rate = self._synth(text)
        self._play(audio, rate)

    async def say(self, text: str) -> None:
        if not text.strip():
            return
        async with self._lock:
            if self._synth == self._piper_synth and not self._path.exists():
                log.warning("voix Piper absente (%s), phrase ignoree", self._path)
                return
            try:
                await asyncio.to_thread(self._speak_blocking, text)
            except Exception as exc:
                log.warning("synthese vocale impossible (%s)", exc)
