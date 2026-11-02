import numpy as np

from drvocal.audio.vad import FRAME_SAMPLES, capture_utterance


def energy_is_speech(frame: np.ndarray) -> bool:
    return float(np.abs(frame.astype(np.float32)).mean()) > 500


def loud() -> np.ndarray:
    return (np.sin(np.linspace(0, 200, FRAME_SAMPLES)) * 8000).astype(np.int16)


def quiet() -> np.ndarray:
    return np.zeros(FRAME_SAMPLES, dtype=np.int16)


async def agen(frames):
    for f in frames:
        yield f


async def test_capture_returns_none_when_no_speech():
    frames = agen([quiet()] * 50)
    result = await capture_utterance(
        frames, silence_ms=400, no_speech_timeout_ms=800, is_speech=energy_is_speech
    )
    assert result is None


async def test_capture_stops_after_silence():
    frames = agen([quiet()] * 2 + [loud()] * 5 + [quiet()] * 20)
    result = await capture_utterance(
        frames, silence_ms=400, no_speech_timeout_ms=2000, is_speech=energy_is_speech
    )
    assert result is not None
    assert result.dtype == np.int16
    # 5 trames de parole + 5 trames de silence final (400 ms) au plus, pas les 20
    assert 5 * FRAME_SAMPLES <= len(result) <= 14 * FRAME_SAMPLES


async def test_capture_caps_at_max_ms():
    frames = agen([loud()] * 100)
    result = await capture_utterance(
        frames, silence_ms=400, no_speech_timeout_ms=2000, max_ms=800,
        is_speech=energy_is_speech,
    )
    assert result is not None
    assert len(result) == 10 * FRAME_SAMPLES


async def test_capture_returns_none_when_stream_ends_without_speech():
    result = await capture_utterance(
        agen([quiet()] * 3), silence_ms=400, no_speech_timeout_ms=5000,
        is_speech=energy_is_speech,
    )
    assert result is None


def test_silero_detects_speech_fixture_and_rejects_silence():
    import wave
    from pathlib import Path

    from drvocal.audio.vad import SileroVAD

    path = Path(__file__).parent / "fixtures" / "mets_daft_punk.wav"
    with wave.open(str(path), "rb") as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    vad = SileroVAD()
    flags = [
        vad(audio[i : i + FRAME_SAMPLES])
        for i in range(0, len(audio) - FRAME_SAMPLES, FRAME_SAMPLES)
    ]
    assert any(flags)
    vad.reset()
    assert not any(vad(quiet()) for _ in range(10))
