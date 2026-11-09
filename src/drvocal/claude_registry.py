"""Registre des sessions Claude Code lancees a la voix, garde dans un JSON entre deux demarrages."""
import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

State = Literal["running", "waiting", "done", "stopped", "failed"]

IMPORTED_TTL = timedelta(days=7)


@dataclass
class SessionRecord:
    id: str
    uuid: str
    project: str
    path: str
    name: str
    started: datetime
    state: State
    imported: bool = False
    parent: str | None = None


def _to_json(rec: SessionRecord) -> dict:
    data = asdict(rec)
    data["path"] = str(rec.path)
    data["started"] = rec.started.isoformat()
    return data


def _from_json(raw: dict) -> SessionRecord:
    return SessionRecord(
        id=raw["id"], uuid=raw["uuid"], project=raw["project"], path=raw["path"],
        name=raw["name"], started=datetime.fromisoformat(raw["started"]), state=raw["state"],
        imported=bool(raw.get("imported", False)), parent=raw.get("parent"),
    )


class Registry:
    def __init__(self, path: Path, now: Callable[[], datetime] = datetime.now):
        self._path = path
        self._now = now
        self.records: list[SessionRecord] = self._read()

    def _read(self) -> list[SessionRecord]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("liste attendue")
            records = [_from_json(item) for item in raw]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("registre Claude illisible (%s), liste vide", self._path.name)
            return []
        limit = self._now() - IMPORTED_TTL
        return [r for r in records if not (r.imported and r.started < limit)]

    def add(self, rec: SessionRecord) -> None:
        self.records.append(rec)

    def save(self) -> None:
        tmp = self._path.with_name(self._path.name + ".tmp")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps([_to_json(r) for r in self.records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    def latest(self) -> SessionRecord | None:
        return self.records[-1] if self.records else None

    def alive(self) -> list[SessionRecord]:
        return [r for r in self.records if r.state in ("running", "waiting")]

    def to_import(self) -> list[SessionRecord]:
        replaced = {r.parent for r in self.records if r.parent}
        return [
            r for r in self.records
            if not r.imported and r.state != "running" and r.id not in replaced
        ]
