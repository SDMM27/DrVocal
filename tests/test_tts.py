import asyncio
import threading

import numpy as np

from drvocal.audio.tts import Speaker

AUDIO = np.zeros(100, dtype=np.int16)


async def test_say_synthesizes_then_plays_off_loop(tmp_path):
    threads = []
    played = []

    def synth(text):
        threads.append(threading.current_thread())
        return AUDIO, 22050

    speaker = Speaker(tmp_path / "v.onnx", synth=synth, play=lambda a, r: played.append((len(a), r)))
    await speaker.say("bonjour")
    assert played == [(100, 22050)]
    assert threads[0] is not threading.main_thread()


async def test_tts_missing_voice_is_silent(tmp_path, caplog):
    played = []
    speaker = Speaker(tmp_path / "absente.onnx", play=lambda a, r: played.append(1))
    await speaker.say("bonjour")
    assert played == []
    assert "absente" in caplog.text


async def test_say_never_raises(tmp_path):
    def boom(_text):
        raise RuntimeError("piper casse")

    await Speaker(tmp_path / "v.onnx", synth=boom, play=lambda a, r: None).say("bonjour")


async def test_one_sentence_at_a_time(tmp_path):
    active = 0
    peak = 0

    def play(a, r):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        threading.Event().wait(0.02)
        active -= 1

    speaker = Speaker(tmp_path / "v.onnx", synth=lambda t: (AUDIO, 1), play=play)
    await asyncio.wait_for(asyncio.gather(speaker.say("a"), speaker.say("b")), 5)
    assert peak == 1
