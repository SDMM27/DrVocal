import numpy as np

from drvocal.audio.mic import FRAME_SAMPLES, MicStream


class FakeStream:
    def __init__(self, blocks):
        self.blocks = list(blocks)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n):
        if not self.blocks:
            raise OSError("stream ended")
        item = self.blocks.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, False


async def test_mic_yields_80ms_int16_frames():
    block = np.ones((FRAME_SAMPLES, 1), dtype=np.int16)
    mic = MicStream(stream_factory=lambda: FakeStream([block, block]), retry_delay_s=0)
    got = []
    async for frame in mic.frames():
        got.append(frame)
        if len(got) == 2:
            break
    assert got[0].shape == (FRAME_SAMPLES,)
    assert got[0].dtype == np.int16


async def test_mic_reopens_after_device_error():
    block = np.ones((FRAME_SAMPLES, 1), dtype=np.int16)
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("device unavailable")
        if calls["n"] == 2:
            return FakeStream([block, RuntimeError("lost")])  # lost mid-stream
        return FakeStream([block, block])

    mic = MicStream(stream_factory=factory, retry_delay_s=0)
    got = []
    async for frame in mic.frames():
        got.append(frame)
        if len(got) == 3:
            break
    assert len(got) == 3
    assert calls["n"] >= 3
