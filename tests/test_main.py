import logging

from drvocal.__main__ import load_config, setup_logging


def test_missing_config_gives_defaults(tmp_path):
    s = load_config(tmp_path)
    assert s.wake_mode == "key" and s.projects == {}


def test_config_and_secrets_are_read_from_root(tmp_path):
    (tmp_path / "config.toml").write_text('wake_mode = "voice"\n', encoding="utf-8")
    (tmp_path / "secrets.toml").write_text('discord_bot_token = "tok"\n', encoding="utf-8")
    s = load_config(tmp_path)
    assert (s.wake_mode, s.discord_bot_token) == ("voice", "tok")


def test_debug_log_never_contains_spotify_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
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
    assert "mets daft punk" in text
    assert "SECRET" not in text and "/v1/search" not in text
