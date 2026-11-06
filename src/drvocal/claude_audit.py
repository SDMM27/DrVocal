"""Journal d'audit des decisions d'outils de Claude Agent (JSONL, une ligne par decision).

Aucun contenu de fichier ni commande complete : seulement l'outil, la decision, son origine
et une cible tronquee (chemin, ou 60 premiers caracteres d'une commande).
"""
import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_COMMAND_LIMIT = 60
_TARGET_LIMIT = 200
_PATH_KEYS = ("file_path", "notebook_path", "path", "url")


def audit_target(tool: str, tool_input: dict) -> str | None:
    """Cible a journaliser, tronquee ; jamais de contenu."""
    if tool in ("Bash", "PowerShell"):
        command = tool_input.get("command")
        return str(command)[:_COMMAND_LIMIT] if command else None
    for key in _PATH_KEYS:
        value = tool_input.get(key)
        if value:
            return str(value)[:_TARGET_LIMIT]
    if tool == "WebSearch" and tool_input.get("query"):
        return str(tool_input["query"])[:_COMMAND_LIMIT]
    return None


class AuditLog:
    """Ecriture en append ; une erreur d'ecriture est journalisee, jamais propagee."""

    def __init__(self, path: Path | None, now: Callable[[], datetime] = datetime.now):
        self._path = path
        self._now = now

    def record(self, session_id: str | None, tool: str, tool_input: dict, decision: str, origin: str) -> None:
        if self._path is None:
            return
        try:
            entry = {
                "ts": self._now().isoformat(timespec="seconds"),
                "session_id": session_id,
                "tool": tool,
                "decision": decision,  # allow, deny ou ask
                "origin": origin,  # policy, vocal, ecran ou approbation
                "target": audit_target(tool, tool_input),
            }
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            log.exception("ecriture du journal d'audit Claude impossible")
