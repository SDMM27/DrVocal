import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "install_journal_shortcut", Path(__file__).parent.parent / "tools" / "install_journal_shortcut.py"
)
install_journal_shortcut = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install_journal_shortcut)


def test_shortcut_target_and_arguments():
    target, arguments = install_journal_shortcut.shortcut_target(Path("D:/Jeux/DrVocal"))
    assert target == str(Path("D:/Jeux/DrVocal") / ".venv" / "Scripts" / "pythonw.exe")
    assert arguments == "-m drvocal.journal"
