"""Politique des outils de Claude Code et reponses vocales aux autorisations.

Ces regles reduisent le risque sans le supprimer : une commande autorisee peut
agir au-dela de ce que les motifs reconnaissent. C'est pourquoi toute commande
demande une autorisation, et jamais l'inverse.
"""
import enum
import ntpath
import re
import unicodedata
from pathlib import Path


class Decision(enum.Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class Reply(enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    NONE = "none"


_READ_TOOLS = {"Read": "file_path", "Glob": "path", "Grep": "path"}
_WRITE_TOOLS = {"Edit": "file_path", "Write": "file_path", "NotebookEdit": "notebook_path"}
_COMMAND_TOOLS = {"Bash", "PowerShell"}

# Ecrire ici permettrait de lancer des commandes sans passer par une autorisation.
_EXECUTION_CONFIG = {".claude", ".git", ".mcp.json"}

_DESTRUCTIVE = re.compile(
    r"""
    \brm\s+(?:\S+\s+)*-[a-z]*[rf]
    | \b(?:remove-item|ri|rmdir|rd|del|erase)\b.*(?:\s-r|\s/s)
    | \bformat\s+[a-z]:
    | \b(?:format-volume|clear-disk|diskpart|mkfs)\b
    | \b(?:taskkill|tskill|stop-process|spps|kill|pkill|killall)\b
    | \b(?:shutdown|stop-computer|restart-computer)\b
    | \bgit\s+clean\b
    | \bgit\s+reset\s+--hard\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _within_project(path: str, project: Path) -> str | None:
    """Renvoie le chemin relatif normalise si `path` est dans le projet, sinon None."""
    root = ntpath.normcase(ntpath.normpath(str(project)))
    full = ntpath.normcase(ntpath.normpath(ntpath.join(root, path)))
    if full == root:
        return "."
    if full.startswith(root.rstrip("\\") + "\\"):
        return full[len(root.rstrip("\\")) + 1:]
    return None


def _touches_execution_config(relative: str) -> bool:
    return relative.split("\\")[0] in _EXECUTION_CONFIG


def decide(tool: str, tool_input: dict, project: Path) -> Decision:
    """Decide du sort d'un outil ; tout ce qui n'est pas reconnu demande une autorisation."""
    if tool in _COMMAND_TOOLS:
        command = tool_input.get("command", "")
        return Decision.DENY if _DESTRUCTIVE.search(command) else Decision.ASK

    if tool in _READ_TOOLS:
        pattern = tool_input.get("pattern", "") if tool == "Glob" else ""
        if ".." in pattern or ntpath.isabs(pattern):
            return Decision.ASK
        path = tool_input.get(_READ_TOOLS[tool]) or "."
        return Decision.ALLOW if _within_project(path, project) is not None else Decision.ASK

    if tool in _WRITE_TOOLS:
        path = tool_input.get(_WRITE_TOOLS[tool])
        relative = _within_project(path, project) if path else None
        if relative is None or _touches_execution_config(relative):
            return Decision.ASK
        return Decision.ALLOW

    return Decision.ASK


def parse_reply(text: str) -> Reply:
    """Seule la phrase exacte compte, pour qu'un « oui » adresse a un ami ne valide rien."""
    folded = unicodedata.normalize("NFC", text).casefold()
    words = re.sub(r"[^\w\s]", " ", folded).split()
    if words == ["oui", "docteur"]:
        return Reply.APPROVE
    if words == ["non", "docteur"]:
        return Reply.REJECT
    return Reply.NONE
