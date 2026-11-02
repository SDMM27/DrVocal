from pathlib import Path

import pytest

from drvocal.config import ConfigError, load_settings


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def empty_config(tmp_path: Path) -> Path:
    return write_config(tmp_path, "")


def test_defaults_notes_dir_to_documents_notes(tmp_path):
    s = load_settings(write_config(tmp_path, ""))
    assert s.notes_dir == Path.home() / "Documents" / "NOTES"


def test_default_wake_phrases(tmp_path):
    assert set(load_settings(empty_config(tmp_path)).wake_phrases) == {
        "salut docteur", "bonjour docteur", "bungiorno docteur", "priviet docteur"}


def test_project_names_are_normalised(tmp_path):
    s = load_settings(write_config(tmp_path, '[projects]\n"Dr Vocal" = "D:/NasaCode/DrVocal"'))
    assert s.projects["dr vocal"] == Path("D:/NasaCode/DrVocal")


def test_invalid_toml_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(write_config(tmp_path, "[["))


def test_scalar_defaults(tmp_path):
    s = load_settings(empty_config(tmp_path))
    assert (s.stt_model, s.stt_device, s.second_screen_index) == ("small", "cpu", 1)
    assert s.spotify_client_id == "" and s.discord_bot_token == ""
    assert s.projects == {} and s.discord_hotkeys == {}
    assert s.discord_channels == {} and s.discord_members == {}


def test_secrets_are_loaded(tmp_path):
    secrets = tmp_path / "secrets.toml"
    secrets.write_text('spotify_client_id = "abc"\ndiscord_bot_token = "tok"\n', encoding="utf-8")
    s = load_settings(empty_config(tmp_path), secrets)
    assert (s.spotify_client_id, s.discord_bot_token) == ("abc", "tok")


def test_missing_secrets_file_is_fine(tmp_path):
    s = load_settings(empty_config(tmp_path), tmp_path / "absent.toml")
    assert s.discord_bot_token == ""


def test_discord_sections_are_loaded(tmp_path):
    s = load_settings(write_config(
        tmp_path,
        '[discord.hotkeys]\nmute = "ctrl+shift+m"\n'
        '[discord.channels]\ngeneral = 123\n'
        '[discord.members]\nalex = 456\n'))
    assert s.discord_hotkeys == {"mute": "ctrl+shift+m"}
    assert s.discord_channels == {"general": 123}
    assert s.discord_members == {"alex": 456}


def test_missing_config_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "nope.toml")


def test_synonyms_are_normalised_and_default_empty(tmp_path):
    assert load_settings(empty_config(tmp_path)).synonyms == {}
    s = load_settings(write_config(tmp_path, '[synonyms]\n" Balance la Suivante " = " Musique Suivante"'))
    assert s.synonyms == {"balance la suivante": "musique suivante"}
