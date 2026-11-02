from datetime import datetime

from drvocal.actions_notes import save_note


def test_note_is_saved_verbatim_in_dated_txt(tmp_path):
    p = save_note("acheter du lait", tmp_path, datetime(2026, 11, 2, 21, 30, 5))
    assert p.name == "2026-11-02_21-30-05.txt"
    assert p.read_text(encoding="utf-8") == "acheter du lait"


def test_same_second_never_overwrites(tmp_path):
    now = datetime(2026, 11, 2, 21, 30, 5)
    a, b = save_note("a", tmp_path, now), save_note("b", tmp_path, now)
    assert a != b and a.read_text(encoding="utf-8") == "a"
    assert b.name == "2026-11-02_21-30-05-2.txt"


def test_creates_missing_folder(tmp_path):
    assert save_note("a", tmp_path / "NOTES", datetime.now()).exists()
