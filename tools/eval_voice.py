"""Evalue les modeles de reveil sur la vraie voix de l'utilisateur (prises tenues a part).

    uv run python tools/eval_voice.py --check
    uv run python tools/eval_voice.py --split val --synthetic-negatives
    uv run python tools/eval_voice.py --split test --negatives message_vocal le_doc_est_la salut_les_gars on_a_gagne

Les modeles du dossier tournent ensemble dans le vrai `WakeDetector` (openwakeword.Model
charge comme a l'execution). Chaque WAV est diffuse trame par trame (80 ms) avec
12 trames de silence avant et apres. Les scores sont enregistres une fois par WAV
puis rejoues dans `WakeDetector` a chaque seuil (delai de reprise compris).

- positif detecte : un reveil tombe pendant le fichier (pas dans le silence ajoute) ;
- faux reveil : tout reveil sur un negatif, silence ajoute compris ;
- croisement : un modele seul (`only=`) qui se declenche sur la phrase d'un autre.

`--split train` = prises 000-055 (diagnostic en echantillon), `--split val` = prises 056-067 (choix du seuil),
`--split test` = prises 068-079 (a ne regarder qu'une fois). Les fichiers de data/voice/ ne sont jamais deplaces.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_wake  # noqa: E402  (importe aussi src/ dans sys.path)

from drvocal.audio.wake import WakeDetector  # noqa: E402

CHUNK = train_wake.CHUNK
RATE = train_wake.RATE
LEAD_FRAMES = 12
TAIL_FRAMES = 12
THRESHOLDS = [0.3, 0.5, 0.7, 0.9]
SPLITS = {"train": (0, 55), "val": (56, 67), "test": (68, 79)}
ROOT = train_wake.ROOT
VOICE = ROOT / "data" / "voice"


@dataclass
class Clip:
    label: str
    positive: bool
    scores: list[dict[str, float]]  # un dict {modele: score} par trame, silence ajoute compris
    start: int  # premiere trame du fichier
    stop: int  # apres la derniere trame du fichier
    names: list[str] = field(default_factory=list)


class ReplayModel:
    """Rejoue des scores enregistres dans WakeDetector."""

    def __init__(self, scores: list[dict[str, float]], only: str | None = None) -> None:
        self._scores = iter(scores)
        self._only = only

    def predict(self, frame: np.ndarray) -> dict[str, float]:
        s = next(self._scores)
        return {self._only: s[self._only]} if self._only else s


def score_clip(model, audio: np.ndarray, label: str, positive: bool) -> Clip:
    """Diffuse `audio` (int16) dans `model.predict`, silence avant et apres."""
    n = -(-len(audio) // CHUNK)
    body = np.zeros(n * CHUNK, dtype=np.int16)
    body[: len(audio)] = audio
    stream = np.concatenate([np.zeros(LEAD_FRAMES * CHUNK, np.int16), body, np.zeros(TAIL_FRAMES * CHUNK, np.int16)])
    scores = [dict(model.predict(stream[i : i + CHUNK])) for i in range(0, len(stream), CHUNK)]
    return Clip(label, positive, scores, LEAD_FRAMES, LEAD_FRAMES + n, sorted(scores[0]) if scores else [])


def wake_frames(clip: Clip, threshold: float, only: str | None = None) -> list[int]:
    """Trames de reveil de WakeDetector (delai de reprise inclus) a ce seuil."""
    det = WakeDetector([], threshold, model=ReplayModel(clip.scores, only))
    silence = np.zeros(CHUNK, dtype=np.int16)
    return [i for i in range(len(clip.scores)) if det.process(silence)]


def detected(clip: Clip, threshold: float, only: str | None = None) -> bool:
    return any(clip.start <= f < clip.stop for f in wake_frames(clip, threshold, only))


def false_wakes(clip: Clip, threshold: float, only: str | None = None) -> int:
    return len(wake_frames(clip, threshold, only))


def summarize(clips: list[Clip], thresholds: list[float]) -> dict:
    pos = [c for c in clips if c.positive]
    neg = [c for c in clips if not c.positive]
    labels = sorted({c.label for c in pos})
    nlabels = sorted({c.label for c in neg})
    models = sorted({n for c in clips for n in c.names})
    out = {}
    for t in thresholds:
        det = {lab: (sum(detected(c, t) for c in pos if c.label == lab), sum(c.label == lab for c in pos)) for lab in labels}
        fw = {lab: sum(false_wakes(c, t) for c in neg if c.label == lab) for lab in nlabels}
        out[t] = {
            "detections": det,
            "detections_total": (sum(d for d, _ in det.values()), len(pos)),
            "false_wakes_total": (sum(fw.values()), len(neg)),
            "false_wakes_by_label": fw,
            "false_wakes_by_model": {m: sum(false_wakes(c, t, m) for c in neg) for m in models},
            "cross": {
                m: {lab: (sum(detected(c, t, m) for c in pos if c.label == lab), sum(c.label == lab for c in pos)) for lab in labels}
                for m in models
            },
        }
    return out


# --- E/S -----------------------------------------------------------------------


def run_clip(model_paths: list[Path], audio: np.ndarray, label: str, positive: bool) -> Clip:
    model = WakeDetector(model_paths, 0.5)._load()  # meme chargement qu'a l'execution
    return score_clip(model, audio, label, positive)


def synthetic_negatives(work: Path) -> list[tuple[str, np.ndarray]]:
    """Negatifs synthetiques (voix et phrases d'evaluation, jamais entraines)."""
    synth = train_wake.Synth(work / "cache")
    sentences = [s.strip() for s in train_wake.EVAL_SENTENCES.read_text(encoding="utf-8").splitlines() if s.strip()]
    sentences += ["docteur", "salut", "salut doc", "doc", "vocal", "salut docteur", "message vocal"]
    out = []
    for k, (voice, spk) in enumerate(train_wake.EVAL_VOICES):
        for text in sentences:
            out.append((f"synth:{train_wake.slug(text)}", train_wake.trim(synth(voice, spk, text, 1.0, 9500 + k))))
    return out


def check_takes(slugs: list[str]) -> None:
    for kind in ("wake", "negative"):
        for folder in sorted(d for d in (VOICE / kind).iterdir() if d.is_dir()):
            if kind == "wake" and slugs and folder.name not in slugs:
                continue
            rows = []
            for p in train_wake.list_takes(folder):
                st = train_wake.take_stats(train_wake.read_wav(p))
                rows.append((p.name, st, train_wake.take_problems(st)))
            peaks = [r[1]["peak"] for r in rows]
            speech = [r[1]["speech_s"] for r in rows]
            print(
                f"{kind}/{folder.name}: {len(rows)} prises, pic {min(peaks)}-{max(peaks)} (median {int(np.median(peaks))}), "
                f"parole {min(speech):.2f}-{max(speech):.2f} s (median {np.median(speech):.2f})"
            )
            for name, st, probs in rows:
                if probs:
                    unusable = " [ECARTEE]" if train_wake.is_unusable(st) else ""
                    print(f"  suspecte {name}: pic {st['peak']}, parole {st['speech_s']:.2f} s : {'; '.join(probs)}{unusable}")


def print_report(res: dict, n_models: int) -> None:
    for t, r in res.items():
        d, n = r["detections_total"]
        fw, nn = r["false_wakes_total"]
        print(f"\n=== seuil {t} : detections {d}/{n}, faux reveils {fw} sur {nn} negatifs ===")
        print("  detections par phrase : " + ", ".join(f"{k} {a}/{b}" for k, (a, b) in r["detections"].items()))
        if r["false_wakes_by_label"]:
            print("  faux reveils par negatif : " + ", ".join(f"{k} {v}" for k, v in r["false_wakes_by_label"].items()))
            print("  faux reveils par modele : " + ", ".join(f"{k} {v}" for k, v in r["false_wakes_by_model"].items()))
        print("  croisement (modele -> phrase prononcee) :")
        for m, row in r["cross"].items():
            print(f"    {m:>18}: " + "  ".join(f"{k} {a}/{b}" for k, (a, b) in row.items()))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", type=Path, default=ROOT / "models" / "wake_voice")
    ap.add_argument("--phrases", nargs="*", default=["salut_doc_vocal"])
    ap.add_argument("--split", choices=list(SPLITS), default="val")
    ap.add_argument("--negatives", nargs="*", default=[], help="slugs de data/voice/negative a utiliser")
    ap.add_argument("--synthetic-negatives", action="store_true")
    ap.add_argument("--work", type=Path, default=ROOT / "models" / "wake_train")
    ap.add_argument("--thresholds", type=float, nargs="*", default=THRESHOLDS)
    ap.add_argument("--check", action="store_true", help="controle des prises (pic, parole), sans evaluer")
    ap.add_argument("--json", type=Path, help="ecrit les resultats")
    args = ap.parse_args()

    if args.check:
        check_takes(args.phrases)
        return
    paths = [args.models / f"{s}.onnx" for s in args.phrases]
    lo, hi = SPLITS[args.split]
    clips: list[Clip] = []
    for s in args.phrases:
        for p in train_wake.list_takes(VOICE / "wake" / s, hi, lo):
            audio = train_wake.read_wav(p)
            if train_wake.is_unusable(train_wake.take_stats(audio)):
                print(f"ecartee : {s}/{p.name}")
                continue
            clips.append(run_clip(paths, audio, s, True))
    for s in args.negatives:
        for p in train_wake.list_takes(VOICE / "negative" / s):
            clips.append(run_clip(paths, train_wake.read_wav(p), s, False))
    if args.synthetic_negatives:
        for label, audio in synthetic_negatives(args.work):
            clips.append(run_clip(paths, audio, label, False))
    res = summarize(clips, args.thresholds)
    print(f"split {args.split}: {sum(c.positive for c in clips)} positifs, {sum(not c.positive for c in clips)} negatifs")
    print_report(res, len(paths))
    if args.json:
        args.json.write_text(json.dumps({str(t): r for t, r in res.items()}, indent=2, default=list), encoding="utf-8")


if __name__ == "__main__":
    main()
