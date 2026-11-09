from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from drvocal.audio.mic import FRAME_MS

log = logging.getLogger(__name__)


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
    Il faut `patience` trames d'affilee au-dessus du seuil : un pic isole (musique,
    bruit) ne reveille pas (mesure du 2026-11-03, voir docs/mesures.md).
    `confirm` recoit les `confirm_window_s` dernieres secondes au moment d'un reveil et
    peut l'ecarter : le modele reagit au souffle du micro de l'utilisateur, un detecteur
    de parole verifie qu'on a vraiment parle.
    """

    def __init__(
        self,
        model_paths: list[Path],
        threshold: float,
        *,
        model: Any = None,
        cooldown_s: float = 2.0,
        patience: int = 2,
        confirm: Callable[[list[np.ndarray]], bool] | None = None,
        confirm_window_s: float = 1.6,
        on_rejected: Callable[[float], None] | None = None,
    ) -> None:
        self._paths = list(model_paths)
        self._threshold = threshold
        self._model = model
        self._cooldown_frames = math.ceil(cooldown_s * 1000 / FRAME_MS)
        self._cooldown_left = 0
        self._patience = patience
        self._above = 0
        self._confirm = confirm
        self._on_rejected = on_rejected
        self._recent: deque[np.ndarray] = deque(maxlen=math.ceil(confirm_window_s * 1000 / FRAME_MS))

    def _load(self) -> Any:
        if self._model is None:
            from openwakeword.model import Model

            self._model = Model(wakeword_model_paths=[str(p) for p in self._paths])
        return self._model

    def process(self, frame: np.ndarray) -> bool:
        scores = self._load().predict(frame)
        self._recent.append(frame)
        if self._cooldown_left > 0:
            self._cooldown_left -= 1
            return False
        score = max(scores.values()) if scores else 0.0
        self._above = self._above + 1 if score >= self._threshold else 0
        if self._above >= self._patience:
            self._above = 0
            self._cooldown_left = self._cooldown_frames  # aussi apres un rejet : pas de verification a chaque trame
            if self._confirm is not None and not self._confirm(list(self._recent)):
                log.info("reveil ecarte : pas de parole (score %.2f)", score)
                if self._on_rejected is not None:
                    try:
                        self._on_rejected(score)
                    except Exception:
                        log.exception("rappel de reveil ecarte en erreur")
                return False
            log.info("reveil (score %.2f)", score)
            return True
        return False
