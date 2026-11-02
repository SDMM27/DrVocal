"""Banc d'essai STT : latence, RAM et exactitude sur les fixtures.

    uv run python tools/bench_stt.py
"""
from __future__ import annotations

import gc
import os
import sys
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from drvocal.audio.stt import Transcriber  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
EXPECTED = {
    "mets_daft_punk.wav": "mets daft punk",
    "ouvre_discord.wav": "ouvre discord",
}
MODELS = ["small", "medium", "large-v3-turbo"]
DEVICES = ["cpu", "cuda"]


def norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def rss_mb() -> float:
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1024 / 1024


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def cuda_available() -> bool:
    """Evite de tenter (et de bloquer sur) un chargement GPU sans bibliotheques CUDA."""
    import ctypes

    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() == 0:
            return False
        ctypes.WinDLL("cublas64_12.dll")
        return True
    except Exception:
        return False


def bench(model: str, device: str) -> tuple[str, str, str]:
    if device == "cuda" and not cuda_available():
        return "indisponible", "indisponible", "indisponible"
    print(f"[{model}/{device}] ...", file=sys.stderr, flush=True)
    t = Transcriber(model, device)
    try:
        base = rss_mb()
        first = time.perf_counter()
        t.transcribe(load_wav(next(iter(FIXTURES.glob("*.wav")))))  # chargement + 1er appel
        load_s = time.perf_counter() - first
        ram = rss_mb() - base
        lat, ok = [], 0
        for name, expected in EXPECTED.items():
            audio = load_wav(FIXTURES / name)
            start = time.perf_counter()
            text = t.transcribe(audio)
            lat.append(time.perf_counter() - start)
            ok += norm(expected) in norm(text)
        return f"{sum(lat) / len(lat):.2f} s (1er appel {load_s:.1f} s)", f"{ram:.0f} Mo", f"{ok}/{len(EXPECTED)}"
    except Exception as exc:  # bibliotheques CUDA absentes, modele introuvable...
        print(f"  [{model}/{device}] {type(exc).__name__}: {exc}", file=sys.stderr)
        return "indisponible", "indisponible", "indisponible"
    finally:
        t.unload()
        gc.collect()


def main() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    rows = [(m, d, *bench(m, d)) for d in DEVICES for m in MODELS]
    print("| modele | device | latence | RAM ajoutee | exactitude |")
    print("|---|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(row) + " |")


if __name__ == "__main__":
    main()
