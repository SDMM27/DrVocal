import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from drvocal.claude_cli import AgentInfo, ClaudeCliError
from drvocal.claude_registry import Registry, SessionRecord
from drvocal.claude_voice import ClaudeVoice

NOW = datetime(2026, 11, 9, 12, 0, 0)
UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"


class FakeCli:
    def __init__(self):
        self.launched: list[tuple[Path, str, str, str | None]] = []
        self.stopped: list[str] = []
        self.imported: list[str] = []
        self.agents_result: list[AgentInfo] = []
        self.agents_error: ClaudeCliError | None = None
        self.launch_error: ClaudeCliError | None = None
        self.import_error: Exception | None = None
        self.next_id = "abc123"
        self.gate: asyncio.Event | None = None
        self.agents_calls = 0

    async def launch(self, cwd, name, prompt, resume=None):
        if self.gate is not None:
            await self.gate.wait()
        if self.launch_error:
            raise self.launch_error
        self.launched.append((cwd, name, prompt, resume))
        return self.next_id

    async def agents(self):
        self.agents_calls += 1
        if self.agents_error:
            raise self.agents_error
        return list(self.agents_result)

    async def stop(self, short_id):
        self.stopped.append(short_id)

    def open_import(self, uuid):
        if self.import_error:
            raise self.import_error
        self.imported.append(uuid)


def _agent(id="abc123", uuid=UUID_A, status="busy", state="working"):
    return AgentInfo(id=id, uuid=uuid, cwd=r"D:\NasaCode\DrVocal", status=status, state=state)


def _rec(id="abc123", **kw):
    base = dict(
        id=id, uuid=UUID_A, project="drvocal", path=r"D:\NasaCode\DrVocal",
        name="drvocal – tests", started=NOW, state="running",
    )
    base.update(kw)
    return SessionRecord(**base)


class Env:
    def __init__(self, tmp_path):
        self.cli = FakeCli()
        self.registry = Registry(tmp_path / "r.json", now=lambda: NOW)
        self.path = tmp_path / "r.json"
        self.notes: list[str] = []
        self.errors: list[str] = []
        self.beeps: list[str] = []
        self.sleeps: list[float] = []
        self.voice = ClaudeVoice(
            self.cli, self.registry,  # type: ignore[arg-type]
            {"drvocal": Path(r"D:\NasaCode\DrVocal")},
            self.notes.append, self.errors.append, self.beeps.append,
            sleep=self._sleep,
        )

    async def _sleep(self, delay):
        self.sleeps.append(delay)
        await asyncio.sleep(0)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


async def test_prompt_launches_in_the_project_folder_and_records_it(env):
    env.cli.agents_result = [_agent()]
    assert await env.voice.prompt("drvocal", "lance les tests") is True
    cwd, name, text, resume = env.cli.launched[0]
    assert cwd == Path(r"D:\NasaCode\DrVocal") and text == "lance les tests" and resume is None
    rec = env.registry.latest()
    assert rec is not None
    assert (rec.id, rec.uuid, rec.project, rec.state, rec.name) == ("abc123", UUID_A, "drvocal", "running", name)
    assert env.notes == [f"{name} : lancée"]
    assert Registry(env.path, now=lambda: NOW).latest() is not None  # sauvegarde
    await env.voice.close()


async def test_prompt_unknown_project_fails_without_launching(env):
    assert await env.voice.prompt("inconnu", "salut") is False
    assert env.cli.launched == []


async def test_prompt_refuses_a_second_session_on_a_busy_project(env):
    env.registry.add(_rec())
    assert await env.voice.prompt("drvocal", "encore") is False
    assert env.cli.launched == []
    assert env.errors == ["Claude travaille déjà sur drvocal."]


