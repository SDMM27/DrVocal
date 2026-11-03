import io
import wave

from drvocal.audio.sounds import SOUND_NAMES, SoundPlayer, default_sounds


def duration_ms(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() * 1000 / w.getframerate()


def test_default_sounds_are_short_valid_wavs():
    sounds = default_sounds()
    assert set(sounds) == set(SOUND_NAMES)
    for data in sounds.values():
        assert 0 < duration_ms(data) < 200


def test_play_sends_named_sound():
    played = []
    SoundPlayer({}, play=played.append).play("wake")
    assert played == [default_sounds()["wake"]]


def test_sound_override_is_used(tmp_path):
    custom = default_sounds()["done"]
    path = tmp_path / "w.wav"
    path.write_bytes(custom)
    played = []
    SoundPlayer({"wake": path}, play=played.append).play("wake")
    assert played == [custom]


def test_sound_override_unreadable_falls_back(tmp_path, caplog):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"pas un wav")
    played = []
    player = SoundPlayer({"wake": bad, "success": tmp_path / "absent.wav"}, play=played.append)
    player.play("wake")
    player.play("success")
    assert played == [default_sounds()["wake"], default_sounds()["success"]]
    assert "illisible" in caplog.text


def test_play_never_raises():
    def boom(_data):
        raise OSError("pas de carte son")

    player = SoundPlayer({}, play=boom)
    player.play("wake")
    player.play("inconnu")
