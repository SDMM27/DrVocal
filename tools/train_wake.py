"""Entraine un modele de mot de reveil openWakeWord (ONNX) pour une phrase francaise.

    uv sync --group train
    uv run python tools/train_wake.py "salut docteur" [--recordings DIR]

Version allegee du pipeline amont (openWakeWord/train.py), qui suppose un
generateur de voix anglais, ~17 Go de caracteristiques ACAV100M et une
conversion onnx_tf. Ici :

- les positifs et les negatifs sont synthetises avec plusieurs voix Piper
  francaises (models/piper), avec variations de debit et de prosodie, puis
  augmentes (gain, vitesse, bruit, murmure de fond, reverberation) ;
- `--recordings DIR` ajoute de vrais enregistrements (WAV) de la phrase,
  fortement augmentes ;
- les caracteristiques sont celles du moteur (melspectrogramme + embeddings
  openWakeWord), calculees en flux, trame par trame, comme a l'execution ;
- seul le classifieur final (petit reseau dense sur 16 embeddings) est entraine,
  puis exporte en ONNX dans models/wake/<phrase>.onnx.

Les voix de l'evaluation (fr_FR-tom-medium et deux locuteurs MLS) ne servent
jamais a l'entrainement. L'evaluation passe par WakeDetector, donc par le
chemin d'execution reel.

Voix necessaires (hors git) :
    for v in siwis-medium siwis-low gilles-low upmc-medium mls-medium tom-medium; do
      uv run python -m piper.download_voices fr_FR-$v --data-dir models/piper
    done
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import unicodedata
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

RATE = 16000
CHUNK = 1280  # 80 ms
WINDOW = 16  # embeddings par entree du classifieur
PIPER_DIR = ROOT / "models" / "piper"
NEGATIVES = ROOT / "tools" / "wake_negatives_fr.txt"
EVAL_SENTENCES = ROOT / "tools" / "wake_eval_fr.txt"

TRAIN_VOICES: list[tuple[str, int | None]] = (
    [("fr_FR-siwis-medium", None), ("fr_FR-siwis-low", None), ("fr_FR-gilles-low", None)]
    + [("fr_FR-upmc-medium", 0), ("fr_FR-upmc-medium", 1)]
    + [("fr_FR-mls-medium", i) for i in range(40)]
)
EVAL_VOICES: list[tuple[str, int | None]] = [
    ("fr_FR-tom-medium", None),
    *[("fr_FR-mls-medium", i) for i in (100, 105, 110, 115, 120)],
]


def slug(phrase: str) -> str:
    folded = unicodedata.normalize("NFD", phrase.lower())
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_")


# --- synthese ---------------------------------------------------------------


class Synth:
    """Piper avec cache disque (models/wake_train/cache)."""

    def __init__(self, cache: Path) -> None:
        self._cache = cache
        self._cache.mkdir(parents=True, exist_ok=True)
        self._voices: dict[str, object] = {}

    def __call__(
        self, voice: str, speaker: int | None, text: str, length_scale: float, seed: int
    ) -> np.ndarray:
        key = hashlib.sha1(f"{voice}|{speaker}|{text}|{length_scale:.3f}|{seed}".encode()).hexdigest()
        path = self._cache / f"{key}.npy"
        if path.exists():
            return np.load(path)
        from piper import PiperVoice, SynthesisConfig
        from scipy.signal import resample_poly

        if voice not in self._voices:
            self._voices[voice] = PiperVoice.load(PIPER_DIR / f"{voice}.onnx")
        rng = random.Random(seed)
        cfg = SynthesisConfig(
            speaker_id=speaker,
            length_scale=length_scale,
            noise_scale=rng.uniform(0.5, 0.9),
            noise_w_scale=rng.uniform(0.6, 1.0),
        )
        chunks = list(self._voices[voice].synthesize(text, syn_config=cfg))
        audio = np.concatenate([c.audio_int16_array for c in chunks]).astype(np.float32)
        src = chunks[0].sample_rate
        if src != RATE:
            g = int(np.gcd(src, RATE))
            audio = resample_poly(audio, RATE // g, src // g)
        out = np.clip(audio, -32768, 32767).astype(np.int16)
        np.save(path, out)
        return out


def trim(audio: np.ndarray, margin_ms: int = 40) -> np.ndarray:
    """Retire le silence de tete et de queue (energie < 2 % du pic)."""
    a = np.abs(audio.astype(np.float32))
    if a.max() == 0:
        return audio
    idx = np.nonzero(a > 0.02 * a.max())[0]
    m = RATE * margin_ms // 1000
    return audio[max(0, idx[0] - m) : idx[-1] + m]


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getnchannels() != 1:
            data = data.reshape(-1, w.getnchannels())[:, 0]
        rate = w.getframerate()
    if rate != RATE:
        from scipy.signal import resample_poly

        g = int(np.gcd(rate, RATE))
        data = np.clip(resample_poly(data.astype(np.float32), RATE // g, rate // g), -32768, 32767).astype(
            np.int16
        )
    return data


# --- augmentation -----------------------------------------------------------


def colored_noise(n: int, kind: str, rng: np.random.Generator) -> np.ndarray:
    if kind == "hum":
        t = np.arange(n) / RATE
        f0 = rng.choice([50.0, 100.0, 120.0])
        x = sum(np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6.28)) / k for k in (1, 2, 3, 5))
        return x + 0.1 * rng.standard_normal(n)
    white = rng.standard_normal(n)
    if kind == "white":
        return white
    spec = np.fft.rfft(white)
    f = np.maximum(np.arange(len(spec)), 1).astype(np.float64)
    spec /= np.sqrt(f) if kind == "pink" else f  # brown : 1/f
    return np.fft.irfft(spec, n)


def mix_snr(signal: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    ps = float(np.mean(signal**2)) + 1e-9
    pn = float(np.mean(noise**2)) + 1e-9
    return signal + noise * np.sqrt(ps / (pn * 10 ** (snr_db / 10)))


def reverb(x: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    rt60 = rng.uniform(0.1, 0.5)
    n = int(rt60 * RATE)
    ir = rng.standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)
    ir[0] = 1.0
    ir /= np.sqrt(np.sum(ir**2))
    from scipy.signal import fftconvolve

    return fftconvolve(x, ir)[: len(x)]


def change_speed(x: np.ndarray, factor: float) -> np.ndarray:
    n = max(1, int(len(x) / factor))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)


def augment(
    x: np.ndarray, rng: np.random.Generator, babble_pool: list[np.ndarray], strength: float = 1.0
) -> np.ndarray:
    """x : float32 d'une scene complete (parole + silences). Renvoie du int16."""
    x = x.astype(np.float64)
    if rng.random() < 0.4 * strength:
        x = reverb(x, rng)
    x *= 10 ** (rng.uniform(-14, -1) / 20)
    r = rng.random()
    if r < 0.75 * strength:
        kind = rng.choice(["white", "pink", "brown", "hum"])
        x = mix_snr(x, colored_noise(len(x), kind, rng), rng.uniform(3, 30))
    if babble_pool and rng.random() < 0.5 * strength:
        bg = np.zeros(len(x))
        for _ in range(rng.integers(1, 4)):
            clip = babble_pool[rng.integers(len(babble_pool))].astype(np.float64)
            start = rng.integers(0, max(1, len(x)))
            seg = np.resize(np.roll(clip, start), len(x))
            bg += seg
        x = mix_snr(x, bg, rng.uniform(6, 25))
    peak = np.abs(x).max()
    if peak > 32000:
        x *= 32000 / peak
    return x.astype(np.int16)