async def test_prompt_twice_concurrently_launches_once(env):
    env.cli.gate = asyncio.Event()
    env.cli.agents_result = [_agent()]
    first = asyncio.create_task(env.voice.prompt("drvocal", "un"))
    second = asyncio.create_task(env.voice.prompt("drvocal", "deux"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    env.cli.gate.set()
    results = await asyncio.gather(first, second)
    assert sorted(results) == [False, True]
    assert env.errors == ["Claude travaille déjà sur drvocal."]
    assert len(env.cli.launched) == 1
    await env.voice.close()


async def test_prompt_cli_error_is_shown_and_fails(env):
    env.cli.launch_error = ClaudeCliError("Claude Code a échoué (code 1).")
    assert await env.voice.prompt("drvocal", "x") is False
    assert env.errors == ["Claude Code a échoué (code 1)."]
    assert env.registry.records == []
    # le verrou est libere
    env.cli.launch_error = None
    env.cli.agents_result = [_agent()]
    assert await env.voice.prompt("drvocal", "x") is True
    await env.voice.close()


async def test_prompt_retries_agents_then_records_empty_uuid(env):
    env.cli.agents_error = ClaudeCliError("illisible")
    assert await env.voice.prompt("drvocal", "x") is True
    assert env.cli.agents_calls == 3
    rec = env.registry.latest()
    assert rec is not None and rec.uuid == "" and rec.state == "running"
    await env.voice.close()


async def test_poll_fills_a_missing_uuid(env):
    env.registry.add(_rec(uuid=""))
    env.cli.agents_result = [_agent()]
    await env.voice.poll_once()
    assert env.registry.records[0].uuid == UUID_A


async def test_poll_idle_marks_done_beeps_once_and_stops_the_session(env):
    env.registry.add(_rec())
    env.cli.agents_result = [_agent(status="idle", state="done")]
    await env.voice.poll_once()
    await env.voice.poll_once()
    assert env.registry.records[0].state == "done"
    assert env.beeps == ["done"]
    assert env.notes == ["drvocal – tests : finie"]
    assert env.cli.stopped == ["abc123"]


async def test_poll_waiting_beeps_once_and_keeps_the_session_alive(env):
    env.registry.add(_rec())
    env.cli.agents_result = [_agent(status="waiting", state="blocked")]
    await env.voice.poll_once()
    await env.voice.poll_once()
    assert env.registry.records[0].state == "waiting"
    assert env.beeps == ["done"]
    assert env.notes == ["drvocal – tests : attend ta réponse"]
    assert env.cli.stopped == []


async def test_poll_working_changes_nothing(env):
    env.registry.add(_rec())
    env.cli.agents_result = [_agent()]
    await env.voice.poll_once()
    assert env.registry.records[0].state == "running" and env.beeps == []


async def test_poll_missing_session_is_stopped_without_beep(env):
    env.registry.add(_rec())
    await env.voice.poll_once()
    assert env.registry.records[0].state == "stopped"
    assert env.beeps == []


async def test_poll_bad_agents_output_is_ignored(env, caplog):
    env.registry.add(_rec())
    env.cli.agents_error = ClaudeCliError("illisible")
    await env.voice.poll_once()
    assert env.registry.records[0].state == "running"
    assert env.beeps == [] and env.errors == []
    assert "illisible" in caplog.text


async def test_proceed_resumes_the_latest_session(env):
    env.registry.add(_rec(state="done"))
    assert await env.voice.proceed("continue") is True
    assert env.cli.launched == [(Path(r"D:\NasaCode\DrVocal"), "drvocal – tests", "continue", UUID_A)]
    assert len(env.registry.records) == 1 and env.registry.records[0].state == "running"
    await env.voice.close()


async def test_proceed_stops_a_waiting_session_first(env):
    env.registry.add(_rec(state="waiting"))
    assert await env.voice.proceed("oui") is True
    assert env.cli.stopped == ["abc123"]
    await env.voice.close()


async def test_proceed_without_session_fails(env):
    assert await env.voice.proceed("continue") is False


async def test_proceed_refuses_an_imported_session(env):
    env.registry.add(_rec(state="done", imported=True))
    assert await env.voice.proceed("continue") is False
    assert env.errors == ["Déjà dans l'app, continue là-bas."]
    assert env.cli.launched == []


async def test_proceed_refuses_while_running(env):
    env.registry.add(_rec())
    assert await env.voice.proceed("continue") is False
    assert env.errors == ["Claude travaille encore."]


async def test_proceed_with_new_id_records_a_child(env):
    env.registry.add(_rec(state="done"))
    env.cli.next_id = "def456"
    env.cli.agents_result = [_agent(id="def456", uuid=UUID_B)]
    assert await env.voice.proceed("continue") is True
    old, new = env.registry.records
    assert old.state == "done"
    assert (new.id, new.uuid, new.parent, new.state) == ("def456", UUID_B, "abc123", "running")
    await env.voice.close()


async def test_stop_stops_the_latest_alive_session(env):
    env.registry.add(_rec("a", state="waiting"))
    env.registry.add(_rec("b", state="done"))
    assert await env.voice.stop() is True
    assert env.cli.stopped == ["a"]
    assert env.registry.records[0].state == "stopped"
    assert env.notes == ["drvocal – tests : arrêtée"]


async def test_stop_without_alive_session_does_nothing(env):
    env.registry.add(_rec(state="done"))
    assert await env.voice.stop() is True
    assert env.cli.stopped == []


async def test_import_all_opens_each_finished_session_once(env):
    env.registry.add(_rec("a", uuid=UUID_A, state="done"))
    env.registry.add(_rec("b", uuid=UUID_B, state="running"))
    assert env.voice.import_all() is True
    assert env.cli.imported == [UUID_A]
    assert env.registry.records[0].imported is True
    assert env.notes == ["drvocal – tests : encore en cours, à importer plus tard"]
    assert env.voice.import_all() is True
    assert env.cli.imported == [UUID_A]


async def test_import_all_nothing_to_import(env):
    assert env.voice.import_all() is True


@pytest.mark.parametrize("error", [ClaudeCliError("invalide"), OSError("boom")])
def test_import_all_failure_is_reported_and_keeps_going(env, error):
    env.registry.add(_rec("a", uuid=UUID_A, state="done"))
    env.registry.add(_rec("b", uuid=UUID_B, state="done"))
    original = env.cli.open_import

    def flaky(uuid):
        if uuid == UUID_A:
            raise error
        original(uuid)

    env.cli.open_import = flaky  # type: ignore[method-assign]
    assert env.voice.import_all() is False
    assert [r.imported for r in env.registry.records] == [False, True]
    assert len(env.errors) == 1


def test_import_all_skips_a_session_without_uuid(env):
    env.registry.add(_rec("a", uuid="", state="done"))
    assert env.voice.import_all() is True
    assert env.cli.imported == [] and env.registry.records[0].imported is False
    assert env.notes == ["drvocal – tests : pas encore prête, à importer plus tard"]


async def test_proceed_refuses_a_session_without_uuid(env):
    env.registry.add(_rec(uuid="", state="done"))
    assert await env.voice.proceed("continue") is False
    assert env.errors == ["Session Claude pas encore prête."]
    assert env.cli.launched == []


async def test_poll_waiting_session_seen_working_goes_back_to_running(env):
    env.registry.add(_rec(state="waiting"))
    env.cli.agents_result = [_agent()]
    await env.voice.poll_once()
    assert env.registry.records[0].state == "running"
    assert env.beeps == []


class SlowAgents:
    """Bloque agents() jusqu'a ce qu'on le libere, en renvoyant la liste d'avant."""

    def __init__(self, env):
        self.gate = asyncio.Event()
        real = env.cli.agents
        self.snapshot: list[AgentInfo] = []

        async def agents():
            self.snapshot = await real()
            await self.gate.wait()
            return self.snapshot

        env.cli.agents = agents  # type: ignore[method-assign]


async def test_poll_ignores_a_session_resumed_during_the_wait(env):
    env.registry.add(_rec(state="done"))
    env.registry.add(_rec("w", state="waiting"))
    env.cli.agents_result = []
    slow = SlowAgents(env)
    poll = asyncio.create_task(env.voice.poll_once())
    await asyncio.sleep(0)
    env.registry.records[0].state = "running"  # reprise pendant l'attente
    env.registry.records[1].state = "running"
    env.registry.records[0].id = "x"
    slow.gate.set()
    await poll
    assert [r.state for r in env.registry.records] == ["running", "running"]
    assert env.beeps == []


async def test_poll_skips_a_record_added_during_the_wait(env):
    env.registry.add(_rec("a"))
    env.cli.agents_result = [_agent(id="a", status="idle", state="done")]
    slow = SlowAgents(env)
    poll = asyncio.create_task(env.voice.poll_once())
    await asyncio.sleep(0)
    env.registry.add(_rec("new"))  # absent de la liste, mais ajoute apres
    slow.gate.set()
    await poll
    assert [r.state for r in env.registry.records] == ["done", "running"]
    assert env.beeps == ["done"]


async def test_proceed_same_id_during_a_poll_keeps_the_session_running(env):
    env.registry.add(_rec(state="waiting"))
    env.cli.agents_result = []  # liste perimee : la session n'y figure pas
    slow = SlowAgents(env)
    poll = asyncio.create_task(env.voice.poll_once())
    await asyncio.sleep(0)
    env.cli.agents_result = [_agent()]  # ce que verront les passes suivantes
    assert await env.voice.proceed("continue") is True
    slow.gate.set()
    await poll
    assert env.registry.records[0].state == "running"
    assert env.beeps == []
    await env.voice.close()


async def test_prompt_survives_a_registry_save_failure(env):
    env.cli.agents_result = [_agent()]

    def broken():
        raise OSError("disque plein")

    env.registry.save = broken  # type: ignore[method-assign]
    assert await env.voice.prompt("drvocal", "x") is True
    assert env.errors == ["Impossible d'enregistrer les sessions Claude."]
    assert env.notes == ["drvocal – x : lancée"]
    assert env.voice._task is not None and not env.voice._task.done()
    await env.voice.close()


async def test_start_after_restart_resumes_watch_without_beeping_finished_ones(env):
    env.registry.add(_rec("old", state="done"))
    env.registry.add(_rec("live", uuid=UUID_B))
    env.cli.agents_result = [_agent(id="live", uuid=UUID_B, status="idle", state="done")]
    env.voice.start()
    assert env.notes == ["1 session Claude à importer"]  # "old" ; "live" tourne encore
    task = env.voice._task
    assert task is not None
    await task
    states = {r.id: r.state for r in env.registry.records}
    assert states == {"old": "done", "live": "done"}
    assert env.beeps == ["done"]
    assert env.cli.stopped == ["live"]


async def test_watch_loop_survives_an_unexpected_error(env, caplog):
    env.registry.add(_rec())
    calls = []

    async def poll():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("inattendu")
        env.registry.records[0].state = "done"

    env.voice.poll_once = poll  # type: ignore[method-assign]
    env.voice.start()
    await env.voice._task  # type: ignore[misc]
    assert len(calls) == 2
    assert "inattendu" in caplog.text
