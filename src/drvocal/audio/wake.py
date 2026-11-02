from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from drvocal.audio.mic import FRAME_MS


class WakeEngine(Protocol):
    """Protocole commun aux moteurs de reveil (openWakeWord, Porcupine, bouton).

    `process` recoit une trame int16 mono de 80 ms a 16 kHz et renvoie True
    une seule fois par declenchement.
    """

    def process(self, frame: np.ndarray) -> bool: ...


class WakeDetector:
    """Detecteur de mot de reveil openWakeWord (ONNX, processeur).

    Le modele se charge au premier appel de `process` : openWakeWord et
    onnxruntime ne sont importes qu'a ce moment. Apres un reveil, `cooldown_s`
    secondes sont ignorees pour qu'une meme phrase ne declenche pas deux fois.
    """

    def __init__(
        self,
        model_paths: list[Path],
        threshold: float,
        *,
        model: Any = None,
        cooldown_s: float = 2.0,
    ) -> None:
        self._paths = list(model_paths)
        self._threshold = threshold
        self._model = model
        self._cooldown_frames = math.ceil(cooldown_s * 1000 / FRAME_MS)
        self._cooldown_left = 0

    def _load(self) -> Any:
        if self._model is None:
            from openwakeword.model import Model

            self._model = Model(wakeword_model_paths=[str(p) for p in self._paths])
        return self._model

    def process(self, frame: np.ndarray) -> bool:
        scores = self._load().predict(frame)
        if self._cooldown_left > 0:
            self._cooldown_left -= 1
            return False
        if scores and max(scores.values()) >= self._threshold:
            self._cooldown_left = self._cooldown_frames
            return True
        return False
