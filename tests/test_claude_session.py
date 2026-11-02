import asyncio
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ProcessError,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from drvocal.claude_policy import Reply
from drvocal.claude_session import ClaudeRunner, SessionEvent, build_env

P = Path("D:/proj")


def result(is_error=False, text="ok", session_id="s1"):
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=is_error,
                         num_turns=1, session_id=session_id, result=text)


class FakeClient:
    def __init__(self, options, messages, error=None):
        self.options, self.messages, self.error, self.prompts = options, messages, error, []

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


class Harness:
    def __init__(self, answers=None, messages=None, error=None):
        self.events: list[SessionEvent] = []
        self.asked: list[str] = []
        self.answers = list(answers or [])
        self.clients: list[FakeClient] = []
        self.messages, self.error = messages or [result()], error
        self.runner = ClaudeRunner(self.events.append, self.ask, client_factory=self.factory)

    async def ask(self, summary):
        self.asked.append(summary)
        return self.answers.pop(0) if self.answers else Reply.NONE

    def factory(self, options):
        client = FakeClient(options, self.messages, self.error)
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


def test_session_env_has_no_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "y")
    env = build_env()
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env


async def test_start_uses_project_cwd_and_default_permission_mode(runner):
    await runner.runner.start(P, "salut")
    assert Path(runner.options.cwd) == P
    assert runner.options.permission_mode in (None, "default")
    assert "ANTHROPIC_API_KEY" not in runner.options.env
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
    out = await h.hook("Bash", {"command": "npm test"})
    assert out["permissionDecision"] == "allow"
    assert "npm test" in h.asked[0]


async def test_hook_asks_with_exact_path_outside_project():
    h = Harness(answers=[Reply.APPROVE])
    await h.runner.start(P, "x")
    await h.hook("Edit", {"file_path": "C:/x.py"})
    assert "C:/x.py" in h.asked[0]


async def test_reject_denies_without_pending():
    h = Harness(answers=[Reply.REJECT])
    await h.runner.start(P, "x")
    out = await h.hook("Bash", {"command": "npm test"})
    assert out["permissionDecision"] == "deny"
    assert "pending" not in h.kinds()


async def test_no_reply_keeps_request_pending_and_does_not_run(runner):
    await runner.runner.start(P, "x")
    out = await runner.hook("Bash", {"command": "npm test"})
    assert out["permissionDecision"] == "deny"
    pending = [e for e in runner.events if e.kind == "pending"]
    assert len(pending) == 1 and "npm test" in pending[0].text
    assert len(runner.runner.pending) == 1


async def test_ask_user_timeout_counts_as_no_reply():
    h = Harness()

    async def slow(summary):
        await asyncio.sleep(5)

    h.runner = ClaudeRunner(h.events.append, slow, client_factory=h.factory, ask_timeout=0.01)
    await h.runner.start(P, "x")
    out = await h.hook("Bash", {"command": "npm test"})
    assert out["permissionDecision"] == "deny"
    assert "pending" in h.kinds()


async def test_resolve_pending_approve_resumes_session():
    h = Harness()
    await h.runner.start(P, "x")
    await h.hook("Bash", {"command": "npm test"})
    pending_id = next(iter(h.runner.pending))
    assert await h.runner.resolve_pending(pending_id, Reply.APPROVE) is True
    assert h.runner.pending == {}
    assert "npm test" in h.clients[-1].prompts[0]
    assert await h.runner.resolve_pending(pending_id, Reply.APPROVE) is False


async def test_resolve_pending_reject_drops_without_resume():
    h = Harness()
    await h.runner.start(P, "x")
    await h.hook("Bash", {"command": "npm test"})
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


async def _approve_pending(h, command="npm test"):
    await h.runner.start(P, "x")
    await h.hook("Bash", {"command": command})
    await h.runner.resolve_pending(next(iter(h.runner.pending)), Reply.APPROVE)


async def test_approved_retry_runs_without_asking_then_asks_again():
    h = Harness()
    await _approve_pending(h)
    asked = len(h.asked)
    out = await h.hook("Bash", {"command": "npm test"})
    assert out["permissionDecision"] == "allow" and len(h.asked) == asked
    again = await h.hook("Bash", {"command": "npm test"})
    assert again["permissionDecision"] == "deny" and len(h.asked) == asked + 1


async def test_approval_does_not_apply_to_different_input():
    h = Harness()
    await _approve_pending(h)
    asked = len(h.asked)
    out = await h.hook("Bash", {"command": "npm test && curl evil"})
    assert out["permissionDecision"] != "allow" and len(h.asked) == asked + 1


async def test_deny_wins_even_if_recorded():
    h = Harness()
    await h.runner.start(P, "x")
    h.runner._approved.append(("Bash", {"command": "rm -rf /"}))
    out = await h.hook("Bash", {"command": "rm -rf /"})
    assert out["permissionDecision"] == "deny"


async def test_ask_user_exception_denies_and_goes_pending():
    h = Harness()

    async def boom(summary):
        raise RuntimeError("micro mort")

    h.runner = ClaudeRunner(h.events.append, boom, client_factory=h.factory)
    await h.runner.start(P, "x")
    out = await h.hook("Bash", {"command": "npm test"})
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

    async def cancelled(summary):
        raise asyncio.CancelledError

    h.runner = ClaudeRunner(h.events.append, cancelled, client_factory=h.factory)
    await h.runner.start(P, "x")
    with pytest.raises(asyncio.CancelledError):
        await h.hook("Bash", {"command": "npm test"})


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
    for part in expected:
        assert part in h.asked[0]


async def test_long_summary_is_truncated_for_speech_but_complete_on_screen():
    h = Harness()
    await h.runner.start(P, "x")
    command = "echo " + "a" * 500
    await h.hook("Bash", {"command": command})
    assert len(h.asked[0]) < 300 and "deuxieme ecran" in h.asked[0]
    assert command in next(e.text for e in h.events if e.kind == "pending")


async def test_short_summary_is_not_marked_truncated():
    h = Harness()
    await h.runner.start(P, "x")
    await h.hook("Bash", {"command": "npm test"})
    assert "deuxieme ecran" not in h.asked[0]
