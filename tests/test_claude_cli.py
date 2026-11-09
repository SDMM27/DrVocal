import asyncio
import json
from pathlib import Path

import pytest

from drvocal import claude_cli
from drvocal.claude_cli import (
    AgentInfo,
    ClaudeCli,
    ClaudeCliError,
    find_claude,
    parse_agents,
    parse_backgrounded,
    session_name,
)

UUID = "915c4b6f-4ca1-4d37-9a28-1c471c66c24b"


def _fake(code=0, out="backgrounded · abc123 · x", exc=None):
    calls = []

    async def run(args, cwd, timeout):
        calls.append((args, cwd, timeout))
        if exc:
            raise exc
        return code, out

    return calls, run


def test_parse_backgrounded_reads_the_short_id():
    out = "Starting background service…\nbackgrounded · 915c4b6f · Essai Dr Vocal\n  claude agents  list"
    assert parse_backgrounded(out) == "915c4b6f"
    assert parse_backgrounded("Workspace not trusted.") is None


def test_parse_backgrounded_without_name_and_after_a_note():
    assert parse_backgrounded("note: resumed\nbackgrounded · 41cb7da2") == "41cb7da2"


def test_parse_agents_keeps_background_sessions_only():
    out = json.dumps([
        {"pid": 1, "cwd": "D:\\x", "kind": "interactive", "sessionId": "a", "status": "idle"},
        {"pid": 2, "id": "915c4b6f", "cwd": "D:\\NasaCode\\DrVocal", "kind": "background",
         "sessionId": UUID, "status": "busy", "state": "working"},
    ])
    assert parse_agents(out) == [AgentInfo("915c4b6f", UUID, "D:\\NasaCode\\DrVocal", "busy", "working")]


def test_parse_agents_state_is_optional():
    out = json.dumps([{"id": "a1", "cwd": "D:\\x", "kind": "background", "sessionId": UUID, "status": "idle"}])
    assert parse_agents(out)[0].state is None


def test_parse_agents_rejects_non_json():
    with pytest.raises(ClaudeCliError):
        parse_agents("warning: update available\n")


def test_parse_agents_skips_a_warning_before_the_array():
    out = "warning: update available\n" + json.dumps(
        [{"id": "a1", "cwd": "D:\\x", "kind": "background", "sessionId": UUID, "status": "idle"}], indent=2)
    assert [a.id for a in parse_agents(out)] == ["a1"]


def test_parse_agents_rejects_a_warning_without_array():
    with pytest.raises(ClaudeCliError):
        parse_agents("[warn] update available\n{}")


def test_parse_agents_coerces_status_and_state_to_text():
    out = json.dumps([{"id": "a1", "kind": "background", "sessionId": UUID, "status": 3, "state": 7}])
    agent = parse_agents(out)[0]
    assert (agent.status, agent.state) == ("3", "7")


def test_parse_agents_rejects_a_non_array():
    with pytest.raises(ClaudeCliError):
        parse_agents('{"a": 1}')


def test_session_name_is_bounded():
    assert session_name("GeoGame", "corriger le bug du score") == "GeoGame – corriger le bug du score"
    name = session_name("GeoGame", "mot " * 40)
    assert len(name) <= 50
    assert name == name.rstrip()
    assert name.endswith("mot")


async def test_launch_passes_the_prompt_as_one_argument():
    calls, run = _fake()
    cli = ClaudeCli("claude", run)
    assert await cli.launch(Path("D:/p"), "P – x", '-rf "quoted" prompt') == "abc123"
    args, cwd, timeout = calls[0]
    assert args[:6] == ["claude", "--bg", "--permission-mode", "auto", "-n", "P – x"]
    assert args[-2:] == ["--", '-rf "quoted" prompt'] and cwd == Path("D:/p") and timeout == 30
    assert "bypassPermissions" not in args


