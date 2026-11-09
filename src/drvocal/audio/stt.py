from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

BEAM_SIZE = 5
TOKENS_PER_S = 8  # le francais parle donne ~4 a 5 jetons par seconde : marge x2
MIN_TOKENS = 24
MAX_TOKENS = 224  # plafond de Whisper par fenetre de 30 s : 448 jetons, la moitie est le prompt


def max_new_tokens(samples: int, sample_rate: int = 16000) -> int:
    """Jetons a generer au plus par fenetre de 30 s : une transcription qui deraille s'arrete vite."""
    seconds = min(samples / sample_rate, 30.0)
    return min(MAX_TOKENS, MIN_TOKENS + round(TOKENS_PER_S * seconds))


class Transcriber:
    """Transcription faster-whisper en francais, modele charge a la demande."""

    def __init__(self, model: str, device: str, compute_type: str = "int8",
                 hotwords: Callable[[], str] | None = None) -> None:
        self._model_name = model
        self._device = device
        self._compute_type = compute_type
        self._hotwords = hotwords
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
        options: dict[str, Any] = {}
        words = self._vocabulary()
        if words:
            options["hotwords"] = words
        segments, _info = model.transcribe(
            # beam 5 : meme duree mesuree sur un ordre reel (1,7 s), noms mieux transcrits
            # ("MCPOW FOSS RICESSE" -> "MCPOW, fausse richesse"), voir docs/mesures.md.
            # Une seule passe, bornee : quand Whisper deraille (repetitions, emojis), le repli en
            # temperature relancait jusqu'a 6 decodages complets, 45 a 68 s pour 5 s d'audio.
            samples, language="fr", beam_size=BEAM_SIZE, vad_filter=False, temperature=0.0,
            condition_on_previous_text=False, max_new_tokens=max_new_tokens(len(samples)), **options
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def _vocabulary(self) -> str:
        if self._hotwords is None:
            return ""
        try:
            return self._hotwords()
        except Exception:
            log.exception("vocabulaire indisponible, transcription sans")
            return ""

    def unload(self) -> None:
        self._model = None
