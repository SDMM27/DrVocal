"""Pilotage de Claude Agent en arriere-plan avec la cle API Anthropic de l'utilisateur (facultatif).

Sans cle, aucune session ne demarre. La politique est appliquee dans un hook PreToolUse, qui
s'execute pour chaque outil (sous-agents compris) meme si une regle utilisateur l'autoriserait
deja. Aucun mode qui contourne les autorisations n'est utilise.
"""
import asyncio
import itertools
import json
import logging
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

from drvocal.claude_audit import AuditLog
from drvocal.claude_policy import VOICE_APPROVABLE_TOOLS, Decision, Reply, decide, validate_project_root

log = logging.getLogger(__name__)

_QUESTION_TOOL = "AskUserQuestion"
_NO_ANSWER = "L'utilisateur n'a pas répondu."


@dataclass(frozen=True)
class _Pending:
    summary: str
    tool: str | None = None  # None : simple question, aucune approbation d'outil
    tool_input: dict | None = None
    screen_only: bool = False  # pas d'autorisation vocale : outil sensible ou texte trop long


@dataclass(frozen=True)
class SessionEvent:
    kind: str  # text, tool, pending, done ou error
    text: str
    question: bool = False  # pending : une question de Claude, pas une autorisation


def env_api_key() -> str | None:
    """Fournisseur de cle par defaut : variable d'environnement ANTHROPIC_API_KEY."""
    return os.environ.get("ANTHROPIC_API_KEY", "").strip() or None