async def test_launch_with_resume():
    calls, run = _fake()
    await ClaudeCli("claude", run).launch(Path("D:/p"), "n", "suite", resume=UUID)
    assert calls[0][0] == ["claude", "--bg", "--resume", UUID, "--", "suite"]


async def test_launch_untrusted_folder_raises_a_helpful_error():
    _, run = _fake(1, "Workspace not trusted. Run `claude` in D:\\p once and accept the trust prompt, then retry.")
    with pytest.raises(ClaudeCliError, match="faire confiance"):
        await ClaudeCli("claude", run).launch(Path("D:/p"), "n", "x")


async def test_launch_nonzero_exit_raises():
    _, run = _fake(1, "boom")
    with pytest.raises(ClaudeCliError):
        await ClaudeCli("claude", run).launch(Path("D:/p"), "n", "x")


async def test_launch_without_id_raises():
    _, run = _fake(0, "nothing useful")
    with pytest.raises(ClaudeCliError):
        await ClaudeCli("claude", run).launch(Path("D:/p"), "n", "x")


async def test_launch_timeout_raises():
    _, run = _fake(exc=TimeoutError())
    with pytest.raises(ClaudeCliError, match="à temps"):
        await ClaudeCli("claude", run).launch(Path("D:/p"), "n", "x")


async def test_agents_runs_agents_json():
    calls, run = _fake(0, "[]")
    assert await ClaudeCli("claude", run).agents() == []
    assert calls[0][0] == ["claude", "agents", "--json"]


async def test_agents_nonzero_exit_raises():
    _, run = _fake(1, "boom")
    with pytest.raises(ClaudeCliError):
        await ClaudeCli("claude", run).agents()


async def test_stop_runs_stop():
    calls, run = _fake(0, "")
    await ClaudeCli("claude", run).stop("abc123")
    assert calls[0][0] == ["claude", "stop", "abc123"]


async def test_stop_nonzero_exit_raises():
    _, run = _fake(1, "boom")
    with pytest.raises(ClaudeCliError):
        await ClaudeCli("claude", run).stop("abc123")


def test_open_import_starts_the_resume_link(monkeypatch):
    opened = []
    monkeypatch.setattr(claude_cli.os, "startfile", opened.append, raising=False)
    ClaudeCli("claude").open_import(UUID)
    assert opened == [f"claude://resume?session={UUID}"]


def test_open_import_refuses_a_non_uuid(monkeypatch):
    opened = []
    monkeypatch.setattr(claude_cli.os, "startfile", opened.append, raising=False)
    with pytest.raises(ClaudeCliError):
        ClaudeCli("claude").open_import("x&y=1")
    assert opened == []


def test_find_claude(tmp_path, monkeypatch):
    exe = tmp_path / "claude.exe"
    exe.write_text("")
    assert find_claude(str(exe)) == str(exe)
    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: "C:/bin/claude.exe")
    assert find_claude(str(tmp_path / "absent.exe")) == "C:/bin/claude.exe"
    assert find_claude(str(tmp_path)) == "C:/bin/claude.exe"  # un dossier n'est pas un executable
    assert find_claude(None) == "C:/bin/claude.exe"
    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: None)
    assert find_claude(None) is None


@pytest.mark.parametrize("name", ["claude.cmd", "claude.BAT"])
def test_find_claude_refuses_a_batch_file(tmp_path, monkeypatch, caplog, name):
    script = tmp_path / name
    script.write_text("")
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: None)
    assert find_claude(str(script)) is None
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: f"C:/npm/{name}")
    assert find_claude(None) is None
    assert name in caplog.text


class HangingProc:
    def __init__(self):
        self.killed = False
        self.waited = False
        self.returncode = None

    async def communicate(self):
        await asyncio.Event().wait()

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        self.returncode = -9


async def test_run_kills_the_child_when_cancelled(monkeypatch):
    proc = HangingProc()

    async def spawn(*args, **kwargs):
        return proc

    monkeypatch.setattr(claude_cli.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(claude_cli._run(["claude"], None, 30))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert proc.killed and proc.waited
