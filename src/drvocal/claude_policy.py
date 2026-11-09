"""Politique des outils de Claude Agent et reponses vocales aux autorisations.

Ces regles reduisent le risque sans le supprimer : une commande autorisee peut
agir au-dela de ce que les motifs reconnaissent. C'est pourquoi toute commande
demande une autorisation, et jamais l'inverse.
"""
import enum
import fnmatch
import ntpath
import os
import re
import unicodedata
from pathlib import Path

from drvocal.projects import validate_project_root  # noqa: F401 (reexport jusqu'a la tache 7)


class Decision(enum.Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class Reply(enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    NONE = "none"


_READ_TOOLS = {"Read": "file_path", "Glob": "path", "Grep": "path"}
_WRITE_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
_COMMAND_TOOLS = {"Bash", "PowerShell"}
# Liste de taches interne a Claude : sans effet externe, ne merite pas d'interrompre la partie.
_INTERNAL_TOOLS = {"TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "ToolSearch"}

# Seuls ces outils peuvent etre autorises a la voix (« oui docteur ») : faible risque, resume fidele.
# Tout le reste (Bash, PowerShell, ecritures, sous-agents, outils MCP...) passe par l'ecran.
VOICE_APPROVABLE_TOOLS = frozenset({"WebSearch", "WebFetch", "Read", "Glob", "Grep"})

# Fichiers qui finissent par etre executes (build, hooks, CI, scripts) : les modifier demande un accord.
_EXECUTED_NAMES = frozenset({
    "package.json", "package-lock.json", "pyproject.toml", "setup.py", "setup.cfg", "makefile", "cmakelists.txt",
    "conftest.py", "claude.md", ".gitattributes", ".gitmodules", "tox.ini", "noxfile.py", "justfile", "dockerfile",
})
_EXECUTED_PATTERNS = (
    "*.ps1", "*.psm1", "*.bat", "*.cmd", "*.vbs", "*.sh", "*.csproj", "*.sln", "*.props", "*.targets", ".env*",
)
_EXECUTED_DIRS = frozenset({".claude", ".github", ".vscode"})

_DESTRUCTIVE = re.compile(
    r"""
    \brm(?:\.exe)?\s+(?:\S+\s+)*-[a-z]*[rf]
    | \brm(?:\.exe)?\s+(?:\S+\s+)*--(?:recursive|force)
    | \brm(?:\.exe)?\s+(?:\S+\s+)*\*
    | \b(?:remove-item|ri|rmdir|rd|del|erase)\b.*(?:\s-r|\s/s|\*)
    | \bfind\b.*\s-delete\b
    | \brimraf\b
    | \bformat(?:\.com)?\s+(?:/\S+\s+)*[a-z]:
    | \b(?:vssadmin|wmic)\b.*\bdelete\b
    | \b(?:format-volume|clear-disk|diskpart|mkfs)\b
    | \b(?:taskkill|tskill|stop-process|spps|kill|pkill|killall)\b
    | \b(?:shutdown|stop-computer|restart-computer)\b
    | \bgit\s+clean\b
    | \bgit\s+reset\s+--hard\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


# Motifs qui peuvent sortir du projet : "..", lecteur, racine, ~, y compris dans une
# alternative {a,/b}. Les crochets ([.][.]/) ne sont pas analyses et demandent un accord.
_GLOB_ESCAPE = re.compile(r"\.\.|:|\[|^[/\\~]|[{,]\s*[/\\~]")


def _is_alias(path: str) -> bool:
    """Formes qui designent sous Windows un autre fichier que leur texte : point ou
    espace final, flux NTFS, nom court 8.3, prefixe de peripherique."""
    drive, tail = ntpath.splitdrive(path)
    if drive.startswith(("\\\\", "//")):
        return True
    if drive and not tail.startswith(("\\", "/")):  # "D:x" depend du dossier courant du lecteur
        return True
    return any(
        part not in (".", "..") and (part != part.rstrip(". ") or ":" in part or "~" in part)
        for part in re.split(r"[\\/]", tail)
    )


def _within_project(path: str, project: Path) -> str | None:
    """Renvoie le chemin relatif reel si `path` est dans le projet, sinon None."""
    if _is_alias(path):
        return None
    root = ntpath.normcase(os.path.realpath(ntpath.normpath(str(project))))
    full = ntpath.normcase(os.path.realpath(ntpath.normpath(ntpath.join(str(project), path))))
    if full == root:
        return "."
    if full.startswith(root.rstrip("\\") + "\\"):
        return full[len(root.rstrip("\\")) + 1:]
    return None


def _touches_execution_config(relative: str) -> bool:
    """Fichiers caches : .claude, .git, .vscode, .husky, .envrc... peuvent lancer des
    commandes sans autorisation. Tous demandent donc un accord, plutot qu'une liste."""
    return any(part.startswith(".") for part in relative.split("\\") if part != ".")


def _is_executed_file(relative: str) -> bool:
    """Chemin relatif (separateur antislash) vers un fichier de build, de script ou de configuration executee."""
    parts = [p.casefold() for p in relative.split("\\") if p and p != "."]
    if not parts:
        return False
    if any(p in _EXECUTED_DIRS for p in parts[:-1]):
        return True
    name = parts[-1]
    return name in _EXECUTED_NAMES or any(fnmatch.fnmatchcase(name, pat) for pat in _EXECUTED_PATTERNS)


def decide(tool: str, tool_input: dict, project: Path) -> Decision:
    """Decide du sort d'un outil ; tout ce qui n'est pas reconnu demande une autorisation."""
    if tool in _INTERNAL_TOOLS:
        return Decision.ALLOW

    if tool in _COMMAND_TOOLS:
        command = tool_input.get("command", "")
        return Decision.DENY if _DESTRUCTIVE.search(command) else Decision.ASK

    if tool in _READ_TOOLS:
        pattern = tool_input.get("pattern", "") if tool == "Glob" else ""
        if _GLOB_ESCAPE.search(pattern):
            return Decision.ASK
        path = tool_input.get(_READ_TOOLS[tool]) or "."
        return Decision.ALLOW if _within_project(path, project) is not None else Decision.ASK

    if tool in _WRITE_TOOLS:
        path = tool_input.get(_WRITE_TOOLS[tool])
        relative = _within_project(path, project) if path else None
        if relative is None or _touches_execution_config(relative) or _is_executed_file(relative):
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
