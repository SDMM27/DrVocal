import importlib.util
import sys
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location(
    "eval_voice", Path(__file__).parent.parent / "tools" / "eval_voice.py"
)
eval_voice = importlib.util.module_from_spec(_spec)
sys.modules["eval_voice"] = eval_voice
_spec.loader.exec_module(eval_voice)

CHUNK = eval_voice.CHUNK
LEAD = eval_voice.LEAD_FRAMES


class FakeModel:
    """Imite openwakeword.Model.predict : scores par trame, scenarises par modele."""

    def __init__(self, scripts: dict[str, dict[int, float]]) -> None:
        self._scripts = scripts
        self._i = -1

    def predict(self, frame: np.ndarray) -> dict[str, float]:
        self._i += 1
        return {name: s.get(self._i, 0.0) for name, s in self._scripts.items()}


def clip_of(audio_frames: int, scripts: dict[str, dict[int, float]], positive: bool):
    audio = np.zeros(audio_frames * CHUNK, dtype=np.int16)
    return eval_voice.score_clip(FakeModel(scripts), audio, "x", positive)


def test_clip_range_covers_only_the_file():
    clip = clip_of(5, {"a": {}}, True)
    assert (clip.start, clip.stop) == (LEAD, LEAD + 5)
    assert len(clip.scores) == LEAD + 5 + eval_voice.TAIL_FRAMES


def test_short_audio_is_padded_to_whole_frames():
    audio = np.zeros(CHUNK * 2 + 10, dtype=np.int16)
    clip = eval_voice.score_clip(FakeModel({"a": {}}), audio, "x", True)
    assert clip.stop - clip.start == 3


def test_detection_during_file_counts():
    clip = clip_of(5, {"a": {LEAD + 2: 0.8}}, True)
    assert eval_voice.detected(clip, 0.5)
    assert not eval_voice.detected(clip, 0.9)


def test_wake_in_tail_padding_is_not_a_detection():
    clip = clip_of(5, {"a": {LEAD + 5 + 1: 0.99}}, True)
    assert not eval_voice.detected(clip, 0.5)


def test_wake_in_lead_padding_is_not_a_detection():
    clip = clip_of(5, {"a": {2: 0.99}}, True)
    assert not eval_voice.detected(clip, 0.5)


def test_false_wakes_count_everywhere_with_cooldown():
    # 2 pics separes de plus que le delai de reprise (25 trames) = 2 reveils ; 1 pic rapproche est ignore
    scripts = {"a": {LEAD + 1: 0.9, LEAD + 3: 0.9, LEAD + 40: 0.9}}
    clip = clip_of(60, scripts, False)
    assert eval_voice.false_wakes(clip, 0.5) == 2
    assert eval_voice.false_wakes(clip, 0.95) == 0


def test_false_wake_in_tail_padding_still_counts():
    clip = clip_of(5, {"a": {LEAD + 5 + 3: 0.9}}, False)
    assert eval_voice.false_wakes(clip, 0.5) == 1


def test_per_model_only_isolates_cross_firing():
    scripts = {"a": {LEAD + 1: 0.9}, "b": {LEAD + 2: 0.2}}
    clip = clip_of(5, scripts, True)
    assert eval_voice.detected(clip, 0.5)
    assert eval_voice.detected(clip, 0.5, only="a")
    assert not eval_voice.detected(clip, 0.5, only="b")


def test_summarize_tables():
    pos_a = clip_of(5, {"a": {LEAD + 1: 0.9}, "b": {LEAD + 1: 0.6}}, True)
    pos_a.label = "a"
    pos_miss = clip_of(5, {"a": {}, "b": {}}, True)
    pos_miss.label = "a"
    neg = clip_of(5, {"a": {LEAD + 1: 0.6}, "b": {}}, False)
    neg.label = "n1"
    res = eval_voice.summarize([pos_a, pos_miss, neg], [0.5, 0.9])
    assert res[0.5]["detections"]["a"] == (1, 2)
    assert res[0.5]["detections_total"] == (1, 2)
    assert res[0.5]["false_wakes_total"] == (1, 1)  # reveils, nb de clips negatifs
    assert res[0.5]["false_wakes_by_label"]["n1"] == 1
    assert res[0.5]["cross"]["b"]["a"] == (1, 2)  # modele b sur les positifs de a
    assert res[0.5]["false_wakes_by_model"] == {"a": 1, "b": 0}
    assert res[0.9]["detections_total"] == (1, 2)
    assert res[0.9]["false_wakes_total"] == (0, 1)
