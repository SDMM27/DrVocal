import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from drvocal.claude_registry import Registry, SessionRecord

NOW = datetime(2026, 11, 9, 12, 0, 0)


def _rec(id: str, **kw) -> SessionRecord:
    base = dict(
        id=id, uuid=f"{id}-uuid", project="drvocal", path=r"D:\NasaCode\DrVocal",
        name=f"session {id}", started=NOW, state="done",
    )
    base.update(kw)
    return SessionRecord(**base)


def _registry(path: Path) -> Registry:
    return Registry(path, now=lambda: NOW)


def test_roundtrip(tmp_path):
    path = tmp_path / "sub" / "r.json"
    reg = _registry(path)
    reg.add(_rec("a", state="waiting"))
    reg.add(_rec("b", parent="a", imported=True, path=Path(r"D:\x")))  # type: ignore[arg-type]
    reg.save()
    loaded = _registry(path).records
    assert [r.id for r in loaded] == ["a", "b"]
    assert loaded[0].started == NOW and loaded[0].state == "waiting"
    assert loaded[1].parent == "a" and loaded[1].imported is True
    assert loaded[1].path == r"D:\x"
    assert isinstance(json.loads(path.read_text(encoding="utf-8")), list)
    assert not list(path.parent.glob("*.tmp"))


def test_missing_file_is_empty(tmp_path):
    assert _registry(tmp_path / "none.json").records == []


def test_corrupt_file_is_empty_then_rewritten(tmp_path, caplog):
    path = tmp_path / "r.json"
    path.write_text("{pas du json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        reg = _registry(path)
    assert reg.records == []
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    reg.add(_rec("a"))
    reg.save()
    assert [r.id for r in _registry(path).records] == ["a"]


def test_purge_imported_older_than_7_days(tmp_path):
    path = tmp_path / "r.json"
    old = NOW - timedelta(days=8)
    reg = _registry(path)
    reg.add(_rec("old-imported", started=old, imported=True))
    reg.add(_rec("old-kept", started=old))
    reg.add(_rec("new-imported", started=NOW - timedelta(days=6), imported=True))
    reg.save()
    assert [r.id for r in _registry(path).records] == ["old-kept", "new-imported"]


def test_latest_and_alive(tmp_path):
    reg = _registry(tmp_path / "r.json")
    assert reg.latest() is None
    reg.add(_rec("a", state="running"))
    reg.add(_rec("b", state="done"))
    reg.add(_rec("c", state="waiting"))
    reg.add(_rec("d", state="failed"))
    assert reg.latest().id == "d"  # type: ignore[union-attr]
    assert [r.id for r in reg.alive()] == ["a", "c"]


def test_to_import_excludes_running_imported_and_replaced(tmp_path):
    reg = _registry(tmp_path / "r.json")
    reg.add(_rec("run", state="running"))
    reg.add(_rec("imp", imported=True))
    reg.add(_rec("parent", state="stopped"))
    reg.add(_rec("child", parent="parent", state="waiting"))
    reg.add(_rec("other", state="failed"))
    reg.add(_rec("no-uuid", uuid=""))
    assert [r.id for r in reg.to_import()] == ["child", "other"]


def test_aware_start_date_does_not_crash_the_load(tmp_path, caplog):
    path = tmp_path / "r.json"
    reg = _registry(path)
    reg.add(_rec("a", started=datetime(2026, 11, 1, tzinfo=UTC), imported=True))
    reg.save()
    with caplog.at_level(logging.WARNING):
        assert _registry(path).records == []
    assert any(r.levelno == logging.WARNING for r in caplog.records)
