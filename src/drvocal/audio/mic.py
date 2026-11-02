from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_MS = 80
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000


def _open_default_stream() -> Any:
    import sounddevice as sd

    return sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME_SAMPLES
    )


class MicStream:
    """Capture du micro physique en trames int16 mono de 80 ms.

    Une erreur de peripherique ne leve jamais : on attend puis on rouvre.
    """

    def __init__(
        self,
        stream_factory: Callable[[], Any] = _open_default_stream,
        retry_delay_s: float = 2.0,
    ) -> None:
        self._factory = stream_factory
        self._retry_delay_s = retry_delay_s

    async def frames(self) -> AsyncIterator[np.ndarray]:
        while True:
            try:
                with self._factory() as stream:
                    while True:
                        data, _overflowed = await asyncio.to_thread(
                            stream.read, FRAME_SAMPLES
                        )
                        yield np.asarray(data, dtype=np.int16).reshape(-1)[:FRAME_SAMPLES]
            except Exception as exc:  # peripherique absent, debranche, occupe...
                log.warning("micro indisponible (%s), nouvel essai", exc)
                await asyncio.sleep(self._retry_delay_s)
