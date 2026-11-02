"""Genere les WAV de test (16 kHz mono) avec Piper TTS.

Le modele de voix est telecharge hors git dans models/piper :
    uv run python -m piper.download_voices fr_FR-siwis-medium --data-dir models/piper
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
VOICE = ROOT / "models" / "piper" / "fr_FR-siwis-medium.onnx"
OUT = ROOT / "tests" / "fixtures"
TARGET_RATE = 16000

PHRASES = {
    "mets_daft_punk.wav": "mets daft punk",
    "ouvre_discord.wav": "ouvre discord",
}


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    n = int(round(len(audio) * dst / src))
    x = np.linspace(0, len(audio) - 1, n)
    return np.interp(x, np.arange(len(audio)), audio.astype(np.float32)).astype(np.int16)


def main() -> None:
    from piper import PiperVoice

    voice = PiperVoice.load(VOICE)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in PHRASES.items():
        chunks = list(voice.synthesize(text))
        audio = np.concatenate([c.audio_int16_array for c in chunks])
        audio = resample(audio, chunks[0].sample_rate, TARGET_RATE)
        with wave.open(str(OUT / name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(TARGET_RATE)
            w.writeframes(audio.tobytes())
        print(f"{name}: {len(audio) / TARGET_RATE:.2f}s")


if __name__ == "__main__":
    main()
