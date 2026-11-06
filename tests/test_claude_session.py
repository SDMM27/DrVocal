import asyncio
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ProcessError,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)

from drvocal.claude_policy import Reply
from drvocal.claude_session import ClaudeRunner, SessionEvent, _Pending

P = Path("D:/proj")
KEY = "sk-test"


def result(is_error=False, text="ok", session_id="s1"):
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=is_error,
                         num_turns=1, session_id=session_id, result=text)


class FakeClient:
    def __init__(self, options, messages, error=None, during=None):
        self.options, self.messages, self.error, self.prompts = options, messages, error, []
        self.during = during

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt):
        self.prompts.append(prompt)

    async def receive_response(self):
        if self.error:
            raise self.error
        for message in self.messages:
            yield message
        if self.during:
            await self.during(self)


class Harness:
    def __init__(self, answers=None, messages=None, error=None):
        self.events: list[SessionEvent] = []
        self.asked: list[str] = []
        self.kinds_asked: list[str] = []
        self.answers = list(answers or [])
        self.clients: list[FakeClient] = []
        self.messages, self.error = messages or [result()], error
        self.during = None  # appelee dans la prochaine execution du client, comme un outil de Claude
        self.runner = self.make_runner(self.ask)

    def make_runner(self, ask, **kwargs):
        kwargs = {"api_key_provider": lambda: KEY, "project_validator": lambda p: None, **kwargs}
        return ClaudeRunner(self.events.append, ask, client_factory=self.factory, **kwargs)

    async def ask(self, summary, kind):
        self.asked.append(summary)
        self.kinds_asked.append(kind)
        return self.answers.pop(0) if self.answers else Reply.NONE

    def factory(self, options):
        client = FakeClient(options, self.messages, self.error, self.during)
        self.during = None
        self.clients.append(client)
        return client

    @property
    def options(self):
        return self.clients[-1].options

    async def hook(self, tool, tool_input, **extra):
        data = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, **extra}
        out = await self.options.hooks["PreToolUse"][0].hooks[0](data, "id1", None)
        return out["hookSpecificOutput"]

    def kinds(self):
        return [e.kind for e in self.events]


@pytest.fixture
def runner():
    return Harness()


async def test_start_uses_project_cwd_and_default_permission_mode(runner):
    await runner.runner.start(P, "salut")
    assert Path(runner.options.cwd) == P
    assert runner.options.permission_mode in (None, "default")
    assert runner.options.env == {"ANTHROPIC_API_KEY": KEY}
    assert runner.clients[0].prompts == ["salut"]


async def test_events_text_tool_done():
    h = Harness(messages=[AssistantMessage(content=[TextBlock("bonjour"), ToolUseBlock("t1", "Read", {})], model="m"),
                          result()])
    await h.runner.start(P, "x")
    assert [(e.kind, e.text) for e in h.events] == [("text", "bonjour"), ("tool", "Read"), ("done", "")]


async def test_resume_reuses_session_id(runner):
    await runner.runner.start(P, "a")
    await runner.runner.resume("b")
    assert runner.options.resume == "s1"
    assert Path(runner.options.cwd) == P
    assert runner.clients[1].prompts == ["b"]


async def test_resume_without_start_emits_error(runner):
    await runner.runner.resume("b")
    assert runner.kinds() == ["error", "done"]


async def test_usage_limit_emits_error_event_and_does_not_raise():
    h = Harness(error=ProcessError("limit", exit_code=1, stderr="Claude usage limit reached"))
    await h.runner.start(P, "x")
    assert h.kinds() == ["error", "done"]
    assert "limit" in h.events[0].text


async def test_error_result_emits_error_event():
    h = Harness(messages=[result(is_error=True, text="Usage limit reached")])
    await h.runner.start(P, "x")
    assert h.kinds() == ["error", "done"]
    assert "Usage limit" in h.events[0].text


async def test_hook_allows_read_in_project_without_asking(runner):
    await runner.runner.start(P, "x")
    out = await runner.hook("Read", {"file_path": "D:/proj/a.py"})
    assert out["permissionDecision"] == "allow" and runner.asked == []


async def test_hook_denies_destructive_without_asking(runner):
    await runner.runner.start(P, "x")
    out = await runner.hook("Bash", {"command": "rm -rf /"})
    assert out["permissionDecision"] == "deny" and out["permissionDecisionReason"]
    assert runner.asked == []


