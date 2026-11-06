from pathlib import Path

import pytest

from drvocal.config import ConfigError, load_settings, migrate_config
from drvocal.storage import documents_dir


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def empty_config(tmp_path: Path) -> Path:
    return write_config(tmp_path, "")


def test_defaults_notes_dir_to_documents_notes(tmp_path):
    s = load_settings(write_config(tmp_path, ""))
    assert s.notes_dir == documents_dir() / "NOTES"


def test_default_wake_phrases(tmp_path):
    assert load_settings(empty_config(tmp_path)).wake_phrases == ["salut doc vocal"]


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


class FakeStore(dict):
    def get(self, name, default=None):
        return super().get(name, default)


def test_secrets_are_loaded_from_store(tmp_path):
    s = load_settings(empty_config(tmp_path), FakeStore(spotify_client_id="abc", discord_bot_token="tok"))
    assert (s.spotify_client_id, s.discord_bot_token) == ("abc", "tok")


def test_missing_secrets_are_empty(tmp_path):
    s = load_settings(empty_config(tmp_path), FakeStore())
    assert s.discord_bot_token == "" and s.spotify_client_id == ""


def test_missing_config_with_missing_ok_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "absent.toml", missing_ok=True).wake_mode == "key"


def test_migrate_config_0_to_1():
    assert migrate_config({"wake_mode": "key"}) == {"wake_mode": "key", "schema_version": 1}
    assert migrate_config({"schema_version": 1}) == {"schema_version": 1}


def test_future_schema_version_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="version"):
        migrate_config({"schema_version": 99})
    with pytest.raises(ConfigError):
        load_settings(write_config(tmp_path, "schema_version = 99"))
    with pytest.raises(ConfigError):
        migrate_config({"schema_version": "un"})


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


def test_simulated_hotkeys_flag_defaults_off_and_loads(tmp_path):
    assert load_settings(empty_config(tmp_path)).simulated_hotkeys_enabled is False
    assert load_settings(write_config(tmp_path, "simulated_hotkeys_enabled = true")).simulated_hotkeys_enabled is True
    with pytest.raises(ConfigError):
        load_settings(write_config(tmp_path, 'simulated_hotkeys_enabled = "oui"'))


def test_discord_owner_id(tmp_path):
    assert load_settings(empty_config(tmp_path)).discord_owner_id == 0
    s = load_settings(write_config(tmp_path, "[discord]\nowner_id = 42\n"))
    assert s.discord_owner_id == 42


def test_wake_and_audio_defaults(tmp_path):
    s = load_settings(empty_config(tmp_path))
    assert s.wake_mode == "key" and s.push_to_talk_key == "mouse5"
    assert s.wake_models_dir == Path("models/wake") and s.wake_threshold == 0.9
    assert s.tts_voice == Path("models/piper/fr_FR-siwis-medium.onnx")
    assert s.sounds == {}


def test_wake_settings_are_loaded(tmp_path):
    s = load_settings(write_config(
        tmp_path,
        'wake_mode = "Voice"\npush_to_talk_key = "F9"\nwake_threshold = 0.8\n'
        '[sounds]\nwake = "w.wav"\n'))
    assert (s.wake_mode, s.push_to_talk_key, s.wake_threshold) == ("voice", "f9", 0.8)
    assert s.sounds == {"wake": Path("w.wav")}


def test_invalid_wake_mode_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(write_config(tmp_path, 'wake_mode = "clap"'))


def test_unknown_push_to_talk_key_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(write_config(tmp_path, 'push_to_talk_key = "mouse99"'))



def test_command_log_and_vocabulary_defaults(tmp_path):
    s = load_settings(empty_config(tmp_path))
    assert s.command_log is True and s.stt_hotwords is True and s.stt_vocabulary == []


def test_command_log_and_vocabulary_load(tmp_path):
    s = load_settings(write_config(
        tmp_path, 'command_log = false\nstt_hotwords = false\nstt_vocabulary = [" Daft Punk ", "", "Zaz"]'))
    assert s.command_log is False and s.stt_hotwords is False and s.stt_vocabulary == ["Daft Punk", "Zaz"]


@pytest.mark.parametrize("line", ['command_log = "oui"', 'stt_hotwords = 1', 'stt_vocabulary = "Zaz"'])
def test_invalid_command_log_and_vocabulary_values_raise(tmp_path, line):
    with pytest.raises(ConfigError):
        load_settings(write_config(tmp_path, line))
