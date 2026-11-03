from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Any

import numpy as np

from drvocal.audio.mic import FRAME_MS, FRAME_SAMPLES, SAMPLE_RATE

_CHUNK = 512  # taille de fenetre attendue par Silero a 16 kHz
_CONTEXT = 64


class SileroVAD:
    """Detecteur de parole Silero (ONNX embarque par faster-whisper, sans torch).

    Le modele se charge au premier appel. Etat interne : appeler reset() entre
    deux enonces.
    """

    def __init__(self, threshold: float = 0.5) -> None:
        self._threshold = threshold
        self._session: Any = None
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(_CONTEXT, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)

    def reset(self) -> None:
        self._h[:] = 0
        self._c[:] = 0
        self._context[:] = 0
        self._pending = np.zeros(0, dtype=np.float32)

    def _load(self) -> Any:
        if self._session is None:
            import os

            import faster_whisper
            import onnxruntime

            path = os.path.join(
                os.path.dirname(faster_whisper.__file__), "assets", "silero_vad_v6.onnx"
            )
            opts = onnxruntime.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            opts.enable_cpu_mem_arena = False
            opts.log_severity_level = 4
            self._session = onnxruntime.InferenceSession(
                path, providers=["CPUExecutionProvider"], sess_options=opts
            )
        return self._session

    def __call__(self, frame: np.ndarray) -> bool:
        session = self._load()
        self._pending = np.concatenate(
            [self._pending, frame.astype(np.float32) / 32768.0]
        )
        peak = 0.0
        while len(self._pending) >= _CHUNK:
            chunk, self._pending = self._pending[:_CHUNK], self._pending[_CHUNK:]
            x = np.concatenate([self._context, chunk])[None, :]
            out, self._h, self._c = session.run(
                None, {"input": x, "h": self._h, "c": self._c}
            )
            self._context = chunk[-_CONTEXT:]
            peak = max(peak, float(out.reshape(-1)[0]))
        return peak >= self._threshold


def speech_confirmer(vad: Callable[[np.ndarray], bool] | None = None,
                     min_speech_ms: int = 240) -> Callable[[list[np.ndarray]], bool]:
    """Pour WakeDetector : vrai si les trames contiennent au moins `min_speech_ms` de parole."""
    detector = vad if vad is not None else SileroVAD()
    needed = max(min_speech_ms // FRAME_MS, 1)

    def confirm(frames: list[np.ndarray]) -> bool:
        if hasattr(detector, "reset"):
            detector.reset()
        return sum(bool(detector(f)) for f in frames) >= needed

    return confirm


async def capture_utterance(
    frames: AsyncIterator[np.ndarray],
    silence_ms: int,
    no_speech_timeout_ms: int,
    max_ms: int = 120000,
    is_speech: Callable[[np.ndarray], bool] | None = None,
    preroll_ms: int = 320,
) -> np.ndarray | None:
    """Accumule les trames jusqu'a `silence_ms` de silence apres la parole.

    Les `preroll_ms` precedant la premiere trame de parole sont gardes : Silero
    reagit avec un temps de retard et couperait la premiere syllabe ("mets").

    Renvoie None si aucune parole n'arrive avant `no_speech_timeout_ms` (ou si
    le flux se termine). Plafonne a `max_ms` et renvoie alors ce qui est capture.
    """
    if is_speech is None:
        detector = SileroVAD()
        detector.reset()
        is_speech = detector

    captured: list[np.ndarray] = []
    before: deque[np.ndarray] = deque(maxlen=max(preroll_ms // FRAME_MS, 0))
    waited_ms = 0
    silent_ms = 0
    total_ms = 0
    started = False

    async for frame in frames:
        speech = is_speech(frame)
        if not started:
            if not speech:
                waited_ms += FRAME_MS
                if waited_ms >= no_speech_timeout_ms:
                    return None
                before.append(frame)
                continue
            started = True
            captured.extend(before)
        captured.append(frame)
        total_ms += FRAME_MS
        silent_ms = 0 if speech else silent_ms + FRAME_MS
        if silent_ms >= silence_ms or total_ms >= max_ms:
            break

    if not started:
        return None
    return np.concatenate(captured)
