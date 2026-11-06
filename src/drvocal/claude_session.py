"""Pilotage de Claude Code en arriere-plan avec la connexion Pro de l'utilisateur.

La politique est appliquee dans un hook PreToolUse, qui s'execute pour chaque
outil (sous-agents compris) meme si une regle utilisateur l'autoriserait deja.
Aucun mode qui contourne les autorisations n'est utilise.
"""
import asyncio
import itertools
import json
import os
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)

from drvocal.claude_policy import Decision, Reply, decide

_QUESTION_TOOL = "AskUserQuestion"
_NO_ANSWER = "L'utilisateur n'a pas répondu."


@dataclass(frozen=True)
class _Pending:
    summary: str
    tool: str | None = None  # None : simple question, aucune approbation d'outil
    tool_input: dict | None = None
    screen_only: bool = False  # trop long pour une autorisation vocale


@dataclass(frozen=True)
class SessionEvent:
    kind: str  # text, tool, pending, done ou error
    text: str
    question: bool = False  # pending : une question de Claude, pas une autorisation


_FORBIDDEN_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def build_env() -> dict[str, str]:
    """Environnement sans cle API, pour que la facturation reste sur l'abonnement."""
    return {k: v for k, v in os.environ.items() if k not in _FORBIDDEN_ENV}


def scrub_environ() -> None:
    """Retire les cles du processus : le SDK fusionne options.env PAR-DESSUS os.environ,
    donc une cle simplement omise de options.env serait heritee par Claude Code."""
    for key in _FORBIDDEN_ENV:
        os.environ.pop(key, None)


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
_SPOKEN_LIMIT = 200


def _summary(tool: str, tool_input: dict) -> str:
    """Texte complet de ce qui est autorise ; il part tel quel sur le deuxieme ecran."""
    keys = _SUMMARY_KEYS.get(tool)
    if keys:
        details = " ; ".join(f"{k} = {tool_input[k]}" for k in keys if tool_input.get(k))
    else:
        details = json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"Claude veut utiliser {tool} : {details}" if details else f"Claude veut utiliser l'outil {tool}"


def _fits_voice(summary: str, limit: int = _SPOKEN_LIMIT) -> bool:
    """Un texte trop long ou sur plusieurs lignes ne peut pas etre autorise a la voix."""
    if len(summary) > limit:
        return False
    # Cc (retours a la ligne...), Cf (bidi, invisibles), Zl/Zp (U+2028/2029) : texte qu'on ne peut pas dire fidelement.
    return not any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in summary)


