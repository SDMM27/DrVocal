from pathlib import Path

import pytest

from drvocal.projects import validate_project_root

ENV = {"APPDATA": "C:/Users/moi/AppData/Roaming", "LOCALAPPDATA": "C:/Users/moi/AppData/Local",
       "SystemRoot": "C:/Windows", "ProgramFiles": "C:/Program Files"}


def check(path, tmp_path, home=None):
    return validate_project_root(path, env=ENV, home=home or Path("C:/Users/moi"))


@pytest.mark.parametrize("path", ["C:/", "D:\\", "C:/Users/moi", "C:/Users/moi/AppData/Roaming",
                                  "C:/Users/moi/AppData/Local", "C:/Windows", "C:/Program Files", "C:/Users",
                                  "C:/Users/moi/AppData", "C:/Windows/System32"])
def test_sensitive_project_roots_refused(path, tmp_path):
    from unittest import mock

    with mock.patch("pathlib.Path.is_dir", return_value=True):
        assert check(path, tmp_path)


def test_real_home_and_missing_and_file_refused(tmp_path):
    assert validate_project_root(Path.home())
    assert validate_project_root(tmp_path / "absent")
    f = tmp_path / "f.txt"
    f.write_text("x")
    assert validate_project_root(f)


def test_normal_project_accepted(tmp_path):
    project = tmp_path / "mon-projet"
    project.mkdir()
    assert validate_project_root(project, env=ENV, home=Path("C:/Users/moi")) is None