async def test_hook_runs_for_subagent_tools_too(runner):
    await runner.runner.start(P, "x")
    out = await runner.hook("Bash", {"command": "rm -rf /"}, agent_id="sub1")
    assert out["permissionDecision"] == "deny"


async def test_hook_asks_with_exact_command_and_allows_on_approve():
    h = Harness(answers=[Reply.APPROVE])
    await h.runner.start(P, "x")
    out = await h.hook("WebSearch", {"query": "npm test"})
    assert out["permissionDecision"] == "allow"
    assert "npm test" in h.asked[0]


async def test_hook_asks_with_exact_path_outside_project():
    h = Harness(answers=[Reply.APPROVE])
    await h.runner.start(P, "x")
    await h.hook("Read", {"file_path": "C:/x.py"})
    assert "C:/x.py" in h.asked[0]


async def test_reject_denies_without_pending():
    h = Harness(answers=[Reply.REJECT])
    await h.runner.start(P, "x")
    out = await h.hook("WebSearch", {"query": "npm test"})
    assert out["permissionDecision"] == "deny"
    assert "pending" not in h.kinds()


async def test_no_reply_keeps_request_pending_and_does_not_run(runner):
    await runner.runner.start(P, "x")
    out = await runner.hook("WebSearch", {"query": "npm test"})
    assert out["permissionDecision"] == "deny"
    pending = [e for e in runner.events if e.kind == "pending"]
    assert len(pending) == 1 and "npm test" in pending[0].text
    assert len(runner.runner.pending) == 1


async def test_ask_user_timeout_counts_as_no_reply():
    h = Harness()

    async def slow(summary, kind):
        await asyncio.sleep(5)

    h.runner = h.make_runner(slow, ask_timeout=0.01)
    await h.runner.start(P, "x")
    out = await h.hook("WebSearch", {"query": "npm test"})
    assert out["permissionDecision"] == "deny"
    assert "pending" in h.kinds()


async def test_resolve_pending_approve_resumes_session():
    h = Harness()
    await h.runner.start(P, "x")
    await h.hook("WebSearch", {"query": "npm test"})
    pending_id = next(iter(h.runner.pending))
    assert await h.runner.resolve_pending(pending_id, Reply.APPROVE) is True
    assert h.runner.pending == {}
    assert "npm test" in h.clients[-1].prompts[0]
    assert await h.runner.resolve_pending(pending_id, Reply.APPROVE) is False


async def test_resolve_pending_reject_drops_without_resume():
    h = Harness()
    await h.runner.start(P, "x")
    await h.hook("WebSearch", {"query": "npm test"})
    await h.runner.resolve_pending(next(iter(h.runner.pending)), Reply.REJECT)
    assert h.runner.pending == {} and len(h.clients) == 1


QUESTION = {"questions": [{"question": "Quel nom ?", "options": [{"label": "hello"}, {"label": "bye"}]}]}


async def test_hook_routes_question_to_can_use_tool(runner):
    await runner.runner.start(P, "x")
    out = await runner.hook("AskUserQuestion", QUESTION)
    assert out["permissionDecision"] == "ask" and runner.asked == []


async def test_question_answer_is_passed_back_verbatim():
    h = Harness(answers=["le premier"])
    await h.runner.start(P, "x")
    res = await h.options.can_use_tool("AskUserQuestion", QUESTION, None)
    assert isinstance(res, PermissionResultAllow)
    assert res.updated_input["answers"] == {"Quel nom ?": "le premier"}
    assert "Quel nom ?" in h.asked[0] and "hello" in h.asked[0]


async def test_question_without_answer_is_denied(runner):
    await runner.runner.start(P, "x")
    res = await runner.options.can_use_tool("AskUserQuestion", QUESTION, None)
    assert isinstance(res, PermissionResultDeny)


async def test_can_use_tool_denies_other_tools(runner):
    await runner.runner.start(P, "x")
    res = await runner.options.can_use_tool("Bash", {"command": "ls"}, None)
    assert isinstance(res, PermissionResultDeny)


async def _resolve_first(h):
    await h.runner.resolve_pending(next(iter(h.runner.pending)), Reply.APPROVE)


