from drvocal.__main__ import load_config


def test_missing_config_gives_defaults(tmp_path):
    s = load_config(tmp_path)
    assert s.wake_mode == "key" and s.projects == {}


def test_config_and_secrets_are_read_from_root(tmp_path):
    (tmp_path / "config.toml").write_text('wake_mode = "voice"\n', encoding="utf-8")
    (tmp_path / "secrets.toml").write_text('discord_bot_token = "tok"\n', encoding="utf-8")
    s = load_config(tmp_path)
    assert (s.wake_mode, s.discord_bot_token) == ("voice", "tok")
