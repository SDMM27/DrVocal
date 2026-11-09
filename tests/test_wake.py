import math
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from drvocal.audio.mic import FRAME_MS, FRAME_SAMPLES
from drvocal.audio.wake import WakeDetector

FIXTURES = Path(__file__).parent / "fixtures"
WAKE_MODELS = Path(__file__).parent.parent / "models" / "wake"


class FakeModel:
    """Imite openwakeword.Model.predict : un score par trame, scenarise."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = iter(scores)

    def predict(self, frame: np.ndarray) -> dict[str, float]:
        return {"salut_docteur": next(self._scores)}


def silent() -> np.ndarray:
    return np.zeros(FRAME_SAMPLES, dtype=np.int16)


def run(detector: WakeDetector, n: int) -> list[bool]:
    return [detector.process(silent()) for _ in range(n)]


# --- logique du detecteur, modele injecte -------------------------------------


def test_below_threshold_never_wakes():
    d = WakeDetector([], 0.5, model=FakeModel([0.1, 0.4, 0.49]), patience=1)
    assert run(d, 3) == [False, False, False]


def test_wakes_once_at_threshold():
    d = WakeDetector([], 0.5, model=FakeModel([0.1, 0.5, 0.1]), patience=1)
    assert run(d, 3) == [False, True, False]


def test_one_phrase_does_not_wake_twice():
    # Le score reste haut sur plusieurs trames : un seul reveil.
    d = WakeDetector([], 0.5, model=FakeModel([0.9, 0.95, 0.9, 0.8, 0.1]), cooldown_s=2.0, patience=1)
    assert run(d, 5) == [True, False, False, False, False]


def test_wakes_again_after_cooldown():
    cooldown_frames = math.ceil(1000 / FRAME_MS)  # 1 s
    scores = [0.9] * (cooldown_frames + 3)
    d = WakeDetector([], 0.5, model=FakeModel(scores), cooldown_s=1.0, patience=1)
    flags = run(d, len(scores))
    assert flags[0] is True
    assert not any(flags[1 : cooldown_frames + 1])
    assert flags[cooldown_frames + 1] is True
    assert flags[cooldown_frames + 2] is False


def test_takes_best_score_over_models():
    class Two:
        def predict(self, frame):
            return {"a": 0.1, "b": 0.8}

    assert WakeDetector([], 0.5, model=Two(), patience=1).process(silent()) is True


def test_isolated_spike_does_not_wake():
    d = WakeDetector([], 0.5, model=FakeModel([0.1, 0.9, 0.1, 0.95, 0.2]))
    assert run(d, 5) == [False] * 5


def test_two_frames_above_threshold_wake():
    d = WakeDetector([], 0.5, model=FakeModel([0.1, 0.6, 0.7, 0.1]))
    assert run(d, 4) == [False, False, True, False]


def test_confirm_rejects_wake_without_speech():
    seen = []
    d = WakeDetector([], 0.5, model=FakeModel([0.9] * 3), confirm=lambda fr: seen.append(len(fr)) or False)
    assert run(d, 3) == [False, False, False]
    assert seen == [2]  # les trames recentes, une seule verification (delai de reprise)


def test_rejected_wake_calls_on_rejected_with_score():
    scores = []
    d = WakeDetector([], 0.5, model=FakeModel([0.9, 0.9]), confirm=lambda fr: False, on_rejected=scores.append)
    assert run(d, 2) == [False, False]
    assert scores == [0.9]


def test_accepted_wake_does_not_call_on_rejected():
    scores = []
    d = WakeDetector([], 0.5, model=FakeModel([0.9, 0.9]), confirm=lambda fr: True, on_rejected=scores.append)
    assert run(d, 2) == [False, True]
    assert scores == []


def test_failing_on_rejected_is_swallowed():
    def boom(score):
        raise RuntimeError("disque plein")

    d = WakeDetector([], 0.5, model=FakeModel([0.9, 0.9]), confirm=lambda fr: False, on_rejected=boom)
    assert run(d, 2) == [False, False]


def test_confirm_accepts_wake_with_speech():
    d = WakeDetector([], 0.5, model=FakeModel([0.9, 0.9]), confirm=lambda fr: True)
    assert run(d, 2) == [False, True]


def test_confirm_window_is_bounded():
    seen = []
    scores = [0.1] * 30 + [0.9, 0.9]
    d = WakeDetector([], 0.5, model=FakeModel(scores), confirm=lambda fr: seen.append(len(fr)) or True,
                     confirm_window_s=0.8)
    run(d, len(scores))
    assert seen == [10]


def test_no_model_loaded_at_construction():
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from drvocal.audio.wake import WakeDetector\n"
        "WakeDetector([Path('x.onnx')], 0.5)\n"
        "assert 'onnxruntime' not in sys.modules\n"
        "assert 'openwakeword' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


# --- vrais modeles (voix de synthese hors entrainement) -----------------------


def load_wav(name: str) -> np.ndarray:
    with wave.open(str(FIXTURES / name), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def count_wakes(audio: np.ndarray) -> int:
    paths = sorted(WAKE_MODELS.glob("*.onnx"))
    detector = WakeDetector(paths, 0.5)
    pad = np.zeros(FRAME_SAMPLES * 12, dtype=np.int16)
    audio = np.concatenate([pad, audio, pad])
    return sum(
        detector.process(audio[i : i + FRAME_SAMPLES])
        for i in range(0, len(audio) - FRAME_SAMPLES + 1, FRAME_SAMPLES)
    )


needs_models = pytest.mark.skipif(
    not list(WAKE_MODELS.glob("*.onnx")),
    reason="models/wake/ absent : lancer `uv run python tools/train_wake.py \"salut doc vocal\"`",
)


@pytest.mark.slow
@needs_models
@pytest.mark.xfail(
    reason="C4 : le modele entraine sur une seule vraie voix ne reconnait plus la voix de synthese "
    "de la fixture (docs/mesures.md). A revoir avec le moteur de reveil universel (L10).",
    strict=False,
)
def test_detects_wake_fixture():
    assert count_wakes(load_wav("salut_doc_vocal.wav")) == 1


@pytest.mark.slow
@needs_models
def test_ignores_conversation_fixture():
    assert count_wakes(load_wav("conversation.wav")) == 0


@pytest.mark.slow
@needs_models
def test_docteur_alone_does_not_wake():
    assert count_wakes(load_wav("docteur_seul.wav")) == 0


@pytest.mark.slow
@needs_models
def test_old_phrase_does_not_wake():
    assert count_wakes(load_wav("salut_docteur.wav")) == 0