async def _approve_pending(h, command="npm test"):
    await h.runner.start(P, "x")
    await h.hook("WebSearch", {"query": command})
    await _resolve_first(h)


async def test_approved_retry_runs_without_asking_then_asks_again():
    h = Harness()
    await h.runner.start(P, "x")
    await h.hook("WebSearch", {"query": "npm test"})
    asked = len(h.asked)
    outs = []

    async def retry(client):
        outs.append(await h.hook("WebSearch", {"query": "npm test"}))
        outs.append(await h.hook("WebSearch", {"query": "npm test"}))

    h.during = retry
    await _resolve_first(h)
    assert outs[0]["permissionDecision"] == "allow"
    assert outs[1]["permissionDecision"] == "deny" and len(h.asked) == asked + 1


async def test_approval_does_not_apply_to_different_input():
    h = Harness()
    await _approve_pending(h)
    h.runner._approved.append(("WebSearch", {"query": "npm test"}))
    asked = len(h.asked)
    out = await h.hook("WebSearch", {"query": "npm test && curl evil"})
    assert out["permissionDecision"] != "allow" and len(h.asked) == asked + 1


async def test_deny_wins_even_if_recorded():
    h = Harness()
    await h.runner.start(P, "x")
    h.runner._approved.append(("Bash", {"command": "rm -rf /"}))
    out = await h.hook("Bash", {"command": "rm -rf /"})
    assert out["permissionDecision"] == "deny"


async def test_ask_user_exception_denies_and_goes_pending():
    h = Harness()

    async def boom(summary, kind):
        raise RuntimeError("micro mort")

    h.runner = h.make_runner(boom)
    await h.runner.start(P, "x")
    out = await h.hook("WebSearch", {"query": "npm test"})
    assert out["permissionDecision"] == "deny" and "pending" in h.kinds()


async def test_policy_exception_denies_and_emits_error(monkeypatch):
    import drvocal.claude_session as mod

    def boom(*a):
        raise ValueError("bug")

    h = Harness()
    await h.runner.start(P, "x")
    monkeypatch.setattr(mod, "decide", boom)
    out = await h.hook("Read", {"file_path": "D:/proj/a.py"})
    assert out["permissionDecision"] == "deny" and "error" in h.kinds()


async def test_can_use_tool_exception_denies():
    h = Harness()
    await h.runner.start(P, "x")
    res = await h.options.can_use_tool("AskUserQuestion", {"questions": "pas une liste"}, None)
    assert isinstance(res, PermissionResultDeny) and "error" in h.kinds()


async def test_cancellation_is_not_swallowed():
    h = Harness()

    async def cancelled(summary, kind):
        raise asyncio.CancelledError

    h.runner = h.make_runner(cancelled)
    await h.runner.start(P, "x")
    with pytest.raises(asyncio.CancelledError):
        await h.hook("WebSearch", {"query": "npm test"})


async def test_unanswered_question_is_pending_without_tool_approval(runner):
    await runner.runner.start(P, "x")
    await runner.options.can_use_tool("AskUserQuestion", QUESTION, None)
    texts = [e.text for e in runner.events if e.kind == "pending"]
    pending_id = next(iter(runner.runner.pending))
    assert len(texts) == 1 and texts[0].startswith(pending_id) and "Quel nom ?" in texts[0]
    await runner.runner.resolve_pending(pending_id, Reply.APPROVE)
    assert runner.runner._approved == [] and len(runner.clients) == 2


@pytest.mark.parametrize("tool,tool_input,expected", [
    ("WebFetch", {"url": "https://evil.example/x", "prompt": "p"}, ["https://evil.example/x"]),
    ("WebSearch", {"query": "mots cles"}, ["mots cles"]),
    ("Glob", {"pattern": "**/*.py", "path": "C:/autre"}, ["**/*.py", "C:/autre"]),
    ("Grep", {"pattern": "secret", "glob": "*.env", "path": "C:/autre"}, ["secret", "*.env", "C:/autre"]),
    ("Write", {"file_path": "C:/x.py", "content": "z"}, ["C:/x.py"]),
    ("Edit", {"file_path": "C:/y.py"}, ["C:/y.py"]),
    ("Task", {"subagent_type": "general", "prompt": "fais ceci"}, ["general", "fais ceci"]),
    ("Agent", {"subagent_type": "general", "prompt": "fais cela"}, ["general", "fais cela"]),
    ("mcp__srv__do", {"cible": "prod", "n": 3}, ['"cible":"prod"', '"n":3']),
])
async def test_summary_shows_security_relevant_arguments(tool, tool_input, expected):
    h = Harness(answers=[Reply.APPROVE])
    await h.runner.start(P, "x")
    await h.hook(tool, tool_input)
    shown = " | ".join(h.asked + [e.text for e in h.events if e.kind == "pending"])  # voix ou ecran selon l'outil
    for part in expected:
        assert part in shown