def _screen_text(pending_id: str, entry: "_Pending") -> str:
    text = f"{pending_id}: {entry.summary}"
    if entry.tool_input is not None:
        text += "\n" + json.dumps(entry.tool_input, ensure_ascii=False, separators=(",", ":"), default=str)
    if entry.screen_only:
        text += "\nTrop long pour être lu : à autoriser sur le deuxième écran."
    return text


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
        ask_user: Callable[[str, str], Awaitable[Reply | str]],
        client_factory: Callable[[ClaudeAgentOptions], Any] = lambda options: ClaudeSDKClient(options=options),
        ask_timeout: float = 60.0,
    ):
        """`ask_user(texte, kind)` avec kind valant "approval" ou "question"."""
        scrub_environ()
        self._emit = on_event
        self._ask_user = ask_user
        self._factory = client_factory
        self._ask_timeout = ask_timeout
        self._project: Path | None = None
        self._session_id: str | None = None
        self._ids = itertools.count(1)
        self.pending: dict[str, _Pending] = {}
        self._approved: list[tuple[str, dict]] = []
        self._run_lock = asyncio.Lock()  # une seule execution de Claude a la fois
        self._ask_lock = asyncio.Lock()  # un seul « oui docteur » attendu a la fois

    async def start(self, project: Path, prompt: str) -> None:
        async with self._run_lock:
            self._project, self._session_id = project, None
            self.pending.clear()
            self._approved.clear()
            await self._run(prompt)

    async def resume(self, prompt: str) -> None:
        async with self._run_lock:
            if self._project is None or self._session_id is None:
                self._emit(SessionEvent("error", "Aucune session Claude à reprendre."))
                self._emit(SessionEvent("done", ""))
                return
            await self._run(prompt)

    async def resolve_pending(self, pending_id: str, reply: Reply) -> bool:
        """Traite une demande restee sans reponse ; une approbation relance la session."""
        entry = self.pending.get(pending_id)
        if entry is None:
            return False
        if reply is Reply.APPROVE and (self._project is None or self._session_id is None):
            return False  # session pas encore reprenable : la demande reste en attente
        del self.pending[pending_id]
        if reply is Reply.APPROVE:
            if entry.tool is None:
                await self.resume(f"L'utilisateur n'a pas pu répondre à : {entry.summary}. Reformule ou continue.")
            else:
                self._approved.append((entry.tool, entry.tool_input or {}))  # une seule fois
                await self.resume(f"L'utilisateur autorise : {entry.summary}. Tu peux réessayer cette action.")
        return True

    def _add_pending(self, entry: _Pending) -> None:
        pending_id = f"p{next(self._ids)}"
        self.pending[pending_id] = entry
        self._emit(SessionEvent("pending", _screen_text(pending_id, entry), question=entry.tool is None))

    def _options(self) -> ClaudeAgentOptions:
        # Le hook doit durer plus longtemps que la question vocale, sinon les deux se courent apres.
        hook = HookMatcher(hooks=[self._pre_tool_use], timeout=self._ask_timeout + 30)  # pyright: ignore[reportArgumentType]
        return ClaudeAgentOptions(
            cwd=self._project,
            env=build_env(),
            resume=self._session_id,
            permission_mode="default",
            # Aucune regle utilisateur/projet ne peut autoriser un outil a notre place ;
            # en contrepartie, le CLAUDE.md et les skills de l'utilisateur ne sont pas charges.
            setting_sources=[],
            system_prompt={"type": "preset", "preset": "claude_code"},
            can_use_tool=self._can_use_tool,
            hooks={"PreToolUse": [hook]},
        )

    async def _run(self, prompt: str) -> None:
        """A appeler sous `_run_lock`."""
        scrub_environ()
        granted = list(self._approved)  # approbations valables pour cette execution
        try:
            async with self._factory(self._options()) as client:
                await client.query(prompt)
                async for message in client.receive_response():
                    self._handle(message)
        except Exception as exc:  # limite d'usage, processus mort, connexion expiree...
            self._emit(SessionEvent("error", str(exc) or type(exc).__name__))
        finally:
            # Une approbation ne vaut que pour l'execution qui l'a suivie ; celles donnees
            # pendant celle-ci (execution suivante en file) sont conservees.
            self._approved[:] = [a for a in self._approved if not any(a is g for g in granted)]
        self._emit(SessionEvent("done", ""))

    def _handle(self, message: object) -> None:
        if isinstance(message, SystemMessage):
            if message.subtype == "init":
                self._session_id = (message.data or {}).get("session_id") or self._session_id
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    self._emit(SessionEvent("text", block.text))
                elif isinstance(block, ToolUseBlock):
                    self._emit(SessionEvent("tool", block.name))
        elif isinstance(message, ResultMessage):
            self._session_id = message.session_id or self._session_id
            if message.is_error:
                self._emit(SessionEvent("error", message.result or "; ".join(message.errors or []) or message.subtype))

    async def _serialized_ask(self, text: str, kind: str) -> Reply | str:
        async with self._ask_lock:
            return await self._ask_user(text, kind)

    async def _ask(self, text: str, kind: str) -> Reply | str:
        """Une seule question a la fois ; l'attente du tour compte dans le delai total."""
        try:
            return await asyncio.wait_for(self._serialized_ask(text, kind), self._ask_timeout)
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
        if self._project is None:  # aucun outil sans projet ouvert
            return _verdict("deny", "Aucun projet ouvert.")
        decision = decide(tool, tool_input, self._project)
        if decision is Decision.ALLOW:
            return _verdict("allow")
        if decision is Decision.DENY:
            return _verdict("deny", "Action interdite par la politique de Dr Vocal.")
        if (tool, tool_input) in self._approved:
            self._approved.remove((tool, tool_input))
            return _verdict("allow")
        summary = _summary(tool, tool_input)
        if not _fits_voice(summary):
            self._add_pending(_Pending(summary, tool, tool_input, screen_only=True))
            return _verdict("deny", "Action trop longue pour une autorisation vocale ; en attente sur le deuxième écran.")
        reply = await self._ask(f"{summary}. Dis oui docteur pour autoriser.", "approval")
        if reply is Reply.APPROVE:
            return _verdict("allow")
        if reply is Reply.REJECT:
            return _verdict("deny", "L'utilisateur a refusé.")
        self._add_pending(_Pending(summary, tool, tool_input))
        return _verdict("deny", "Pas de réponse de l'utilisateur ; l'action est en attente d'autorisation.")

    async def _can_use_tool(self, tool, tool_input, context):
        try:
            if tool != _QUESTION_TOOL:
                return PermissionResultDeny(message="Outil non autorisé par Dr Vocal.")
            text = _question_text(tool_input)
            if not _fits_voice(text):  # trop long pour etre dit en entier
                self._add_pending(_Pending(text, screen_only=True))
                return PermissionResultDeny(message=_NO_ANSWER)
            answer = await self._ask(text, "question")
            if not isinstance(answer, str) or not answer.strip():
                self._add_pending(_Pending(text))
                return PermissionResultDeny(message=_NO_ANSWER)
            answers = {q["question"]: answer for q in tool_input.get("questions", [])}
            return PermissionResultAllow(updated_input={**tool_input, "answers": answers})
        except Exception as exc:
            self._emit(SessionEvent("error", f"Erreur de la politique : {exc}"))
            return PermissionResultDeny(message="Erreur interne de Dr Vocal.")
