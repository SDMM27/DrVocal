import json
import logging

from drvocal.spotify_aliases import Aliases


def test_roundtrip_and_replace(tmp_path):
    path = tmp_path / "sub" / "a.json"
    a = Aliases(path)
    a.add("  En   boucle ", "spotify:playlist:1")
    a.add("Sport", "spotify:playlist:2")
    a.add("En boucle", "spotify:playlist:3")
    assert Aliases(path).items() == [("En boucle", "spotify:playlist:3"), ("Sport", "spotify:playlist:2")]
    assert json.loads(path.read_text(encoding="utf-8"))["Sport"] == "spotify:playlist:2"
    assert not list(path.parent.glob("*.tmp"))


def test_remove(tmp_path):
    a = Aliases(tmp_path / "a.json")
    a.add("Sport", "spotify:playlist:2")
    assert a.remove(" Sport ") is True
    assert a.remove("Sport") is False
    assert Aliases(tmp_path / "a.json").items() == []


def test_missing_file_is_empty(tmp_path):
    assert Aliases(tmp_path / "none.json").items() == []


def test_corrupt_file_is_empty_with_warning(tmp_path, caplog):
    path = tmp_path / "a.json"
    path.write_text("{pas du json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert Aliases(path).items() == []
    assert "illisibles" in caplog.text
