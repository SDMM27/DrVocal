import numpy as np
import pytest

from drvocal.audio.push_to_talk import KeyTrigger, resolve_key

FRAME = np.zeros(1280, dtype=np.int16)


def test_resolve_key():
    assert resolve_key("mouse5") == 0x06
    assert resolve_key("mouse4") == 0x05
    assert resolve_key("mouse3") == 0x04
    assert resolve_key("F9") == 0x78
    assert resolve_key("v") == ord("V")
    assert resolve_key("mouse99") is None


def test_unknown_key_raises():
    with pytest.raises(ValueError):
        KeyTrigger("mouse99", is_down=lambda vk: False)


def test_key_trigger_fires_once_per_press():
    state = {"down": False}
    seen = []
    trigger = KeyTrigger("mouse5", is_down=lambda vk: seen.append(vk) or state["down"])
    assert trigger.process(FRAME) is False
    state["down"] = True
    assert [trigger.process(FRAME) for _ in range(3)] == [True, False, False]
    assert trigger.held() is True
    state["down"] = False
    assert trigger.process(FRAME) is False and trigger.held() is False
    state["down"] = True
    assert trigger.process(FRAME) is True
    assert set(seen) == {0x06}
