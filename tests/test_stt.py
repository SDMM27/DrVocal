import unicodedata
import wave
from pathlib import Path

import numpy as np
import pytest

from drvocal.audio.stt import Transcriber

FIXTURES = Path(__file__).parent / "fixtures"


def load_wav(name: str) -> np.ndarray:
    with wave.open(str(FIXTURES / name), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def test_model_is_not_loaded_until_first_use():
    t = Transcriber("small", "cpu")
    assert not t.loaded


def test_unload_releases_model():
    t = Transcriber("small", "cpu")
    t._model = object()
    assert t.loaded
    t.unload()
    assert not t.loaded


def test_preload_loads_once_even_when_racing_a_transcription(monkeypatch):
    import threading
    import time

    import faster_whisper

    built = []

    class FakeModel:
        def __init__(self, *args, **kwargs):
            time.sleep(0.05)
            built.append(self)

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    t = Transcriber("small", "cpu")
    threads = [threading.Thread(target=t.preload) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert t.loaded
    assert len(built) == 1


@pytest.mark.slow
def test_transcribes_french_fixture():
    t = Transcriber("small", "cpu")
    text = t.transcribe(load_wav("mets_daft_punk.wav"))
    t.unload()
    assert "daft punk" in normalise(text)
