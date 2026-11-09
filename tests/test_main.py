import logging
import subprocess
import sys

from drvocal.__main__ import check, load_config, setup_logging
from drvocal.secrets_store import SecretStore


def test_missing_config_gives_defaults(tmp_path):
    s = load_config(tmp_path, SecretStore(tmp_path / "s"))
    assert s.wake_mode == "key" and s.projects == {}


def test_config_from_directory_and_secrets_from_store(tmp_path):
    (tmp_path / "config.toml").write_text('wake_mode = "voice"\n', encoding="utf-8")
    store = SecretStore(tmp_path / "s")
    store.set("discord_bot_token", "tok")
    s = load_config(tmp_path, store)
    assert (s.wake_mode, s.discord_bot_token) == ("voice", "tok")


def test_debug_log_never_contains_spotify_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("DRVOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DRVOCAL_LOG_LEVEL", "DEBUG")
    path = setup_logging()
    try:
        logging.getLogger("drvocal.app").debug("transcription : mets daft punk")
        logging.getLogger("spotipy.client").debug("Headers: {'Authorization': 'Bearer SECRET'}")
        logging.getLogger("urllib3.connectionpool").debug("GET /v1/search?q=daft")
        for h in logging.getLogger().handlers:
            h.flush()
        text = path.read_text(encoding="utf-8")
    finally:
        logging.basicConfig(force=True)
        for h in logging.getLogger().handlers:
            h.close()
    assert path.parent == tmp_path / "logs"
    assert "mets daft punk" in text
    assert "SECRET" not in text and "/v1/search" not in text


def _isolated_env(tmp_path):
    import os
    env = dict(os.environ)
    env.update(DRVOCAL_CONFIG_DIR=str(tmp_path / "cfg"), DRVOCAL_DATA_DIR=str(tmp_path / "data"))
    return env


def test_check_flag_runs_from_any_directory(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    done = subprocess.run([sys.executable, "-m", "drvocal", "--check"], cwd=work, env=_isolated_env(tmp_path),
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    assert str(tmp_path / "cfg") in done.stdout and str(tmp_path / "data") in done.stdout
    assert "spotify_token : non" in done.stdout


def test_check_reports_invalid_config(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "config.toml").write_text("schema_version = 99\n", encoding="utf-8")
    monkeypatch.setenv("DRVOCAL_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("DRVOCAL_DATA_DIR", str(tmp_path / "data"))
    assert check() == 1
    assert "invalide" in capsys.readouterr().out


def test_check_never_prints_secret_values(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DRVOCAL_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("DRVOCAL_DATA_DIR", str(tmp_path / "data"))
    store = SecretStore(tmp_path / "data" / "secrets")
    store.set("discord_bot_token", "VALEUR-SECRETE")
    assert check(store) == 0
    out = capsys.readouterr().out
    assert "discord_bot_token : oui" in out and "VALEUR-SECRETE" not in out


def _claude_settings(settings, projects):
    from dataclasses import replace

    return replace(settings, projects=projects)


def test_no_claude_voice_without_claude_code(settings, monkeypatch, tmp_path):
    import drvocal.claude_cli as claude_cli
    from drvocal.__main__ import _make_claude_voice

    monkeypatch.setattr(claude_cli, "find_claude", lambda configured: None)
    assert _make_claude_voice(_claude_settings(settings, {"p": tmp_path}), object(), lambda e: None) is None


def test_no_claude_voice_without_valid_project(settings, monkeypatch, tmp_path):
    import drvocal.claude_cli as claude_cli
    from drvocal.__main__ import _make_claude_voice

    monkeypatch.setattr(claude_cli, "find_claude", lambda configured: "claude.exe")
    projects = {"absent": tmp_path / "absent"}
    assert _make_claude_voice(_claude_settings(settings, projects), object(), lambda e: None) is None
    assert _make_claude_voice(_claude_settings(settings, {}), object(), lambda e: None) is None


def test_claude_voice_is_built_and_started_with_valid_projects(settings, monkeypatch, tmp_path):
    import drvocal.claude_cli as claude_cli
    import drvocal.claude_voice as claude_voice
    from drvocal.__main__ import _make_claude_voice

    built = []

    class FakeVoice:
        def __init__(self, cli, registry, projects, notify, error, play):
            built.append((cli, registry, projects, notify, error, play))
            self.started = False

        def start(self):
            self.started = True

    class Player:
        def play(self, name):
            pass

    project = tmp_path / "projet"
    project.mkdir()
    monkeypatch.setenv("DRVOCAL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(claude_cli, "find_claude", lambda configured: "claude.exe")
    monkeypatch.setattr(claude_voice, "ClaudeVoice", FakeVoice)
    pushed = []
    voice = _make_claude_voice(
        _claude_settings(settings, {"ok": project, "absent": tmp_path / "absent"}), Player(), pushed.append)
    assert isinstance(voice, FakeVoice) and voice.started
    (_, _, projects, notify, error, _), = built
    assert projects == {"ok": project}
    notify("a")
    error("b")
    assert [(e.kind, e.text) for e in pushed] == [("text", "a"), ("error", "b")]
