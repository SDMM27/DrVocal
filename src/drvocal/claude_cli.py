"""Couche mince autour de l'executable `claude` (Claude Code) : sessions en arriere-plan."""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

LAUNCH_TIMEOUT = 30.0
SESSION_NAME_MAX = 50

Runner = Callable[[list[str], Path | None, float], Awaitable[tuple[int, str]]]

_BACKGROUNDED = re.compile(r"backgrounded\s+·\s+([0-9a-zA-Z]+)")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class ClaudeCliError(Exception):
    """Echec de l'appel a Claude Code ; le message est pret a etre affiche."""


@dataclass(frozen=True)
class AgentInfo:
    id: str
    uuid: str
    cwd: str
    status: str
    state: str | None


def parse_backgrounded(output: str) -> str | None:
    match = _BACKGROUNDED.search(output)
    return match.group(1) if match else None


def parse_agents(output: str) -> list[AgentInfo]:
    try:
        data = json.loads(output)
    except ValueError as exc:
        raise ClaudeCliError("Claude Code a renvoyé une liste illisible.") from exc
    if not isinstance(data, list):
        raise ClaudeCliError("Claude Code a renvoyé une liste illisible.")
    agents = []
    for entry in data:
        if not isinstance(entry, dict) or entry.get("kind") != "background" or not entry.get("id"):
            continue
        agents.append(AgentInfo(
            id=str(entry["id"]),
            uuid=str(entry.get("sessionId", "")),
            cwd=str(entry.get("cwd", "")),
            status=str(entry.get("status", "")),
            state=entry.get("state"),
        ))
    return agents


def session_name(project: str, prompt: str) -> str:
    name = f"{project} – {' '.join(prompt.split())}"
    if len(name) <= SESSION_NAME_MAX:
        return name
    cut = name[:SESSION_NAME_MAX]
    if name[SESSION_NAME_MAX] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip()


async def _run(args: list[str], cwd: Path | None, timeout: float) -> tuple[int, str]:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, creationflags=flags,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out.decode("utf-8", errors="replace")


class ClaudeCli:
    def __init__(self, exe: str, run: Runner = _run):
        self._exe = exe
        self._run = run

    async def _call(self, args: list[str], cwd: Path | None, timeout: float) -> tuple[int, str]:
        try:
            return await self._run(args, cwd, timeout)
        except TimeoutError as exc:
            raise ClaudeCliError("Claude Code n'a pas répondu à temps.") from exc
        except OSError as exc:
            raise ClaudeCliError(f"Impossible de lancer Claude Code : {exc}") from exc

    async def launch(self, cwd: Path, name: str, prompt: str, resume: str | None = None) -> str:
        if resume:
            # Aucune autre option : sinon la CLI demarre une copie sous un nouvel identifiant.
            args = [self._exe, "--bg", "--resume", resume, "--", prompt]
        else:
            args = [self._exe, "--bg", "--permission-mode", "auto", "-n", name, "--", prompt]
        code, out = await self._call(args, cwd, LAUNCH_TIMEOUT)
        if "Workspace not trusted" in out:
            raise ClaudeCliError("Ouvre une fois Claude Code dans ce dossier pour lui faire confiance.")
        if code != 0:
            raise ClaudeCliError(f"Claude Code a échoué (code {code}).")
        short_id = parse_backgrounded(out)
        if short_id is None:
            raise ClaudeCliError("Claude Code n'a pas donné d'identifiant de session.")
        return short_id

    async def agents(self) -> list[AgentInfo]:
        code, out = await self._call([self._exe, "agents", "--json"], None, LAUNCH_TIMEOUT)
        if code != 0:
            raise ClaudeCliError(f"Claude Code a échoué (code {code}).")
        return parse_agents(out)

    async def stop(self, short_id: str) -> None:
        code, _ = await self._call([self._exe, "stop", short_id], None, LAUNCH_TIMEOUT)
        if code != 0:
            raise ClaudeCliError(f"Claude Code n'a pas pu arrêter la session (code {code}).")

    def open_import(self, uuid: str) -> None:
        if not _UUID.fullmatch(uuid):
            raise ClaudeCliError("Identifiant de session invalide.")
        os.startfile(f"claude://resume?session={uuid}")


def find_claude(configured: str | None) -> str | None:
    if configured and Path(configured).exists():
        return configured
    return shutil.which("claude")