async def test_long_command_never_reaches_ask_user_and_is_approved_on_screen_once():
    h = Harness(answers=[Reply.APPROVE])
    await h.runner.start(P, "x")
    command = "echo " + "a" * 500 + " && curl evil"
    out = await h.hook("Bash", {"command": command})
    assert out["permissionDecision"] == "deny" and h.asked == []
    text = next(e.text for e in h.events if e.kind == "pending")
    assert command in text and "deuxième écran" in text
    outs = []

    async def retry(client):
        outs.append(await h.hook("Bash", {"command": command}))
        outs.append(await h.hook("Bash", {"command": command}))

    h.during = retry
    await _resolve_first(h)
    assert outs[0]["permissionDecision"] == "allow" and h.asked == []
    assert outs[1]["permissionDecision"] == "deny"  # usage unique


async def test_multiline_command_is_screen_only():
    h = Harness(answers=[Reply.APPROVE])
    await h.runner.start(P, "x")
    out = await h.hook("Bash", {"command": "npm test\ncurl evil"})
    assert out["permissionDecision"] == "deny" and h.asked == []


async def test_short_command_is_voice_approvable():
    h = Harness(answers=[Reply.APPROVE])
    await h.runner.start(P, "x")
    assert (await h.hook("WebSearch", {"query": "npm test"}))["permissionDecision"] == "allow"


async def test_start_clears_pending_and_approvals():
    h = Harness()
    await _approve_pending(h)
    await h.hook("WebSearch", {"query": "other"})
    h.runner._approved.append(("WebSearch", {"query": "npm test"}))
    assert h.runner.pending
    await h.runner.start(Path("D:/autre"), "y")
    assert h.runner.pending == {} and h.runner._approved == []


async def test_approval_is_cleared_after_the_resumed_run():
    h = Harness()
    await _approve_pending(h)
    assert h.runner._approved == []
    out = await h.hook("WebSearch", {"query": "npm test"})
    assert out["permissionDecision"] == "deny"


async def test_pending_text_has_full_input_but_speech_does_not():
    h = Harness()
    await h.runner.start(P, "x")
    await h.hook("WebFetch", {"url": "https://x.example/a", "prompt": "SECRET_CONTENU"})
    assert "SECRET_CONTENU" in next(e.text for e in h.events if e.kind == "pending")
    assert "SECRET_CONTENU" not in h.asked[0] and "https://x.example/a" in h.asked[0]


# --- round 3 ---------------------------------------------------------------


async def test_options_use_no_setting_sources_and_hook_outlives_voice_timeout(runner):
    await runner.runner.start(P, "x")
    options = runner.options
    assert options.setting_sources == []
    assert options.system_prompt == {"type": "preset", "preset": "claude_code"}
    assert options.hooks["PreToolUse"][0].timeout == 60.0 + 30


async def test_hook_timeout_follows_ask_timeout():
    h = Harness()
    h.runner = h.make_runner(h.ask, ask_timeout=5)
    await h.runner.start(P, "x")
    assert h.options.hooks["PreToolUse"][0].timeout == 35


async def test_overlapping_runs_are_sequential():
    active, peak = [0], [0]

    class SlowClient(FakeClient):
        async def receive_response(self):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            await asyncio.sleep(0.02)
            active[0] -= 1
            yield result()

    h = Harness()
    h.runner = ClaudeRunner(h.events.append, h.ask, client_factory=lambda o: SlowClient(o, []),
                            api_key_provider=lambda: KEY, project_validator=lambda p: None)
    await asyncio.gather(h.runner.start(P, "a"), h.runner.resume("b"), h.runner.resume("c"))
    assert peak[0] == 1