# --- caracteristiques en flux ----------------------------------------------


class Extractor:
    """Embeddings openWakeWord calcules trame par trame, comme a l'execution."""

    def __init__(self) -> None:
        from openwakeword.utils import AudioFeatures

        self._af = AudioFeatures()
        self._initial = self._af.feature_buffer.copy()

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        """(n_trames, WINDOW, 96) : une entree de classifieur par trame de 80 ms."""
        from collections import deque

        af = self._af
        af.raw_data_buffer = deque(maxlen=RATE * 10)
        af.melspectrogram_buffer = np.ones((76, 32))
        af.accumulated_samples = 0
        af.feature_buffer = self._initial.copy()
        out = []
        for i in range(0, len(audio) - CHUNK + 1, CHUNK):
            af(audio[i : i + CHUNK])
            out.append(af.get_features(WINDOW)[0])
        return np.stack(out)


def frame_labels(n_frames: int, phrase_end: int | None) -> tuple[np.ndarray, np.ndarray]:
    """Etiquettes et poids par trame. Positif : la trame qui complete la phrase et les 2 suivantes."""
    y = np.zeros(n_frames, dtype=np.float32)
    w = np.ones(n_frames, dtype=np.float32)
    if phrase_end is not None:
        te = -(-phrase_end // CHUNK)  # trame qui contient la fin de la phrase
        y[te : te + 3] = 1.0
        for t in (te - 2, te - 1, te + 3, te + 4, te + 5):  # zone ambigue : ignoree
            if 0 <= t < n_frames:
                w[t] = 0.0
    return y, w


# --- jeu de donnees ---------------------------------------------------------


def build_dataset(phrase: str, recordings: Path | None, work: Path, seed: int):
    rng = np.random.default_rng(seed)
    pyrng = random.Random(seed)
    synth = Synth(work / "cache")
    ext = Extractor()
    words = phrase.split()
    sentences = [s.strip() for s in NEGATIVES.read_text(encoding="utf-8").splitlines() if s.strip()]

    # --- parole negative (aussi reservoir de murmure de fond)
    neg_audio: list[np.ndarray] = []
    for i, text in enumerate(sentences):
        for voice, spk in pyrng.sample(TRAIN_VOICES, 4):
            neg_audio.append(trim(synth(voice, spk, text, pyrng.choice([0.9, 1.0, 1.15]), seed + i)))
    adversarial: list[np.ndarray] = []
    parts = {" ".join(words[i:j]) for i in range(len(words)) for j in range(i + 1, len(words) + 1)}
    parts.discard(phrase)
    for text in sorted(parts):
        for k, (voice, spk) in enumerate(TRAIN_VOICES):
            for ls in (0.9, 1.1):
                adversarial.append(trim(synth(voice, spk, text, ls, seed + 7 * k)))
    print(f"negatifs : {len(neg_audio)} phrases, {len(adversarial)} sous-phrases", flush=True)

    # --- positifs
    pos_audio: list[np.ndarray] = []
    texts = [phrase, phrase + " !", phrase.capitalize() + "."]
    for k, (voice, spk) in enumerate(TRAIN_VOICES):
        for text in texts:
            for ls in (0.9, 1.05, 1.2):
                pos_audio.append(trim(synth(voice, spk, text, ls, seed + 13 * k)))
    n_real = 0
    if recordings is not None:
        for path in sorted(recordings.glob("*.wav")):
            rec = trim(read_wav(path))
            pos_audio += [rec] * 10  # enregistrements reels : surponderes
            n_real += 1
    print(f"positifs : {len(pos_audio)} bases ({n_real} enregistrements reels)", flush=True)

    def scene_of(speech: np.ndarray, is_pos: bool, strength: float = 1.0):
        lead = np.zeros(int(rng.uniform(0.3, 1.0) * RATE))
        tail = np.zeros(int(rng.uniform(0.4, 1.0) * RATE))
        sp = change_speed(speech.astype(np.float64), rng.uniform(0.88, 1.12))
        scene = augment(np.concatenate([lead, sp, tail]), rng, neg_audio, strength)
        return scene, (len(lead) + len(sp) if is_pos else None)

    def noise_scenes():
        for i in range(80):
            n = int(rng.uniform(2, 5) * RATE)
            if i % 4 == 0:
                yield np.zeros(n, dtype=np.int16), None
            else:
                yield augment(rng.standard_normal(n) * 30, rng, neg_audio, 1.0), None

    stages = {
        "pos": lambda: (scene_of(b, True) for b in pos_audio for _ in range(5)),
        "neg": lambda: (scene_of(b, False) for b in neg_audio for _ in range(2)),
        "adv": lambda: (scene_of(b, False) for b in adversarial for _ in range(2)),
        "noise": noise_scenes,
    }
    X, Y, W = [], [], []
    for name, scenes in stages.items():
        # chaque etape est mise en cache : une execution interrompue reprend ici
        part = work / f"stage_{slug(phrase)}_{seed}_{name}.npz"
        if part.exists() and recordings is None:
            d = np.load(part)
            sx, sy, sw = d["X"], d["Y"], d["W"]
        else:
            fx, fy, fw = [], [], []
            for scene, phrase_end in scenes():
                feats = ext(scene)
                y, w = frame_labels(len(feats), phrase_end)
                fx.append(feats), fy.append(y), fw.append(w)
            sx, sy, sw = np.concatenate(fx), np.concatenate(fy), np.concatenate(fw)
            if recordings is None:
                np.savez(part, X=sx, Y=sy, W=sw)
        print(f"etape {name} : {len(sy)} fenetres", flush=True)
        X.append(sx), Y.append(sy), W.append(sw)
    return np.concatenate(X), np.concatenate(Y), np.concatenate(W)


# --- modele -----------------------------------------------------------------


def build_net():
    import torch.nn as nn

    return nn.Sequential(
        nn.Flatten(),
        nn.Linear(WINDOW * 96, 128),
        nn.LayerNorm(128),
        nn.ReLU(),
        nn.Dropout(0.1),
        nn.Linear(128, 128),
        nn.LayerNorm(128),
        nn.ReLU(),
        nn.Linear(128, 1),
        nn.Sigmoid(),
    )


def fit(X: np.ndarray, Y: np.ndarray, W: np.ndarray, epochs: int, seed: int):
    import torch

    torch.manual_seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    keep = W > 0
    X, Y = X[keep], Y[keep]
    n_pos = int(Y.sum())
    print(f"fenetres : {len(Y)} ({n_pos} positives) sur {device}", flush=True)
    perm = np.random.default_rng(seed).permutation(len(Y))
    n_val = len(Y) // 10
    val, tr = perm[:n_val], perm[n_val:]
    xt = torch.tensor(X, dtype=torch.float32, device=device)
    yt = torch.tensor(Y, dtype=torch.float32, device=device)[:, None]
    net = build_net().to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    # Les faux reveils coutent plus que les oublis : poids x3 sur les negatifs.
    weights = torch.where(yt > 0.5, 1.0, 3.0)
    bce = torch.nn.BCELoss(reduction="none")
    for epoch in range(epochs):
        if epoch == epochs // 2:  # fouille des negatifs difficiles : x5 sur ceux a > 0.1
            net.eval()
            with torch.no_grad():
                p = net(xt)
            hard = (p > 0.1) & (yt < 0.5)
            print(f"negatifs difficiles : {int(hard.sum())}", flush=True)
            weights = torch.where(hard, 15.0, weights)
        net.train()
        order = torch.tensor(np.random.default_rng(seed + epoch).permutation(tr), device=device)
        for i in range(0, len(order), 256):
            idx = order[i : i + 256]
            loss = (bce(net(xt[idx]), yt[idx]) * weights[idx]).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        if epoch % 5 == 4 or epoch == epochs - 1:
            net.eval()
            with torch.no_grad():
                p = net(xt[val])
            pred = (p > 0.5).float()
            yv = yt[val]
            tp = float(((pred == 1) & (yv == 1)).sum() / max(1, (yv == 1).sum()))
            fp = float(((pred == 1) & (yv == 0)).sum() / max(1, (yv == 0).sum()))
            print(f"epoch {epoch + 1}: val rappel {tp:.3f}, faux positifs/fenetre {fp:.4f}", flush=True)
    return net.cpu().eval()


def export(net, path: Path) -> None:
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        net,
        torch.zeros(1, WINDOW, 96),
        str(path),
        input_names=["x"],
        output_names=["score"],
        opset_version=17,
        dynamo=False,
    )


