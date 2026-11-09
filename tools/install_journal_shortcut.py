"""Cree (ou retire) le raccourci « Journal Dr Vocal » sur le bureau.

    uv run python tools/install_journal_shortcut.py            # cree le raccourci
    uv run python tools/install_journal_shortcut.py --remove   # le retire

Le bureau reel est demande a Windows (il peut etre dans OneDrive). pythonw.exe : pas de console.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHORTCUT_NAME = "Journal Dr Vocal.lnk"
_DESKTOP = "[Environment]::GetFolderPath('Desktop')"


def shortcut_target(root: Path) -> tuple[str, str]:
    """(cible, arguments) du raccourci (fonction pure)."""
    return str(root / ".venv" / "Scripts" / "pythonw.exe"), "-m drvocal.journal"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _powershell(script: str) -> str:
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8", check=True)
    return done.stdout.strip()


def install(root: Path = ROOT) -> str:
    target, arguments = shortcut_target(root)
    script = (
        f"$lnk = Join-Path ({_DESKTOP}) {_ps_quote(SHORTCUT_NAME)}; "
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk); "
        f"$s.TargetPath = {_ps_quote(target)}; $s.Arguments = {_ps_quote(arguments)}; "
        f"$s.WorkingDirectory = {_ps_quote(str(root))}; $s.Description = 'Journal de Dr Vocal'; "
        f"$s.IconLocation = {_ps_quote(target)}; $s.Save(); $lnk"
    )
    return _powershell(script)


def remove() -> bool:
    script = (
        f"$lnk = Join-Path ({_DESKTOP}) {_ps_quote(SHORTCUT_NAME)}; "
        "if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk; 'removed' }"
    )
    return _powershell(script) == "removed"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remove", action="store_true", help="retire le raccourci du bureau")
    args = ap.parse_args()
    if args.remove:
        print("retire" if remove() else "rien a retirer")
    else:
        print(f"cree : {install()}")


if __name__ == "__main__":
    main()
