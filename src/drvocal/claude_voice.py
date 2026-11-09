"""Regles vocales des sessions Claude Code en arriere-plan : lancer, continuer, arreter, importer, surveiller."""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from drvocal.claude_cli import ClaudeCli, ClaudeCliError, session_name
from drvocal.claude_registry import Registry, SessionRecord

log = logging.getLogger(__name__)

WORKING: frozenset[tuple[str, str | None]] = frozenset({("busy", "working")})
AGENTS_ATTEMPTS = 3
AGENTS_RETRY_DELAY = 1.0


class ClaudeVoice:
    def __init__(
        self,
        cli: ClaudeCli,
        registry: Registry,
        projects: dict[str, Path],
        notify: Callable[[str], None],
        error: Callable[[str], None],
        play: Callable[[str], None],
        working: frozenset[tuple[str, str | None]] = WORKING,
        interval: float = 5.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._cli = cli
        self._registry = registry
        self._projects = projects
        self._notify = notify
        self._error = error
        self._play = play
        self._working = working
        self._interval = interval
        self._sleep = sleep
        self._launching: set[str] = set()
        self._task: asyncio.Task[None] | None = None

    async def prompt(self, project: str, text: str) -> bool:
        path = self._projects.get(project)
        if path is None:
            return False
        if self._is_busy(project):
            self._error(f"Claude travaille déjà sur {project}.")
            return False
        self._launching.add(project)
        try:
            name = session_name(project, text)
            try:
                short_id = await self._cli.launch(path, name, text)
            except ClaudeCliError as exc:
                self._error(str(exc))
                return False
            uuid = await self._find_uuid(short_id)
            self._registry.add(SessionRecord(
                id=short_id, uuid=uuid, project=project, path=str(path), name=name,
                started=datetime.now(), state="running",
            ))
            self._registry.save()
        finally:
            self._launching.discard(project)
        self._notify(f"{name} : lancée")
        self._ensure_watch()
        return True

    async def proceed(self, text: str) -> bool:
        rec = self._registry.latest()
        if rec is None:
            return False
        if rec.imported:
            self._error("Déjà dans l'app, continue là-bas.")
            return False
        if rec.state == "running" or self._is_busy(rec.project):
            self._error("Claude travaille encore.")
            return False
        self._launching.add(rec.project)
        try:
            try:
                if rec.state == "waiting":
                    await self._cli.stop(rec.id)
                short_id = await self._cli.launch(Path(rec.path), rec.name, text, resume=rec.uuid)
            except ClaudeCliError as exc:
                self._error(str(exc))
                return False
            if short_id == rec.id:
                rec.state = "running"
            else:
                self._registry.add(SessionRecord(
                    id=short_id, uuid=await self._find_uuid(short_id), project=rec.project, path=rec.path,
                    name=rec.name, started=datetime.now(), state="running", parent=rec.id,
                ))
            self._registry.save()
        finally:
            self._launching.discard(rec.project)
        self._ensure_watch()
        return True

    async def stop(self) -> bool:
        alive = self._registry.alive()
        if not alive:
            return True
        rec = alive[-1]
        try:
            await self._cli.stop(rec.id)
        except ClaudeCliError as exc:
            self._error(str(exc))
            return False
        rec.state = "stopped"
        self._registry.save()
        self._notify(f"{rec.name} : arrêtée")
        return True

    def import_all(self) -> bool:
        ok = True
        for rec in self._registry.records:
            if rec.state == "running" and not rec.imported:
                self._notify(f"{rec.name} : encore en cours, à importer plus tard")
        for rec in self._registry.to_import():
            try:
                self._cli.open_import(rec.uuid)
            except (ClaudeCliError, OSError) as exc:
                log.warning("import de %s impossible : %s", rec.id, exc)
                self._error(str(exc) if isinstance(exc, ClaudeCliError) else f"Impossible d'ouvrir Claude Code : {exc}")
                ok = False
                continue
            rec.imported = True
        self._registry.save()
        return ok

    async def poll_once(self) -> None:
        try:
            agents = {a.id: a for a in await self._cli.agents()}
        except ClaudeCliError as exc:
            log.warning("liste des sessions Claude illisible : %s", exc)
            return
        changed = False
        for rec in self._registry.alive():
            agent = agents.get(rec.id)
            if agent is None:
                rec.state = "stopped"
                changed = True
                continue
            if not rec.uuid and agent.uuid:
                rec.uuid = agent.uuid
                changed = True
            if (agent.status, agent.state) in self._working:
                continue
            if agent.status == "idle":
                rec.state = "done"
                self._play("done")
                self._notify(f"{rec.name} : finie")
                try:
                    await self._cli.stop(rec.id)
                except ClaudeCliError as exc:
                    log.warning("arret de %s impossible : %s", rec.id, exc)
                changed = True
            elif rec.state != "waiting":
                rec.state = "waiting"
                self._play("done")
                self._notify(f"{rec.name} : attend ta réponse")
                changed = True
        if changed:
            self._registry.save()

    def start(self) -> None:
        pending = len(self._registry.to_import())
        if pending:
            self._notify(f"{pending} session{'s' if pending > 1 else ''} Claude à importer")
        self._ensure_watch()

    def _is_busy(self, project: str) -> bool:
        return project in self._launching or any(
            r.project == project and r.state == "running" for r in self._registry.records
        )

    async def _find_uuid(self, short_id: str) -> str:
        for attempt in range(AGENTS_ATTEMPTS):
            if attempt:
                await self._sleep(AGENTS_RETRY_DELAY)
            try:
                for agent in await self._cli.agents():
                    if agent.id == short_id:
                        return agent.uuid
            except ClaudeCliError as exc:
                log.warning("liste des sessions Claude illisible : %s", exc)
        return ""

    def _ensure_watch(self) -> None:
        if self._registry.alive() and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        while self._registry.alive():
            try:
                await self.poll_once()
            except Exception:
                log.exception("surveillance des sessions Claude en echec")
            await self._sleep(self._interval)
