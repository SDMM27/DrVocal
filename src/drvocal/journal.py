"""Fenetre « Dr Vocal — journal » : ce que Dr Vocal a entendu, compris et fait (lecture seule).

`python -m drvocal.journal` ouvre la fenetre. La lecture du journal (`read_entries`,
`wav_path`) n'a pas besoin de pywebview ; la fenetre n'est importee qu'a l'ouverture.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from drvocal.actions import Catalogue, Outcome
from drvocal.intent import Intent
from drvocal.storage import data_dir

log = logging.getLogger(__name__)

_PAGE = Path(__file__).with_name("journal.html")
_WAV_NAME = re.compile(r"^[\w.-]+\.wav$")
_MUTEX_NAME = "Local\\DrVocalJournal"
_ERROR_ALREADY_EXISTS = 183
_EVENT_KINDS = ("wake_rejected", "no_speech")
TITLE = "Dr Vocal — journal"


def _kind(row: dict) -> str | None:
    event = row.get("event")
    if event is not None:
        return event if event in _EVENT_KINDS else None  # evenement inconnu : ignore
    ok = row.get("ok")
    if ok is None:
        return "not_understood"
    return "ok" if ok else "failed"


def read_entries(commands_dir: Path, limit: int = 500) -> list[dict]:
    """Les `limit` lignes les plus recentes (la plus recente d'abord), chacune avec un `kind`."""
    rows: list[dict] = []
    for name in ("commands.1.jsonl", "commands.jsonl"):
        try:
            text = (commands_dir / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in text.splitlines():
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            kind = _kind(row)
            if kind is not None:
                rows.append({**row, "kind": kind})
    return rows[-limit:][::-1] if limit > 0 else []


def wav_path(commands_dir: Path, name: object) -> Path | None:
    """Chemin d'un WAV d'echec, uniquement s'il est directement dans `failures/` et existe."""
    if not isinstance(name, str) or not _WAV_NAME.fullmatch(name):
        return None
    path = commands_dir / "failures" / name
    return path if path.is_file() else None


def launch_journal() -> None:
    """Ouvre la fenetre dans un processus detache (sans console) ; leve OSError si impossible."""
    exe = Path(sys.executable).with_name("pythonw.exe")
    if not exe.exists():
        exe = Path(sys.executable)
    root = Path(__file__).resolve().parents[2]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # pyright: ignore[reportAttributeAccessIssue]
    subprocess.Popen([str(exe), "-m", "drvocal.journal"], cwd=root if root.is_dir() else None,
                     creationflags=flags, close_fds=True)


def register_journal(catalogue: Catalogue, launch: Callable[[], None] = launch_journal) -> None:
    async def open_journal(_: Intent) -> Outcome:
        try:
            launch()
        except OSError:
            log.exception("ouverture du journal impossible")
            return Outcome(False)
        return Outcome(True)

    catalogue.register("journal.open", open_journal)


class _Bridge:
    """Seul objet expose a la page."""

    def __init__(self, commands_dir: Path) -> None:
        self._dir = commands_dir

    def entries(self) -> list[dict]:
        return read_entries(self._dir)

    def play(self, name) -> None:
        path = wav_path(self._dir, name)
        if path is None:
            return
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)


def _already_open() -> bool:
    """Instance unique : mutex nomme Windows, garde ouvert jusqu'a la fin du processus."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    return ctypes.get_last_error() == _ERROR_ALREADY_EXISTS


def main() -> int:
    if _already_open():
        return 0
    import webview  # import tardif : lourd, et inutile pour les tests

    webview.create_window(
        TITLE,
        html=_PAGE.read_text(encoding="utf-8"),
        js_api=_Bridge(data_dir() / "commands"),
        width=900, height=600, resizable=True,
    )
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
