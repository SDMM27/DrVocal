"""Lance Dr Vocal au demarrage de Windows (cle Run de l'utilisateur, sans droits admin).

    uv run python tools/install_autostart.py            # installe
    uv run python tools/install_autostart.py --remove   # retire

pythonw.exe : pas de console. Le journal est dans drvocal.log dans le dossier LOCALAPPDATA/DrVocal.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DrVocal"


def autostart_command(root: Path) -> str:
    """Commande enregistree dans le registre (fonction pure, sans acces au registre)."""
    return f'"{root / ".venv" / "Scripts" / "pythonw.exe"}" -m drvocal'


def install(root: Path = ROOT) -> str:
    import winreg

    command = autostart_command(root)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    return command


def remove() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remove", action="store_true", help="retire le lancement au demarrage")
    args = ap.parse_args()
    if args.remove:
        print("retire" if remove() else "rien a retirer")
    else:
        print(f"installe : {install()}")


if __name__ == "__main__":
    main()
