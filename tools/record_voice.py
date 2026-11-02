"""Enregistre la voix de l'utilisateur pour entrainer et evaluer le mot de reveil.

    uv run python tools/record_voice.py [--takes 40]

Chaque phrase s'affiche, il suffit de la dire avant la fin de la barre. Ctrl+C
arrete, et relancer reprend ou l'on s'est arrete. Tout reste dans data/voice/,
ignore par git, et rien ne quitte le PC.
"""
from __future__ import annotations

import argparse
import re
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_RATE = 16000
TAKE_S = 2.5
PAUSE_S = 0.5

WAKE_PHRASES = ["salut docteur", "bonjour docteur", "bungiorno docteur", "priviet docteur"]
# Phrases proches qui ne doivent pas reveiller : servent a mesurer les faux reveils.
NEGATIVE_PHRASES = [
    "salut", "bonjour", "docteur", "salut les gars", "bonjour tout le monde",
    "le docteur est parti", "salut mon pote", "bien joue docteur",
    "passe la balle", "je vais au but", "attention derriere toi", "on a gagne",
]
NEGATIVE_TAKES = 3


def slug(phrase: str) -> str:
    return re.sub(r"\W+", "_", phrase.strip().lower())


def take_issue(audio: np.ndarray) -> str | None:
    """Signale une prise inutilisable : muette ou saturee."""
    peak = int(np.abs(audio.astype(np.int32)).max()) if audio.size else 0
    if peak < 800:
        return "trop faible"
    if peak >= 32000:
        return "saturee"
    return None


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(audio.astype(np.int16).tobytes())


def record_take() -> np.ndarray:
    import sounddevice as sd

    audio = sd.rec(int(TAKE_S * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    steps = 20
    for i in range(steps):
        print("\r    [" + "#" * (i + 1) + "." * (steps - i - 1) + "]", end="", flush=True)
        time.sleep(TAKE_S / steps)
    sd.wait()
    return audio.reshape(-1)


def record_phrase(phrase: str, folder: Path, takes: int) -> None:
    index = len(list(folder.glob("*.wav")))
    while index < takes:
        print(f'\n  ({index + 1}/{takes}) Dis : "{phrase}"')
        audio = record_take()
        issue = take_issue(audio)
        if issue:
            print(f"\n    Prise {issue}, on recommence.")
        else:
            write_wav(folder / f"{index:03d}.wav", audio)
            index += 1
        time.sleep(PAUSE_S)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--takes", type=int, default=40, help="prises par phrase de reveil")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "voice")
    args = ap.parse_args()

    import sounddevice as sd

    print(f"Micro utilise : {sd.query_devices(kind='input')['name']}")
    print("Parle normalement, comme en jeu. Varie un peu le ton et la vitesse.")
    input("Appuie sur Entree pour commencer...")
    try:
        for phrase in WAKE_PHRASES:
            print(f"\n=== {phrase} ===")
            record_phrase(phrase, args.out / "wake" / slug(phrase), args.takes)
        print("\n=== Phrases proches, qui ne doivent pas reveiller ===")
        for phrase in NEGATIVE_PHRASES:
            record_phrase(phrase, args.out / "negative" / slug(phrase), NEGATIVE_TAKES)
    except KeyboardInterrupt:
        print("\nArret. Relance la commande pour reprendre.")
        return
    print(f"\nTermine, merci ! Enregistrements dans {args.out}")


if __name__ == "__main__":
    main()
