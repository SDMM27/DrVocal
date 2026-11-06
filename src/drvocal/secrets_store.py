"""Stockage chiffre des secrets (DPAPI Windows, portee utilisateur courant), un fichier par nom."""
from __future__ import annotations

import ctypes
import logging
import os
import re
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger("drvocal.secrets")

NAME_RE = re.compile(r"[a-z0-9_]+")
ENTROPY = b"DrVocal secrets v1"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buf = ctypes.create_string_buffer(data, len(data))  # garde la reference tant que le blob sert
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _dpapi(protect_mode: bool, data: bytes) -> bytes:
    """CryptProtectData / CryptUnprotectData avec l'entropie applicative ; OSError en cas d'echec."""
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    pblob = ctypes.POINTER(_Blob)
    source, keep_source = _blob(data)
    entropy, keep_entropy = _blob(ENTROPY)
    out = _Blob()
    if protect_mode:
        call = crypt32.CryptProtectData
        call.argtypes = [pblob, wintypes.LPCWSTR, pblob, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, pblob]
        call.restype = wintypes.BOOL
        ok = call(ctypes.byref(source), "DrVocal", ctypes.byref(entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN,
                  ctypes.byref(out))
    else:
        call = crypt32.CryptUnprotectData
        call.argtypes = [pblob, ctypes.c_void_p, pblob, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, pblob]
        call.restype = wintypes.BOOL
        ok = call(ctypes.byref(source), None, ctypes.byref(entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN,
                  ctypes.byref(out))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))
        del keep_source, keep_entropy


def protect(data: bytes) -> bytes:
    return _dpapi(True, data)


def unprotect(data: bytes) -> bytes:
    return _dpapi(False, data)


class SecretStore:
    """Un fichier chiffre `<nom>.bin` par secret dans `directory`. Les valeurs ne sont jamais journalisees."""

    def __init__(self, directory: Path):
        self.directory = directory

    def _path(self, name: str) -> Path:
        if not NAME_RE.fullmatch(name):
            raise ValueError(f"nom de secret invalide : {name!r}")
        return self.directory / f"{name}.bin"

    def get(self, name: str) -> str | None:
        path = self._path(name)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.warning("secret %s illisible (%s)", name, type(exc).__name__)
            return None
        try:
            return unprotect(raw).decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("secret %s illisible ou corrompu (%s)", name, type(exc).__name__)
            return None

    def set(self, name: str, value: str) -> None:
        path = self._path(name)
        encrypted = protect(value.encode("utf-8"))
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(encrypted)
        os.replace(tmp, path)

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)
