import json
import subprocess

import pytest

from drvocal.actions import Catalogue
from drvocal.intent import Intent
from drvocal.journal import launch_journal, read_entries, register_journal, wav_path


def write(path, rows):
    path.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows), encoding="utf-8")


def cmd(n, ok=True, **extra):
    return {"ts": f"2026-11-04T12:00:{n:02d}", "text": f"t{n}", "action": "spotify.pause", "args": {},
            "ok": ok, **extra}


def test_missing_files_give_empty_list(tmp_path):
    assert read_entries(tmp_path) == []


def test_newest_first_across_both_files(tmp_path):
    write(tmp_path / "commands.1.jsonl", [cmd(1), cmd(2)])
    write(tmp_path / "commands.jsonl", [cmd(3), cmd(4)])
    assert [e["text"] for e in read_entries(tmp_path)] == ["t4", "t3", "t2", "t1"]


def test_limit_keeps_the_most_recent(tmp_path):
    write(tmp_path / "commands.1.jsonl", [cmd(1), cmd(2)])
    write(tmp_path / "commands.jsonl", [cmd(3), cmd(4)])
    assert [e["text"] for e in read_entries(tmp_path, limit=3)] == ["t4", "t3", "t2"]


def test_invalid_lines_are_ignored(tmp_path):
    write(tmp_path / "commands.jsonl", [cmd(1), "{pas du json", "[1, 2]", "", cmd(2)])
    assert [e["text"] for e in read_entries(tmp_path)] == ["t2", "t1"]


def test_kinds(tmp_path):
    write(tmp_path / "commands.jsonl", [
        cmd(1, ok=True),
        cmd(2, ok=False),
        cmd(3, ok=None, action=None),
        {"ts": "2026-11-04T12:00:04", "event": "wake_rejected", "score": 0.91},
        {"ts": "2026-11-04T12:00:05", "event": "no_speech"},
        {"ts": "2026-11-04T12:00:06", "event": "inconnu"},
    ])
    kinds = [e["kind"] for e in read_entries(tmp_path)]
    assert kinds == ["no_speech", "wake_rejected", "not_understood", "failed", "ok"]


def test_old_lines_without_reply_stay_readable(tmp_path):
    write(tmp_path / "commands.jsonl", [cmd(1, wav=None)])
    [entry] = read_entries(tmp_path)
    assert entry["kind"] == "ok" and "reply" not in entry


def test_wav_path_accepts_existing_failure(tmp_path):
    (tmp_path / "failures").mkdir()
    wav = tmp_path / "failures" / "2026-11-04_12-00-01-000000.wav"
    wav.write_bytes(b"RIFF")
    assert wav_path(tmp_path, wav.name) == wav


@pytest.mark.parametrize("name", ["..\\x.wav", "../x.wav", "a/b.wav", "a\\b.wav", "x.txt", "", "x.wav\n", None, 3])
def test_wav_path_refuses_traversal_and_bad_names(tmp_path, name):
    (tmp_path / "failures").mkdir()
    (tmp_path / "x.wav").write_bytes(b"RIFF")
    assert wav_path(tmp_path, name) is None


def test_wav_path_refuses_missing_file(tmp_path):
    (tmp_path / "failures").mkdir()
    assert wav_path(tmp_path, "absent.wav") is None


async def test_open_journal_handler_launches():
    launched = []
    catalogue = Catalogue()
    register_journal(catalogue, lambda: launched.append(1))
    outcome = await catalogue.run(Intent("journal.open", {}))
    assert outcome.ok and launched == [1]


async def test_open_journal_handler_fails_on_oserror():
    def boom():
        raise OSError("introuvable")

    catalogue = Catalogue()
    register_journal(catalogue, boom)
    assert (await catalogue.run(Intent("journal.open", {}))).ok is False


def test_launch_journal_spawns_detached_pythonw(monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: seen.update(args=args, kw=kw))
    launch_journal()
    assert seen["args"][1:] == ["-m", "drvocal.journal"]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # pyright: ignore[reportAttributeAccessIssue]
    assert seen["kw"]["creationflags"] == flags
