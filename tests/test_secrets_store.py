import pytest

from drvocal.secrets_store import SecretStore


def test_set_get_roundtrip_and_file_is_encrypted(tmp_path):
    store = SecretStore(tmp_path / "secrets")
    store.set("discord_bot_token", "jeton-très-secret-é")
    assert store.get("discord_bot_token") == "jeton-très-secret-é"
    raw = (tmp_path / "secrets" / "discord_bot_token.bin").read_bytes()
    assert b"secret" not in raw
    assert not list((tmp_path / "secrets").glob("*.tmp"))


def test_missing_returns_none_and_delete_is_idempotent(tmp_path):
    store = SecretStore(tmp_path)
    assert store.get("spotify_client_id") is None
    store.set("spotify_client_id", "x")
    store.delete("spotify_client_id")
    store.delete("spotify_client_id")
    assert store.get("spotify_client_id") is None


def test_set_overwrites(tmp_path):
    store = SecretStore(tmp_path)
    store.set("spotify_token", "a")
    store.set("spotify_token", "b")
    assert store.get("spotify_token") == "b"


def test_corrupted_file_gives_none_and_warns_without_value(tmp_path, caplog):
    store = SecretStore(tmp_path)
    store.set("spotify_token", "VALEUR")
    (tmp_path / "spotify_token.bin").write_bytes(b"garbage garbage garbage")
    with caplog.at_level("WARNING", logger="drvocal.secrets"):
        assert store.get("spotify_token") is None
    assert "spotify_token" in caplog.text and "VALEUR" not in caplog.text


@pytest.mark.parametrize("name", ["", "../x", "Token", "a b", "a.b"])
def test_invalid_names_are_refused(tmp_path, name):
    with pytest.raises(ValueError):
        SecretStore(tmp_path).set(name, "x")
    with pytest.raises(ValueError):
        SecretStore(tmp_path).get(name)