async def test_parallel_asks_are_serialized():
    active, peak, order = [0], [0], []

    async def ask(summary, kind):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        order.append(summary)
        await asyncio.sleep(0.01)
        active[0] -= 1
        return Reply.APPROVE

    h = Harness()
    h.runner = h.make_runner(ask)
    await h.runner.start(P, "x")
    outs = await asyncio.gather(h.hook("WebSearch", {"query": "a"}), h.hook("WebSearch", {"query": "b"}))
    assert peak[0] == 1 and len(order) == 2
    assert all(o["permissionDecision"] == "allow" for o in outs)


async def test_queued_ask_counts_its_wait_in_the_timeout():
    async def ask(summary, kind):
        await asyncio.sleep(0.2)
        return Reply.APPROVE

    h = Harness()
    h.runner = h.make_runner(ask, ask_timeout=0.05)
    await h.runner.start(P, "x")
    outs = await asyncio.gather(h.hook("WebSearch", {"query": "a"}), h.hook("WebSearch", {"query": "b"}))
    assert [o["permissionDecision"] for o in outs] == ["deny", "deny"]


async def test_approval_during_first_run_is_not_lost_and_no_false_done():
    init = SystemMessage(subtype="init", data={"session_id": "s1"})
    h = Harness(messages=[init])
    outs, tasks = [], []

    async def retry(client):
        outs.append(await h.hook("WebSearch", {"query": "npm test"}))

    async def first(client):
        await h.hook("WebSearch", {"query": "npm test"})
        pending_id = next(iter(h.runner.pending))
        tasks.append(asyncio.create_task(h.runner.resolve_pending(pending_id, Reply.APPROVE)))
        await asyncio.sleep(0.01)  # la reprise est en file derriere la premiere execution
        assert h.kinds().count("done") == 0 and len(h.clients) == 1
        h.during = retry

    h.during = first
    await h.runner.start(P, "x")
    assert await tasks[0] is True
    assert outs[0]["permissionDecision"] == "allow"
    assert h.kinds().count("done") == 2


async def test_resolve_pending_stays_pending_when_session_not_resumable():
    h = Harness(messages=[AssistantMessage(content=[], model="m")])
    await h.runner.start(P, "x")
    await h.hook("WebSearch", {"query": "npm test"})
    pending_id = next(iter(h.runner.pending))
    assert await h.runner.resolve_pending(pending_id, Reply.APPROVE) is False
    assert pending_id in h.runner.pending and h.runner._approved == [] and len(h.clients) == 1


async def test_session_id_is_captured_from_init_message():
    h = Harness(messages=[SystemMessage(subtype="init", data={"session_id": "sinit"})])
    await h.runner.start(P, "x")
    await h.runner.resume("y")
    assert h.options.resume == "sinit"


@pytest.mark.parametrize("command", ["echo ‮evil", "echo a b", "echo a\x00b"])
async def test_control_and_format_characters_are_screen_only(command):
    h = Harness(answers=[Reply.APPROVE])
    await h.runner.start(P, "x")
    out = await h.hook("Bash", {"command": command})
    assert out["permissionDecision"] == "deny" and h.asked == []
    assert any(e.kind == "pending" for e in h.events)


async def test_ask_kinds_are_approval_and_question():
    h = Harness(answers=[Reply.APPROVE, "oui"])
    await h.runner.start(P, "x")
    await h.hook("WebSearch", {"query": "npm test"})
    await h.options.can_use_tool("AskUserQuestion", QUESTION, None)
    assert h.kinds_asked == ["approval", "question"]


async def test_overlong_question_goes_pending_without_asking():
    h = Harness(answers=["reponse"])
    await h.runner.start(P, "x")
    long_q = {"questions": [{"question": "Q" * 400, "options": []}]}
    res = await h.options.can_use_tool("AskUserQuestion", long_q, None)
    assert isinstance(res, PermissionResultDeny) and h.asked == []
    assert [e.question for e in h.events if e.kind == "pending"] == [True]


async def test_empty_answer_counts_as_no_answer():
    h = Harness(answers=["  "])
    await h.runner.start(P, "x")
    res = await h.options.can_use_tool("AskUserQuestion", QUESTION, None)
    assert isinstance(res, PermissionResultDeny)
    assert [e.question for e in h.events if e.kind == "pending"] == [True]


