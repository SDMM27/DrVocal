"""Emplacements des fichiers (config, donnees, journaux, documents) et migration depuis le depot."""
from __future__ import annotations

import ctypes
import logging
import os
import tomllib
import uuid
from ctypes import wintypes
from pathlib import Path

from drvocal.secrets_store import SecretStore

log = logging.getLogger("drvocal.storage")

APP_DIR = "DrVocal"
FOLDERID_DOCUMENTS = "FDD39AD0-238F-46AF-ADB4-6C85480369C7"
SECRETS_FILE = "secrets.toml"
SPOTIFY_CACHE_FILE = ".spotify-cache"
PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # racine du depot quand on tourne depuis un checkout


def _dir(override_env: str, base_env: str, fallback: Path) -> Path:
    override = os.environ.get(override_env)
    path = Path(override) if override else Path(os.environ.get(base_env) or fallback) / APP_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    """%APPDATA%\\DrVocal (config.toml), surchargeable par DRVOCAL_CONFIG_DIR."""
    return _dir("DRVOCAL_CONFIG_DIR", "APPDATA", Path.home() / "AppData" / "Roaming")


def data_dir() -> Path:
    """%LOCALAPPDATA%\\DrVocal (modeles, cache, journaux, secrets chiffres), surchargeable par DRVOCAL_DATA_DIR."""
    return _dir("DRVOCAL_DATA_DIR", "LOCALAPPDATA", Path.home() / "AppData" / "Local")


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_store() -> SecretStore:
    return SecretStore(data_dir() / "secrets")


class _Guid(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


def _known_folder(folder_id: str) -> Path | None:
    """SHGetKnownFolderPath ; None si l'appel echoue (suit la redirection OneDrive)."""
    try:
        guid = _Guid.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
        shell32 = ctypes.WinDLL("shell32")
        ole32 = ctypes.WinDLL("ole32")
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(_Guid), wintypes.DWORD, wintypes.HANDLE,
                                                 ctypes.POINTER(ctypes.c_void_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        out = ctypes.c_void_p()
        status = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out))
        try:
            if status != 0 or not out.value:
                return None
            return Path(ctypes.wstring_at(out.value))
        finally:
            ole32.CoTaskMemFree(out)
    except (OSError, AttributeError, ValueError):
        return None


def documents_dir() -> Path:
    """Dossier Documents de l'utilisateur ; repli sur ~/Documents."""
    return _known_folder(FOLDERID_DOCUMENTS) or Path.home() / "Documents"


def legacy_root() -> Path | None:
    """Racine du depot si on tourne depuis un checkout de drvocal, sinon None."""
    try:
        with (PACKAGE_ROOT / "pyproject.toml").open("rb") as f:
            name = tomllib.load(f).get("project", {}).get("name")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return PACKAGE_ROOT if name == "drvocal" else None


def resolve_data_path(path: Path, legacy: Path | None = None) -> Path:
    """Chemin relatif : data_dir() s'il existe, sinon la racine du depot s'il existe, sinon data_dir()."""
    if path.is_absolute():
        return path
    candidate = data_dir() / path
    if candidate.exists():
        return candidate
    if legacy is not None and (legacy / path).exists():
        return legacy / path
    return candidate


def _import_secrets(source: Path, store: SecretStore) -> bool:
    try:
        with source.open("rb") as f:
            values = {str(k): str(v) for k, v in tomllib.load(f).items()}
        for name, value in values.items():
            store.set(name, value)
        if any(store.get(name) != value for name, value in values.items()):
            raise ValueError("relecture differente")
    except Exception as exc:  # rien n'est supprime : le fichier d'origine reste la source de verite
        log.error("migration de %s impossible (%s), fichier conserve", source.name, type(exc).__name__)
        return False
    source.unlink()
    return True


def _import_spotify_cache(source: Path, store: SecretStore) -> bool:
    try:
        token = source.read_text(encoding="utf-8")
        store.set("spotify_token", token)
        if store.get("spotify_token") != token:
            raise ValueError("relecture differente")
    except Exception as exc:
        log.error("migration de %s impossible (%s), fichier conserve", source.name, type(exc).__name__)
        return False
    source.unlink()
    return True


def migrate_legacy(legacy_root: Path, config_dir: Path, store: SecretStore) -> list[str]:
    """Importe config.toml, secrets.toml et .spotify-cache de l'ancien emplacement ; idempotente.

    Renvoie les noms migres. Un secret en clair n'est supprime qu'apres relecture verifiee dans le store.
    """
    done: list[str] = []
    old_config = legacy_root / "config.toml"
    new_config = config_dir / "config.toml"
    if old_config.is_file() and not new_config.exists():
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            new_config.write_bytes(old_config.read_bytes())
            os.replace(old_config, old_config.with_name("config.toml.migrated"))
            done.append("config.toml")
        except OSError as exc:
            log.error("migration de config.toml impossible (%s)", type(exc).__name__)
    old_secrets = legacy_root / SECRETS_FILE
    if old_secrets.is_file() and _import_secrets(old_secrets, store):
        done.append(SECRETS_FILE)
    old_cache = legacy_root / SPOTIFY_CACHE_FILE
    if old_cache.is_file() and _import_spotify_cache(old_cache, store):
        done.append(SPOTIFY_CACHE_FILE)
    if done:
        log.info("migration depuis %s : %s", legacy_root, ", ".join(done))
    return done
