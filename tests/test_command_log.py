import json
import wave
from datetime import datetime, timedelta

import numpy as np

from drvocal.command_log import CommandLog
from drvocal.intent import Intent


def clock():
    state = {"t": datetime(2026, 11, 4, 12, 0, 0)}

    def now():
        state["t"] += timedelta(seconds=1)
        return state["t"]

    return now


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


AUDIO = np.arange(1600, dtype=np.int16)


def test_line_is_written_and_readable_with_accents(tmp_path):
    log = CommandLog(tmp_path, now=clock())
    log.record("mets Beyoncé", Intent("spotify.play", {"query": "Beyoncé"}), True, AUDIO, 900, 120)
    [row] = lines(tmp_path / "commands.jsonl")
    assert row == {"ts": "2026-11-04T12:00:01", "text": "mets Beyoncé", "action": "spotify.play",
                   "args": {"query": "Beyoncé"}, "ok": True, "stt_ms": 900, "action_ms": 120, "wav": None, "reply": None}
    assert "Beyoncé" in (tmp_path / "commands.jsonl").read_text(encoding="utf-8")


def test_wav_only_written_on_failure(tmp_path):
    log = CommandLog(tmp_path, now=clock())
    log.record("ok", Intent("a", {}), True, AUDIO, 1, 1)
    assert not (tmp_path / "failures").exists()
    log.record("rate", Intent("a", {}), False, AUDIO, 1, 1)
    log.record("inconnu", None, None, AUDIO, 1, None)
    rows = lines(tmp_path / "commands.jsonl")
    assert rows[0]["wav"] is None and rows[1]["wav"] and rows[2]["wav"] and rows[2]["action"] is None
    with wave.open(str(tmp_path / "failures" / rows[1]["wav"]), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 1600)


def test_old_wavs_are_purged(tmp_path):
    log = CommandLog(tmp_path, keep_wavs=3, now=clock())
    for i in range(6):
        log.record(str(i), None, None, AUDIO, 1, None)
    rows = lines(tmp_path / "commands.jsonl")
    kept = sorted(p.name for p in (tmp_path / "failures").glob("*.wav"))
    assert kept == [r["wav"] for r in rows[-3:]]


def test_rotation_when_too_big(tmp_path):
    log = CommandLog(tmp_path, max_bytes=100, now=clock())
    for _ in range(3):
        log.record("x" * 80, None, None, None, None, None)
    assert len(lines(tmp_path / "commands.jsonl")) == 1
    assert len(lines(tmp_path / "commands.1.jsonl")) == 1  # l'ancien .1 est ecrase


def test_os_error_is_swallowed(tmp_path):
    blocker = tmp_path / "pas_un_dossier"
    blocker.write_text("x")
    CommandLog(blocker / "sub", now=clock()).record("a", None, None, AUDIO, 1, None)


def test_reply_is_written(tmp_path):
    log = CommandLog(tmp_path, now=clock())
    log.record("mets X", Intent("spotify.play", {}), False, None, 1, 2, reply="Je n'ai pas trouvé X")
    [row] = lines(tmp_path / "commands.jsonl")
    assert row["reply"] == "Je n'ai pas trouvé X"


def test_record_event_writes_a_line(tmp_path):
    log = CommandLog(tmp_path, now=clock())
    log.record_event("wake_rejected", score=0.91)
    log.record_event("no_speech")
    assert lines(tmp_path / "commands.jsonl") == [
        {"ts": "2026-11-04T12:00:01", "event": "wake_rejected", "score": 0.91},
        {"ts": "2026-11-04T12:00:02", "event": "no_speech"}]


def test_record_event_rotates_like_record(tmp_path):
    log = CommandLog(tmp_path, max_bytes=100, now=clock())
    for _ in range(4):
        log.record_event("no_speech")
    assert (tmp_path / "commands.1.jsonl").exists()
    assert len(lines(tmp_path / "commands.jsonl")) < 4


def test_record_event_never_raises_on_oserror(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    CommandLog(blocker / "sub").record_event("no_speech")  # le dossier ne peut pas etre cree
