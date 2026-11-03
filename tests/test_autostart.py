import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "install_autostart", Path(__file__).parent.parent / "tools" / "install_autostart.py"
)
install_autostart = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install_autostart)


def test_autostart_command_uses_pythonw():
    command = install_autostart.autostart_command(Path("D:/Jeux/DrVocal"))
    assert command.endswith(" -m drvocal")
    assert command.startswith('"') and 'pythonw.exe"' in command
    assert str(Path("D:/Jeux/DrVocal") / ".venv" / "Scripts" / "pythonw.exe") in command
