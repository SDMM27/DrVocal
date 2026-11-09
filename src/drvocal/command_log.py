"""Journal local des commandes : texte, action, resultat, et WAV des echecs (pour mesurer et rejouer)."""
from __future__ import annotations

import json
import logging
import wave
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np

from drvocal.audio.mic import SAMPLE_RATE
from drvocal.intent import Intent

log = logging.getLogger(__name__)


class CommandLog:
    """Ajoute une ligne JSON par commande dans `commands.jsonl` ; ne leve jamais d'OSError."""

    def __init__(self, dir: Path, keep_wavs: int = 200, max_bytes: int = 2_000_000,
                 now: Callable[[], datetime] = datetime.now) -> None:
        self._dir = dir
        self._keep_wavs = keep_wavs
        self._max_bytes = max_bytes
        self._now = now

    def record(self, text: str, intent: Intent | None, ok: bool | None, audio: np.ndarray | None,
               stt_ms: int | None, action_ms: int | None, reply: str | None = None) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            when = self._now()
            wav = None
            if audio is not None and len(audio) and (intent is None or ok is False):
                wav = self._write_wav(audio, when)
            line = {
                "ts": when.isoformat(timespec="seconds"),
                "text": text,
                "action": intent.action if intent else None,
                "args": intent.args if intent else None,
                "ok": ok,
                "stt_ms": stt_ms,
                "action_ms": action_ms,
                "wav": wav,
                "reply": reply,
            }
            self._append(line)
        except OSError:
            log.exception("journal des commandes impossible")

    def record_event(self, kind: str, **fields: object) -> None:
        """Evenement hors commande (reveil ecarte, rien entendu) dans le meme fichier."""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._append({"ts": self._now().isoformat(timespec="seconds"), "event": kind, **fields})
        except OSError:
            log.exception("journal des commandes impossible")

    def _append(self, line: dict) -> None:
        path = self._dir / "commands.jsonl"
        if path.exists() and path.stat().st_size > self._max_bytes:
            path.replace(self._dir / "commands.1.jsonl")
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def _write_wav(self, audio: np.ndarray, when: datetime) -> str:
        failures = self._dir / "failures"
        failures.mkdir(parents=True, exist_ok=True)
        name = f"{when:%Y-%m-%d_%H-%M-%S-%f}.wav"
        with wave.open(str(failures / name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(audio.astype(np.int16).tobytes())
        wavs = sorted(failures.glob("*.wav"))
        for old in wavs[:max(len(wavs) - self._keep_wavs, 0)]:
            old.unlink()
        return name
