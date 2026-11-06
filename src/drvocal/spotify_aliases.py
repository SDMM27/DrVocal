"""Alias de lecture appris a la voix : nom dit -> uri Spotify, gardes dans un JSON.

Les playlists generees par Spotify (En boucle, Daily Mix...) sont invisibles a l'API en mode
developpement : on ne peut les lire que par leur uri, apprise pendant qu'elles jouent.
"""
import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)


def _clean_name(name: str) -> str:
    return " ".join(name.split())


class Aliases:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._data = self._read()

    def _read(self) -> dict[str, str]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            raw = None
        if not isinstance(raw, dict):
            log.warning("alias Spotify illisibles (%s), liste vide", self._path.name)
            return {}
        return {_clean_name(k): v for k, v in raw.items() if isinstance(v, str) and _clean_name(k)}

    def _write(self) -> None:
        tmp = self._path.with_name(self._path.name + ".tmp")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def items(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._data.items())

    def add(self, name: str, uri: str) -> None:
        name = _clean_name(name)
        if not name:
            return
        with self._lock:
            self._data[name] = uri
            self._write()

    def remove(self, name: str) -> bool:
        name = _clean_name(name)
        with self._lock:
            if name not in self._data:
                return False
            del self._data[name]
            self._write()
            return True
