from __future__ import annotations

import threading
from typing import Any

import numpy as np


class Transcriber:
    """Transcription faster-whisper en francais, modele charge a la demande."""

    def __init__(self, model: str, device: str, compute_type: str = "int8") -> None:
        self._model_name = model
        self._device = device
        self._compute_type = compute_type
        self._model: Any = None
        self._load_lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self) -> Any:
        with self._load_lock:  # le prechargement peut croiser une premiere transcription
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self._model_name, device=self._device, compute_type=self._compute_type
                )
            return self._model

    def preload(self) -> None:
        """Charge le modele maintenant (une vingtaine de secondes sur processeur), a appeler hors de la boucle."""
        self._ensure_loaded()

    def transcribe(self, audio: np.ndarray) -> str:
        model = self._ensure_loaded()
        samples = audio.astype(np.float32) / 32768.0
        segments, _info = model.transcribe(
            samples, language="fr", beam_size=1, vad_filter=False
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def unload(self) -> None:
        self._model = None
