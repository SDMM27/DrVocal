import importlib.util
import wave
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location(
    "record_voice", Path(__file__).parent.parent / "tools" / "record_voice.py"
)
record_voice = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(record_voice)


def test_silent_take_is_rejected():
    assert record_voice.take_issue(np.zeros(1000, dtype=np.int16)) == "trop faible"


def test_clipped_take_is_rejected():
    assert record_voice.take_issue(np.full(1000, -32768, dtype=np.int16)) == "saturee"


def test_good_take_is_accepted():
    assert record_voice.take_issue(np.full(1000, 8000, dtype=np.int16)) is None


def test_slug():
    assert record_voice.slug("Salut docteur") == "salut_docteur"


def test_wav_is_16k_mono(tmp_path):
    path = tmp_path / "a" / "000.wav"
    record_voice.write_wav(path, np.zeros(1600, dtype=np.int16))
    with wave.open(str(path)) as f:
        assert (f.getframerate(), f.getnchannels(), f.getnframes()) == (16000, 1, 1600)
