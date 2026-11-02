"""Pilotage de Claude Code en arriere-plan avec la connexion Pro de l'utilisateur.

La politique est appliquee dans un hook PreToolUse, qui s'execute pour chaque
outil (sous-agents compris) meme si une regle utilisateur l'autoriserait deja.
Aucun mode qui contourne les autorisations n'est utilise.
"""
import asyncio
import itertools
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from drvocal.claude_policy import Decision, Reply, decide

_QUESTION_TOOL = "AskUserQuestion"
_NO_ANSWER = "L'utilisateur n'a pas repondu."


@dataclass(frozen=True)
class _Pending:
    summary: str
    tool: str | None = None  # None : simple question, aucune approbation d'outil
    tool_input: dict | None = None


@dataclass(frozen=True)
class SessionEvent:
    kind: str  # text, tool, pending, done ou error
    text: str


def build_env() -> dict[str, str]:
    """Environnement sans cle API, pour que la facturation reste sur l'abonnement."""
    return {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}


_SUMMARY_KEYS = {
    "WebFetch": ("url",),
    "WebSearch": ("query",),
    "Glob": ("pattern", "path"),
    "Grep": ("pattern", "glob", "path"),
    "Read": ("file_path",),
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "NotebookEdit": ("notebook_path",),
    "Task": ("subagent_type", "prompt"),
    "Agent": ("subagent_type", "prompt"),
    "Bash": ("command",),
    "PowerShell": ("command",),
}
_SPOKEN_SUFFIX = "... detail sur le deuxieme ecran"


def _summary(tool: str, tool_input: dict) -> str:
    """Texte complet de ce qui est autorise ; il part tel quel sur le deuxieme ecran."""
    keys = _SUMMARY_KEYS.get(tool)
    if keys:
        details = " ; ".join(f"{k} = {tool_input[k]}" for k in keys if tool_input.get(k))
    else:
        details = json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"Claude veut utiliser {tool} : {details}" if details else f"Claude veut utiliser l'outil {tool}"


def _spoken(summary: str, limit: int = 200) -> str:
    """Version dite a voix haute : tronquee, en le signalant."""
    if len(summary) <= limit:
        return summary
    return summary[:limit].rstrip() + _SPOKEN_SUFFIX


def _question_text(tool_input: dict) -> str:
    parts = []
    for q in tool_input.get("questions", []):
        labels = ", ".join(o.get("label", "") for o in q.get("options", []))
        parts.append(f"{q.get('question', '')} Options : {labels}" if labels else q.get("question", ""))
    return " ".join(parts)


def _verdict(decision: str, reason: str = "") -> dict:
    out = {"hookEventName": "PreToolUse", "permissionDecision": decision}
    if reason:
        out["permissionDecisionReason"] = reason
    return {"hookSpecificOutput": out}


