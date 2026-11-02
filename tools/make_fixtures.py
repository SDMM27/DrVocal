"""Genere les WAV de test (16 kHz mono) avec Piper TTS.

Les modeles de voix sont telecharges hors git dans models/piper :
    uv run python -m piper.download_voices fr_FR-siwis-medium --data-dir models/piper
    uv run python -m piper.download_voices fr_FR-tom-medium --data-dir models/piper

Les fixtures du mot de reveil utilisent fr_FR-tom-medium, voix absente de
l'entrainement (tools/train_wake.py), pour mesurer la generalisation.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
VOICES = ROOT / "models" / "piper"
OUT = ROOT / "tests" / "fixtures"
TARGET_RATE = 16000

EVAL_SENTENCES = ROOT / "tools" / "wake_eval_fr.txt"
GAP_S = 0.4

# nom du WAV -> (voix, texte ; une liste est concatenee avec des silences)
FIXTURES: dict[str, tuple[str, str | list[str]]] = {
    "mets_daft_punk.wav": ("fr_FR-siwis-medium", "mets daft punk"),
    "ouvre_discord.wav": ("fr_FR-siwis-medium", "ouvre discord"),
    "salut_docteur.wav": ("fr_FR-tom-medium", "salut docteur"),
    "docteur_seul.wav": ("fr_FR-tom-medium", "docteur"),
    "conversation.wav": (
        "fr_FR-tom-medium",
        [line.strip() for line in EVAL_SENTENCES.read_text(encoding="utf-8").splitlines() if line.strip()],
    ),
}


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    n = int(round(len(audio) * dst / src))
    x = np.linspace(0, len(audio) - 1, n)
    return np.interp(x, np.arange(len(audio)), audio.astype(np.float32)).astype(np.int16)


def to_16k(audio: np.ndarray, src: int) -> np.ndarray:
    if src == TARGET_RATE:
        return audio
    if src == 22050:  # chemin historique des premieres fixtures
        return resample(audio, src, TARGET_RATE)
    from scipy.signal import resample_poly

    g = np.gcd(src, TARGET_RATE)
    out = resample_poly(audio.astype(np.float32), TARGET_RATE // g, src // g)
    return np.clip(out, -32768, 32767).astype(np.int16)


def synth(voice, text: str) -> np.ndarray:
    chunks = list(voice.synthesize(text))
    audio = np.concatenate([c.audio_int16_array for c in chunks])
    return to_16k(audio, chunks[0].sample_rate)


def main() -> None:
    from piper import PiperVoice

    OUT.mkdir(parents=True, exist_ok=True)
    voices: dict[str, PiperVoice] = {}
    for name, (voice_name, text) in FIXTURES.items():
        if voice_name not in voices:
            voices[voice_name] = PiperVoice.load(VOICES / f"{voice_name}.onnx")
        voice = voices[voice_name]
        if isinstance(text, str):
            audio = synth(voice, text)
        else:
            gap = np.zeros(int(GAP_S * TARGET_RATE), dtype=np.int16)
            parts = []
            for sentence in text:
                parts += [synth(voice, sentence), gap]
            audio = np.concatenate(parts)
        with wave.open(str(OUT / name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(TARGET_RATE)
            w.writeframes(audio.tobytes())
        print(f"{name}: {len(audio) / TARGET_RATE:.2f}s")


if __name__ == "__main__":
    main()
