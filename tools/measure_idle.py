"""Mesure le cout en veille du mot de reveil : processeur, RAM, faux reveils.

    uv run python tools/measure_idle.py --minutes 60            # micro reel
    uv run python tools/measure_idle.py --minutes 1 --silent    # flux silencieux

Le processeur est exprime en % du total de la machine (temps CPU du processus /
(duree x nombre de coeurs logiques)). Imprime une ligne prete a coller dans
docs/mesures.md. Chaque reveil detecte est liste : pendant une vraie discussion,
tout reveil est un faux reveil.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from drvocal.audio.mic import FRAME_MS, FRAME_SAMPLES, MicStream  # noqa: E402
from drvocal.audio.wake import WakeDetector  # noqa: E402


async def silent_frames() -> AsyncIterator[np.ndarray]:
    """Flux de silence cadence en temps reel."""
    frame = np.zeros(FRAME_SAMPLES, dtype=np.int16)
    next_at = time.monotonic()
    while True:
        next_at += FRAME_MS / 1000
        await asyncio.sleep(max(0.0, next_at - time.monotonic()))
        yield frame


async def measure(minutes: float, silent: bool, threshold: float, models: list[Path]) -> None:
    import psutil

    proc = psutil.Process()
    detector = WakeDetector(models, threshold)
    detector.process(np.zeros(FRAME_SAMPLES, dtype=np.int16))  # charge le modele avant de mesurer
    frames = silent_frames() if silent else MicStream().frames()

    cores = psutil.cpu_count(logical=True) or 1
    cpu0, t0 = sum(proc.cpu_times()[:2]), time.monotonic()
    deadline = t0 + minutes * 60
    rss_peak = proc.memory_info().rss
    wakes: list[float] = []
    n_frames = 0
    async for frame in frames:
        if detector.process(frame):
            wakes.append(time.monotonic() - t0)
            print(f"  reveil a +{wakes[-1] / 60:.1f} min", flush=True)
        n_frames += 1
        if n_frames % 125 == 0:  # toutes les 10 s
            rss_peak = max(rss_peak, proc.memory_info().rss)
        if time.monotonic() >= deadline:
            break
    wall = time.monotonic() - t0
    cpu_pct = (sum(proc.cpu_times()[:2]) - cpu0) / (wall * cores) * 100
    rss_mb = max(rss_peak, proc.memory_info().rss) / 2**20

    print(f"duree {wall / 60:.1f} min, {n_frames} trames, {cores} coeurs logiques")
    print(f"processeur {cpu_pct:.2f} % du total, RAM max {rss_mb:.0f} Mo, reveils {len(wakes)}")
    source = "flux silencieux" if silent else "micro reel"
    print(
        f"| {datetime.now():%Y-%m-%d %H:%M} | {source} | {wall / 60:.0f} min | "
        f"{cpu_pct:.2f} % | {rss_mb:.0f} Mo | {len(wakes)} |"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--silent", action="store_true", help="flux de silence au lieu du micro")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--models", type=Path, default=ROOT / "models" / "wake")
    args = ap.parse_args()
    models = sorted(args.models.glob("*.onnx"))
    if not models:
        sys.exit(f"Aucun modele dans {args.models} : lancer tools/train_wake.py")
    asyncio.run(measure(args.minutes, args.silent, args.threshold, models))


if __name__ == "__main__":
    main()