# --- evaluation (chemin d'execution reel) -----------------------------------


def count_wakes(model_path: Path, audio: np.ndarray, threshold: float) -> int:
    from drvocal.audio.wake import WakeDetector

    detector = WakeDetector([model_path], threshold)
    pad = np.zeros(CHUNK * 12, dtype=np.int16)
    audio = np.concatenate([pad, audio, pad])
    return sum(
        detector.process(audio[i : i + CHUNK]) for i in range(0, len(audio) - CHUNK + 1, CHUNK)
    )


def evaluate(phrase: str, model_path: Path, work: Path, threshold: float, seed: int) -> dict:
    synth = Synth(work / "cache")
    rng = np.random.default_rng(seed + 1)
    # positifs : voix hors entrainement, 3 textes x 2 debits, + variantes bruitees
    clean, noisy = [], []
    for k, (voice, spk) in enumerate(EVAL_VOICES):
        for text in (phrase, phrase.capitalize() + " !"):
            for ls in (0.95, 1.15):
                clip = trim(synth(voice, spk, text, ls, 9000 + k))
                clean.append(clip)
                noisy.append(
                    augment(
                        np.concatenate([np.zeros(RATE // 2), clip.astype(np.float64), np.zeros(RATE // 2)]),
                        rng, [], 1.0,
                    )
                )
    tp_clean = sum(count_wakes(model_path, c, threshold) >= 1 for c in clean)
    tp_noisy = sum(count_wakes(model_path, c, threshold) >= 1 for c in noisy)
    # negatifs : phrases de test, mots isoles, hors entrainement
    sentences = [s.strip() for s in EVAL_SENTENCES.read_text(encoding="utf-8").splitlines() if s.strip()]
    words = phrase.split()
    sentences += sorted({" ".join(words[i:j]) for i in range(len(words)) for j in range(i + 1, len(words) + 1)} - {phrase})
    false_wakes, seconds = 0, 0.0
    for k, (voice, spk) in enumerate(EVAL_VOICES):
        for text in sentences:
            clip = trim(synth(voice, spk, text, 1.0, 9500 + k))
            seconds += len(clip) / RATE
            false_wakes += count_wakes(model_path, clip, threshold)
    return {
        "threshold": threshold,
        "tp_clean": f"{tp_clean}/{len(clean)}",
        "tp_noisy": f"{tp_noisy}/{len(noisy)}",
        "false_wakes": false_wakes,
        "negative_seconds": round(seconds, 1),
        "false_wakes_per_hour": round(false_wakes / seconds * 3600, 1) if seconds else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phrase")
    ap.add_argument("--recordings", type=Path, help="dossier de WAV reels de la phrase")
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "wake")
    ap.add_argument("--work", type=Path, default=ROOT / "models" / "wake_train")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--eval-only", action="store_true", help="n'entraine pas, evalue le modele existant")
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()

    phrase = args.phrase.strip().lower()
    model_path = args.out / f"{slug(phrase)}.onnx"
    if not args.eval_only:
        X, Y, W = build_dataset(phrase, args.recordings, args.work, args.seed)
        net = fit(X, Y, W, args.epochs, args.seed)
        export(net, model_path)
        print(f"modele : {model_path}")
    report = {
        str(t): evaluate(phrase, model_path, args.work, t, args.seed)
        for t in sorted({args.threshold, 0.7, 0.9})
    }
    print(json.dumps(report, indent=2))
    model_path.with_suffix(".json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
