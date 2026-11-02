from pathlib import Path

import pytest

from drvocal.claude_policy import Decision, Reply, decide, parse_reply

P = Path("D:/proj")


@pytest.mark.parametrize("tool,tool_input", [
    ("Read", {"file_path": "D:/proj/a.py"}),
    ("Read", {"file_path": "a.py"}),
    ("Glob", {"pattern": "*.py"}),
    ("Grep", {"pattern": "x", "path": "D:/proj/src"}),
])
def test_reads_inside_project_allowed(tool, tool_input):
    assert decide(tool, tool_input, P) is Decision.ALLOW


@pytest.mark.parametrize("tool_input", [
    {"file_path": "C:/Users/moi/.ssh/id_rsa"},
    {"file_path": "D:/proj/../secret.txt"},
])
def test_reads_outside_project_ask(tool_input):
    assert decide("Read", tool_input, P) is Decision.ASK


def test_glob_with_outside_path_asks():
    assert decide("Glob", {"pattern": "*", "path": "C:/"}, P) is Decision.ASK


def test_glob_pattern_escaping_project_asks():
    assert decide("Glob", {"pattern": "../**/*"}, P) is Decision.ASK


def test_edit_inside_project_allowed():
    assert decide("Edit", {"file_path": "D:/proj/a.py"}, P) is Decision.ALLOW


def test_project_path_is_case_insensitive():
    assert decide("Edit", {"file_path": "d:\\PROJ\\a.py"}, P) is Decision.ALLOW


def test_edit_outside_project_asks():
    assert decide("Edit", {"file_path": "C:/x.py"}, P) is Decision.ASK


def test_traversal_asks():
    assert decide("Write", {"file_path": "D:/proj/../x.py"}, P) is Decision.ASK


def test_sibling_prefix_asks():
    assert decide("Write", {"file_path": "D:/proj2/x.py"}, P) is Decision.ASK


def test_write_without_path_asks():
    assert decide("Write", {}, P) is Decision.ASK


# Ecrire ces fichiers permettrait d'executer des commandes sans autorisation.
@pytest.mark.parametrize("path", [
    "D:/proj/.claude/settings.json",
    "D:/proj/.claude/settings.local.json",
    "D:/proj/.git/hooks/pre-commit",
    "D:/proj/.mcp.json",
    "D:/PROJ/.GIT/config",
])
def test_writing_execution_config_asks(path):
    assert decide("Write", {"file_path": path}, P) is Decision.ASK


# Windows ouvre le meme fichier sous ces formes : elles ne doivent pas contourner la regle.
@pytest.mark.parametrize("path", [
    "D:/proj/.git./hooks/pre-commit",
    "D:/proj/.git /hooks/pre-commit",
    "D:/proj/.claude./settings.json",
    "D:/proj/.mcp.json.",
    "D:/proj/.git::$INDEX_ALLOCATION/hooks/pre-commit",
    "D:/proj/a.py:flux",
    "D:/proj/GIT~1/hooks/pre-commit",
    "\\\\?\\D:\\proj\\.git\\config",
    "\\\\.\\D:\\proj\\.git\\config",
])
def test_windows_path_aliases_ask(path):
    assert decide("Write", {"file_path": path}, P) is Decision.ASK


def test_symlink_leaving_project_asks(monkeypatch):
    real = "C:\\Users\\moi\\.ssh\\id_rsa"
    monkeypatch.setattr(
        "drvocal.claude_policy.os.path.realpath",
        lambda p: real if p.lower().endswith("lien") else p,
    )
    assert decide("Read", {"file_path": "D:/proj/lien"}, P) is Decision.ASK
    assert decide("Write", {"file_path": "D:/proj/lien"}, P) is Decision.ASK


def test_symlink_to_execution_config_asks(monkeypatch):
    monkeypatch.setattr(
        "drvocal.claude_policy.os.path.realpath",
        lambda p: "D:\\proj\\.git\\config" if p.lower().endswith("lien") else p,
    )
    assert decide("Write", {"file_path": "D:/proj/lien"}, P) is Decision.ASK


@pytest.mark.parametrize("path", [
    "D:/proj/.vscode/tasks.json",
    "D:/proj/.husky/pre-commit",
    "D:/proj/.envrc",
    "D:/proj/src/.idea/x.xml",
])
def test_writing_any_hidden_file_asks(path):
    assert decide("Write", {"file_path": path}, P) is Decision.ASK


def test_drive_relative_path_asks():
    assert decide("Write", {"file_path": "D:x.py"}, P) is Decision.ASK


@pytest.mark.parametrize("pattern", [
    "C:/**", "D:*", "~/**", "/etc/*", "\\\\srv\\x\\*",
    "{/etc,src}/*", "{src,~}/*", "{src, /etc}/*", "{..,src}/*", "[.][.]/*",
])
def test_glob_pattern_outside_project_asks(pattern):
    assert decide("Glob", {"pattern": pattern}, P) is Decision.ASK


@pytest.mark.parametrize("pattern", ["**/*.py", "src/*.{ts,tsx}", "{src,tests}/**"])
def test_glob_pattern_inside_project_allowed(pattern):
    assert decide("Glob", {"pattern": pattern}, P) is Decision.ALLOW


def test_bash_asks():
    assert decide("Bash", {"command": "npm test"}, P) is Decision.ASK


def test_bash_without_command_asks():
    assert decide("Bash", {}, P) is Decision.ASK


def test_unknown_tool_asks():
    assert decide("Foo", {}, P) is Decision.ASK


def test_internal_todo_tool_allowed():
    assert decide("TodoWrite", {"todos": []}, P) is Decision.ALLOW


def test_question_asks():
    assert decide("AskUserQuestion", {"questions": []}, P) is Decision.ASK


@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    "rm -r build",
    "rm -fr build",
    "npm test && rm -rf ~",
    "Remove-Item -Recurse C:\\",
    "remove-item x -recurse -force",
    "ri -r x",
    "del /s x",
    "rd /s /q x",
    "rmdir /s x",
    "format d:",
    "Format-Volume -DriveLetter D",
    "Clear-Disk -Number 1",
    "diskpart",
    "taskkill /im discord.exe",
    "Stop-Process -Name RocketLeague",
    "spps -n discord",
    "kill -9 1234",
    "pkill discord",
    "shutdown /s",
    "Stop-Computer",
    "Restart-Computer",
    "git clean -fdx",
    "git reset --hard",
])
def test_destructive_denied(cmd):
    assert decide("Bash", {"command": cmd}, P) is Decision.DENY


def test_destructive_powershell_tool_denied():
    assert decide("PowerShell", {"command": "Stop-Process -Name cs2"}, P) is Decision.DENY


@pytest.mark.parametrize("cmd", ["npm run format", "git status", "cat formats.txt", "python skill.py"])
def test_harmless_lookalikes_only_ask(cmd):
    assert decide("Bash", {"command": cmd}, P) is Decision.ASK


@pytest.mark.parametrize("text,reply", [
    ("oui docteur", Reply.APPROVE),
    ("Oui, docteur !", Reply.APPROVE),
    ("OUI DOCTEUR.", Reply.APPROVE),
    ("oui", Reply.NONE),
    ("ouais vas-y", Reply.NONE),
    ("", Reply.NONE),
    ("non oui docteur", Reply.NONE),
    ("oui docteur mais non", Reply.NONE),
    ("non docteur", Reply.REJECT),
    ("Non, docteur.", Reply.REJECT),
])
def test_parse_reply(text, reply):
    assert parse_reply(text) is reply