async def test_tool_pending_is_not_a_question():
    h = Harness()
    await h.runner.start(P, "x")
    await h.hook("WebSearch", {"query": "npm test"})
    assert [e.question for e in h.events if e.kind == "pending"] == [False]


# --- lot L1 : cle API, approbation limitee, arret, limites, audit -----------


async def hang(client):
    await asyncio.Event().wait()


async def test_api_key_comes_from_provider_and_environment_is_not_scrubbed(monkeypatch):
    import os

    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-l-environnement")
    h = Harness()
    h.runner = h.make_runner(h.ask, api_key_provider=lambda: "sk-fournisseur")
    await h.runner.start(P, "x")
    assert h.options.env == {"ANTHROPIC_API_KEY": "sk-fournisseur"}
    assert os.environ["ANTHROPIC_API_KEY"] == "cle-de-l-environnement"


async def test_default_provider_reads_environment(monkeypatch):
    from drvocal.claude_session import env_api_key

    monkeypatch.setenv("ANTHROPIC_API_KEY", " sk-env ")
    assert env_api_key() == "sk-env"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert env_api_key() is None


async def test_no_api_key_means_error_and_no_session():
    h = Harness()
    h.runner = h.make_runner(h.ask, api_key_provider=lambda: None)
    await h.runner.start(P, "x")
    assert h.clients == [] and h.kinds() == ["error", "done"]
    assert "clé API" in h.events[0].text


async def test_start_refuses_invalid_project():
    h = Harness()
    h.runner = ClaudeRunner(h.events.append, h.ask, client_factory=h.factory, api_key_provider=lambda: KEY)
    await h.runner.start(Path("Z:/n-existe-pas"), "x")
    assert h.clients == [] and h.kinds() == ["error", "done"]


async def test_limits_are_passed_to_sdk(runner):
    await runner.runner.start(P, "x")
    assert runner.options.max_turns == 30 and runner.options.max_budget_usd == 2.0
    h = Harness()
    h.runner = h.make_runner(h.ask, max_turns=5, max_budget_usd=0.5)
    await h.runner.start(P, "x")
    assert h.options.max_turns == 5 and h.options.max_budget_usd == 0.5


@pytest.mark.parametrize("tool,tool_input", [
    ("Bash", {"command": "npm test"}),
    ("PowerShell", {"command": "Get-Date"}),
    ("Write", {"file_path": "C:/x.py", "content": "z"}),
    ("Edit", {"file_path": "D:/proj/package.json"}),
    ("MultiEdit", {"file_path": "D:/proj/CLAUDE.md"}),
    ("NotebookEdit", {"notebook_path": "C:/n.ipynb"}),
])
async def test_sensitive_tools_never_reach_voice_approval(tool, tool_input):
    h = Harness(answers=[Reply.APPROVE, Reply.APPROVE])
    await h.runner.start(P, "x")
    out = await h.hook(tool, tool_input)
    assert h.asked == [] and out["permissionDecision"] == "deny"
    assert [e.kind for e in h.events if e.kind == "pending"] == ["pending"]
    assert next(iter(h.runner.pending.values())).screen_only is True


async def test_low_risk_tools_can_still_be_approved_by_voice():
    h = Harness(answers=[Reply.APPROVE, Reply.APPROVE])
    await h.runner.start(P, "x")
    assert (await h.hook("WebSearch", {"query": "q"}))["permissionDecision"] == "allow"
    assert (await h.hook("Read", {"file_path": "C:/x.txt"}))["permissionDecision"] == "allow"
    assert len(h.asked) == 2


async def test_stop_interrupts_a_never_ending_session_quickly():
    h = Harness()
    h.during = hang  # receive_response ne finit jamais ; le faux client n'a pas d'interrupt
    task = asyncio.create_task(h.runner.start(P, "x"))
    while not h.clients:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    h.runner._approved.append(("WebSearch", {"query": "q"}))
    t0 = asyncio.get_running_loop().time()
    await h.runner.stop()
    await asyncio.wait_for(task, 2)
    assert asyncio.get_running_loop().time() - t0 < 2
    assert h.runner._approved == [] and h.kinds()[-1] == "done"
    assert "arrêté" in next(e.text for e in h.events if e.kind == "text")
    assert "error" not in h.kinds()


