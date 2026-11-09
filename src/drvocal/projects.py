"""Validation des dossiers de projet ouverts par Dr Vocal."""
import ntpath
import os
from collections.abc import Mapping
from pathlib import Path


def _comparable(path: str | Path) -> str:
    return ntpath.normcase(os.path.realpath(ntpath.normpath(str(path))))


def _is_or_contains(candidate: str, protected: str) -> bool:
    """Vrai si `candidate` est `protected` ou un de ses ancetres."""
    candidate, protected = candidate.rstrip("\\"), protected.rstrip("\\")
    return protected == candidate or protected.startswith(candidate + "\\")


def validate_project_root(
    path: str | Path, env: Mapping[str, str] | None = None, home: Path | None = None
) -> str | None:
    """Raison du refus d'un dossier de projet, ou None s'il est acceptable.

    Refuse un dossier inexistant, une racine de lecteur, le dossier personnel, AppData,
    Windows, Program Files et tout dossier qui contient l'un d'eux. `env` et `home` sont
    injectables pour les tests."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    p = Path(path)
    if not p.is_dir():
        return f"Le dossier du projet n'existe pas : {path}"
    here = _comparable(p)
    if not ntpath.splitdrive(here)[1].strip("\\/"):
        return f"Un lecteur entier ne peut pas être un projet : {path}"
    protected = [str(home)]
    protected += [env[k] for k in ("APPDATA", "LOCALAPPDATA") if env.get(k)]
    # Dossiers systeme : eux-memes, leurs ancetres, et tout ce qu'ils contiennent.
    system = [env[k] for k in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)") if env.get(k)]
    system += [r"C:\Windows", r"C:\Program Files", r"C:\Program Files (x86)"]
    for prot in protected + system:
        if _is_or_contains(here, _comparable(prot)):
            return f"Dossier de projet trop sensible : {path}"
    for prot in system:
        root = _comparable(prot).rstrip("\\")
        if here.startswith(root + "\\"):
            return f"Dossier de projet dans un dossier système : {path}"
    return None