class ClaudeRunner:
    def __init__(
        self,
        on_event: Callable[[SessionEvent], None],
        ask_user: Callable[[str], Awaitable[Reply | str]],
        client_factory: Callable[[ClaudeAgentOptions], object] = lambda options: ClaudeSDKClient(options=options),
        ask_timeout: float = 60.0,
    ):
        self._emit = on_event
        self._ask_user = ask_user
        self._factory = client_factory
        self._ask_timeout = ask_timeout
        self._project: Path | None = None
        self._session_id: str | None = None
        self._ids = itertools.count(1)
        self.pending: dict[str, _Pending] = {}
        self._approved: list[tuple[str, dict]] = []

    async def start(self, project: Path, prompt: str) -> None:
        self._project, self._session_id = project, None
        await self._run(prompt)

    async def resume(self, prompt: str) -> None:
        if self._project is None or self._session_id is None:
            self._emit(SessionEvent("error", "Aucune session Claude a reprendre."))
            self._emit(SessionEvent("done", ""))
            return
        await self._run(prompt)

    async def resolve_pending(self, pending_id: str, reply: Reply) -> bool:
        """Traite une demande restee sans reponse ; une approbation relance la session."""
        entry = self.pending.pop(pending_id, None)
        if entry is None:
            return False
        if reply is Reply.APPROVE:
            if entry.tool is None:
                await self.resume(f"L'utilisateur n'a pas pu repondre a : {entry.summary}. Reformule ou continue.")
            else:
                self._approved.append((entry.tool, entry.tool_input))  # une seule fois
                await self.resume(f"L'utilisateur autorise : {entry.summary}. Tu peux reessayer cette action.")
        return True

    def _add_pending(self, entry: _Pending) -> None:
        pending_id = f"p{next(self._ids)}"
        self.pending[pending_id] = entry
        self._emit(SessionEvent("pending", f"{pending_id}: {entry.summary}"))

    def _options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cwd=self._project,
            env=build_env(),
            resume=self._session_id,
            permission_mode="default",
            can_use_tool=self._can_use_tool,
            hooks={"PreToolUse": [HookMatcher(hooks=[self._pre_tool_use])]},
        )

    async def _run(self, prompt: str) -> None:
        try:
            async with self._factory(self._options()) as client:
                await client.query(prompt)
                async for message in client.receive_response():
                    self._handle(message)
        except Exception as exc:  # limite d'usage, processus mort, connexion expiree...
            self._emit(SessionEvent("error", str(exc) or type(exc).__name__))
        self._emit(SessionEvent("done", ""))

    def _handle(self, message: object) -> None:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    self._emit(SessionEvent("text", block.text))
                elif isinstance(block, ToolUseBlock):
                    self._emit(SessionEvent("tool", block.name))
        elif isinstance(message, ResultMessage):
            self._session_id = message.session_id or self._session_id
            if message.is_error:
                self._emit(SessionEvent("error", message.result or "; ".join(message.errors or []) or message.subtype))

    async def _ask(self, text: str) -> Reply | str:
        try:
            return await asyncio.wait_for(self._ask_user(text), self._ask_timeout)
        except Exception:  # TimeoutError compris ; CancelledError n'est pas une Exception
            return Reply.NONE

    async def _pre_tool_use(self, input_data, tool_use_id, context) -> dict:
        try:
            return await self._decide_tool(input_data)
        except Exception as exc:  # echec ferme : dans le doute, l'outil ne tourne pas
            self._emit(SessionEvent("error", f"Erreur de la politique : {exc}"))
            return _verdict("deny", "Erreur interne de Dr Vocal.")

    async def _decide_tool(self, input_data) -> dict:
        tool, tool_input = input_data["tool_name"], input_data.get("tool_input") or {}
        if tool == _QUESTION_TOOL:
            return _verdict("ask", "question")  # la reponse passe par can_use_tool
        decision = decide(tool, tool_input, self._project)
        if decision is Decision.ALLOW:
            return _verdict("allow")
        if decision is Decision.DENY:
            return _verdict("deny", "Action interdite par la politique de Dr Vocal.")
        if (tool, tool_input) in self._approved:
            self._approved.remove((tool, tool_input))
            return _verdict("allow")
        summary = _summary(tool, tool_input)
        reply = await self._ask(f"{_spoken(summary)}. Dis oui docteur pour autoriser.")
        if reply is Reply.APPROVE:
            return _verdict("allow")
        if reply is Reply.REJECT:
            return _verdict("deny", "L'utilisateur a refuse.")
        self._add_pending(_Pending(summary, tool, tool_input))
        return _verdict("deny", "Pas de reponse de l'utilisateur ; l'action est en attente d'autorisation.")

    async def _can_use_tool(self, tool, tool_input, context):
        try:
            if tool != _QUESTION_TOOL:
                return PermissionResultDeny(message="Outil non autorise par Dr Vocal.")
            text = _question_text(tool_input)
            answer = await self._ask(text)
            if not isinstance(answer, str):
                self._add_pending(_Pending(text))
                return PermissionResultDeny(message=_NO_ANSWER)
            answers = {q["question"]: answer for q in tool_input.get("questions", [])}
            return PermissionResultAllow(updated_input={**tool_input, "answers": answers})
        except Exception as exc:
            self._emit(SessionEvent("error", f"Erreur de la politique : {exc}"))
            return PermissionResultDeny(message="Erreur interne de Dr Vocal.")