async def test_stop_calls_interrupt_and_survives_a_hanging_interrupt():
    h = Harness()
    h.during = hang
    calls = []

    async def interrupt():
        calls.append(1)
        await asyncio.Event().wait()

    task = asyncio.create_task(h.runner.start(P, "x"))
    while not h.clients:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    h.clients[0].interrupt = interrupt
    h.runner._client = h.clients[0]
    t0 = asyncio.get_running_loop().time()
    await h.runner.stop()
    await asyncio.wait_for(task, 2)
    assert calls == [1] and asyncio.get_running_loop().time() - t0 < 2


async def test_stop_cancels_a_resume_queued_behind_the_running_session():
    h = Harness()
    h.during = hang
    first = asyncio.create_task(h.runner.start(P, "x"))
    while not h.clients:
        await asyncio.sleep(0.01)
    h.runner._session_id = "s1"  # session reprenable
    queued = asyncio.create_task(h.runner.resume("encore"))  # attend le verrou
    await asyncio.sleep(0.05)
    await h.runner.stop()
    await asyncio.wait_for(asyncio.gather(first, queued), 2)
    assert len(h.clients) == 1  # la relance en file n'a jamais lance Claude


async def test_stop_forgets_pending_requests():
    h = Harness()
    h.during = hang
    task = asyncio.create_task(h.runner.start(P, "x"))
    while not h.clients:
        await asyncio.sleep(0.01)
    h.runner._add_pending(_Pending("Bash : rm", "Bash", {"command": "rm"}, screen_only=True))
    pending_id = next(iter(h.runner.pending))
    await h.runner.stop()
    await asyncio.wait_for(task, 2)
    assert h.runner.pending == {}
    assert await h.runner.resolve_pending(pending_id, Reply.APPROVE) is False
    assert len(h.clients) == 1


async def test_stop_without_session_says_so():
    h = Harness()
    await h.runner.stop()
    assert [e.kind for e in h.events] == ["text"]


async def test_max_duration_emits_error():
    h = Harness()
    h.runner = h.make_runner(h.ask, max_duration=0.05)
    h.during = hang
    await asyncio.wait_for(h.runner.start(P, "x"), 2)
    assert h.kinds() == ["error", "done"] and "durée maximale" in h.events[0].text


async def test_caller_cancellation_cancels_the_session():
    h = Harness()
    h.during = hang
    task = asyncio.create_task(h.runner.start(P, "x"))
    while not h.clients:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    inner = h.runner._task
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert inner is not None and inner.cancelled()


async def test_audit_log_has_one_line_per_decision_and_no_content(tmp_path):
    import json

    audit = tmp_path / "logs" / "audit.jsonl"
    h = Harness(answers=[Reply.APPROVE])
    h.runner = h.make_runner(h.ask, audit_path=audit)
    await h.runner.start(P, "x")
    long_command = "npm test " + "x" * 200
    await h.hook("Read", {"file_path": "D:/proj/a.py"})
    await h.hook("Bash", {"command": "rm -rf /"})
    await h.hook("Bash", {"command": long_command})
    await h.hook("WebSearch", {"query": "q"})
    await h.hook("Write", {"file_path": "D:/proj/package.json", "content": "SECRET_CONTENU"})
    rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [(r["tool"], r["decision"], r["origin"]) for r in rows] == [
        ("Read", "allow", "policy"), ("Bash", "deny", "policy"), ("Bash", "ask", "ecran"),
        ("WebSearch", "allow", "vocal"), ("Write", "ask", "ecran")]
    assert rows[2]["target"] == long_command[:60] and rows[4]["target"] == "D:/proj/package.json"
    assert all(r["session_id"] == "s1" and r["ts"] for r in rows)
    assert "SECRET_CONTENU" not in audit.read_text(encoding="utf-8")


async def test_audit_write_failure_never_breaks_the_policy(tmp_path):
    h = Harness()
    h.runner = h.make_runner(h.ask, audit_path=tmp_path)  # un dossier : l'ecriture echoue
    await h.runner.start(P, "x")
    out = await h.hook("Read", {"file_path": "D:/proj/a.py"})
    assert out["permissionDecision"] == "allow"
    out = await h.hook("Bash", {"command": "rm -rf /"})
    assert out["permissionDecision"] == "deny"
