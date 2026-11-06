"""Rejoue les WAV d'echecs du journal des commandes avec les reglages actuels.

    uv run python tools/replay_commands.py
    uv run python tools/replay_commands.py --limit 20 --no-hotwords

Relit commands.jsonl (et commands.1.jsonl), re-transcrit les entrees qui ont un WAV,
re-parse le texte et compare avec ce qui avait ete compris. Le vocabulaire Spotify n'est pas utilise.
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_wake  # noqa: E402,F401  (met src/ dans sys.path)

from drvocal.__main__ import load_config  # noqa: E402
from drvocal.audio.stt import Transcriber  # noqa: E402
from drvocal.intent import parse  # noqa: E402
from drvocal.storage import data_dir  # noqa: E402
from drvocal.vocabulary import make_hotwords  # noqa: E402


def default_dir() -> Path:
    return data_dir() / "commands"


def read_entries(directory: Path) -> list[dict]:
    """Entrees avec un WAV existant, de la plus ancienne a la plus recente."""
    entries: list[dict] = []
    for name in ("commands.1.jsonl", "commands.jsonl"):
        path = directory / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("wav") and (directory / "failures" / entry["wav"]).exists():
                entries.append(entry)
    return entries


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def describe(intent) -> str:
    return "(non compris)" if intent is None else f"{intent.action} {intent.args}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, default=default_dir(), help="dossier du journal (defaut : LOCALAPPDATA/DrVocal/commands)")
    ap.add_argument("--limit", type=int, default=50, help="nombre d'entrees les plus recentes (defaut 50)")
    ap.add_argument("--no-hotwords", action="store_true", help="transcrire sans vocabulaire, pour comparer")
    args = ap.parse_args()

    settings = load_config()
    entries = read_entries(args.dir)[-args.limit:] if args.limit > 0 else []
    if not entries:
        print(f"Aucune entree avec WAV dans {args.dir}")
        return 0
    hotwords = None if args.no_hotwords else make_hotwords(settings)
    transcriber = Transcriber(settings.stt_model, settings.stt_device, hotwords=hotwords)

    understood = 0
    for entry in entries:
        audio = load_wav(args.dir / "failures" / entry["wav"])
        text = transcriber.transcribe(audio)
        intent = parse(text, settings)
        old = f"{entry['action']} {entry['args']}" if entry.get("action") else "(non compris)"
        if intent is not None and not entry.get("action"):
            understood += 1
        print(f"{entry['ts']}\n  ancien : {entry['text']!r} -> {old}\n  nouveau : {text!r} -> {describe(intent)}")
    transcriber.unload()
    never = sum(1 for e in entries if not e.get("action"))
    print(f"\n{understood} echec(s) sur {never} non compris(s) sont maintenant compris ({len(entries)} rejoue(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