_SUMMARY_KEYS = {
    "WebFetch": ("url",),
    "WebSearch": ("query",),
    "Glob": ("pattern", "path"),
    "Grep": ("pattern", "glob", "path"),
    "Read": ("file_path",),
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "MultiEdit": ("file_path",),
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
        text += "\nPas d'autorisation vocale possible (outil sensible ou texte trop long) : à autoriser sur le deuxième écran."
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
        api_key_provider: Callable[[], str | None] = env_api_key,
        max_turns: int = 30,
        max_budget_usd: float = 2.0,
        max_duration: float = 15 * 60.0,
        audit_path: Path | None = None,
        project_validator: Callable[[Path], str | None] = validate_project_root,
    ):
        """`ask_user(texte, kind)` avec kind valant "approval" ou "question"."""
        self._emit = on_event
        self._ask_user = ask_user
        self._factory = client_factory
        self._ask_timeout = ask_timeout
        self._api_key_provider = api_key_provider
        self._max_turns = max_turns
        self._max_budget_usd = max_budget_usd
        self._max_duration = max_duration
        self._audit = AuditLog(audit_path)
        self._validate_project = project_validator
        self._project: Path | None = None
        self._session_id: str | None = None
        self._ids = itertools.count(1)
        self.pending: dict[str, _Pending] = {}
        self._approved: list[tuple[str, dict]] = []
        self._task: asyncio.Task | None = None  # execution en cours, arretable par stop()
        self._client: Any = None
        self._stopped = False
        self._run_lock = asyncio.Lock()  # une seule execution de Claude a la fois
        # Incremente par stop() : un start/resume demande avant l'arret et encore en file derriere
        # _run_lock ne doit pas relancer Claude apres coup.
        self._generation = 0
        self._ask_lock = asyncio.Lock()  # un seul « oui docteur » attendu a la fois

    async def start(self, project: Path, prompt: str) -> None:
        generation = self._generation
        async with self._run_lock:
            if generation != self._generation:
                return  # arrete pendant l'attente du verrou
            reason = self._validate_project(project)
            if reason:  # defense en profondeur : register_claude filtre deja les projets
                self._emit(SessionEvent("error", reason))
                self._emit(SessionEvent("done", ""))
                return
            self._project, self._session_id = project, None
            self.pending.clear()
            self._approved.clear()
            await self._run(prompt)

    async def resume(self, prompt: str) -> None:
        generation = self._generation
        async with self._run_lock:
            if generation != self._generation:
                return  # arrete pendant l'attente du verrou
            if self._project is None or self._session_id is None:
                self._emit(SessionEvent("error", "Aucune session Claude à reprendre."))
                self._emit(SessionEvent("done", ""))
                return
            await self._run(prompt)

    async def stop(self) -> None:
        """Interrompt l'execution en cours (moins de 2 s), annule les relances en file et oublie
        les approbations accordees et les demandes en attente (aucune ne pourra relancer la session)."""
        self._generation += 1
        self._approved.clear()
        self.pending.clear()
        task = self._task
        if task is None or task.done():
            self._emit(SessionEvent("text", "Aucune session Claude en cours."))
            return
        self._stopped = True
        self._emit(SessionEvent("text", "Claude Agent arrêté."))
        interrupt = getattr(self._client, "interrupt", None)
        if interrupt is not None:
            try:
                await asyncio.wait_for(interrupt(), 1.0)
            except Exception:  # TimeoutError compris : la tache est annulee de toute facon
                pass
        task.cancel()
        await asyncio.wait({task}, timeout=0.5)

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

    # Mode de permission : "dontAsk" + allowed_tools evalue, non retenu. En dontAsk tout ce qui n'est pas
    # pre-approuve est refuse sans appeler can_use_tool, or AskUserQuestion (les questions vocales de Claude)
    # en depend ; et la file d'attente a l'ecran repose sur notre hook, qui refuse puis memorise la demande
    # pour une autorisation ulterieure. On garde donc "default" + hook PreToolUse a echec ferme : toute
    # decision allow/deny vient de decide(), et setting_sources=[] empeche les regles de l'utilisateur.
    def _options(self, api_key: str) -> ClaudeAgentOptions:
        # Le hook doit durer plus longtemps que la question vocale, sinon les deux se courent apres.
        hook = HookMatcher(hooks=[self._pre_tool_use], timeout=self._ask_timeout + 30)  # pyright: ignore[reportArgumentType]
        return ClaudeAgentOptions(
            cwd=self._project,
            env={"ANTHROPIC_API_KEY": api_key},  # le SDK fusionne options.env par-dessus os.environ
            resume=self._session_id,
            permission_mode="default",
            max_turns=self._max_turns,
            max_budget_usd=self._max_budget_usd,
            # Aucune regle utilisateur/projet ne peut autoriser un outil a notre place ;
            # en contrepartie, le CLAUDE.md et les skills de l'utilisateur ne sont pas charges.
            setting_sources=[],
            system_prompt={"type": "preset", "preset": "claude_code"},  # identifiant technique, non visible
            can_use_tool=self._can_use_tool,
            hooks={"PreToolUse": [hook]},
        )

    async def _converse(self, api_key: str, prompt: str) -> None:
        async with self._factory(self._options(api_key)) as client:
            self._client = client
            await client.query(prompt)
            async for message in client.receive_response():
                self._handle(message)

    async def _run(self, prompt: str) -> None:
        """A appeler sous `_run_lock`."""
        api_key = self._api_key_provider()
        if not api_key:
            self._emit(SessionEvent("error", "Claude Agent est désactivé : aucune clé API Anthropic."))
            self._emit(SessionEvent("done", ""))
            return
        granted = list(self._approved)  # approbations valables pour cette execution
        self._stopped = False
        task = self._task = asyncio.create_task(self._converse(api_key, prompt))
        try:
            await asyncio.wait({task}, timeout=self._max_duration)
            if not task.done():
                task.cancel()
                await asyncio.wait({task}, timeout=1.0)
                self._emit(SessionEvent("error", "Claude Agent : durée maximale atteinte, session interrompue."))
            elif task.cancelled():
                if not self._stopped:
                    self._emit(SessionEvent("error", "Claude Agent : session annulée."))
            elif (exc := task.exception()) is not None:  # limite d'usage, processus mort, cle refusee...
                self._emit(SessionEvent("error", str(exc) or type(exc).__name__))
        finally:
            if not task.done():  # l'appelant est annule : la session ne doit pas continuer sans lui
                task.cancel()
            self._task, self._client = None, None
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

    def _log_decision(self, input_data, decision: str, origin: str) -> None:
        """Journal d'audit ; ne doit jamais faire echouer la politique."""
        try:
            tool, tool_input = input_data["tool_name"], input_data.get("tool_input") or {}
            self._audit.record(self._session_id, tool, tool_input, decision, origin)
        except Exception:
            log.exception("journal d'audit Claude impossible")

    async def _pre_tool_use(self, input_data, tool_use_id, context) -> dict:
        try:
            return await self._decide_tool(input_data)
        except Exception as exc:  # echec ferme : dans le doute, l'outil ne tourne pas
            self._emit(SessionEvent("error", f"Erreur de la politique : {exc}"))
            self._log_decision(input_data, "deny", "policy")
            return _verdict("deny", "Erreur interne de Dr Vocal.")

    async def _decide_tool(self, input_data) -> dict:
        tool, tool_input = input_data["tool_name"], input_data.get("tool_input") or {}
        if tool == _QUESTION_TOOL:
            return _verdict("ask", "question")  # la reponse passe par can_use_tool
        if self._project is None:  # aucun outil sans projet ouvert
            self._log_decision(input_data, "deny", "policy")
            return _verdict("deny", "Aucun projet ouvert.")
        decision = decide(tool, tool_input, self._project)
        if decision is Decision.ALLOW:
            self._log_decision(input_data, "allow", "policy")
            return _verdict("allow")
        if decision is Decision.DENY:
            self._log_decision(input_data, "deny", "policy")
            return _verdict("deny", "Action interdite par la politique de Dr Vocal.")
        if (tool, tool_input) in self._approved:
            self._approved.remove((tool, tool_input))
            self._log_decision(input_data, "allow", "approbation")
            return _verdict("allow")
        summary = _summary(tool, tool_input)
        # Approbation vocale seulement pour les outils a faible risque dont le resume se lit fidelement.
        if tool not in VOICE_APPROVABLE_TOOLS or not _fits_voice(summary):
            self._add_pending(_Pending(summary, tool, tool_input, screen_only=True))
            self._log_decision(input_data, "ask", "ecran")
            return _verdict("deny", "Action à autoriser sur le deuxième écran ; en attente.")
        reply = await self._ask(f"{summary}. Dis oui docteur pour autoriser.", "approval")
        if reply is Reply.APPROVE:
            self._log_decision(input_data, "allow", "vocal")
            return _verdict("allow")
        if reply is Reply.REJECT:
            self._log_decision(input_data, "deny", "vocal")
            return _verdict("deny", "L'utilisateur a refusé.")
        self._add_pending(_Pending(summary, tool, tool_input))
        self._log_decision(input_data, "ask", "vocal")
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
