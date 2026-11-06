import pytest

from drvocal.secrets_store import SecretStore
from drvocal.storage import migrate_legacy

CLIENT_ID = "client-id-connu-123"
BOT_TOKEN = "bot-token-connu-456"
SPOTIFY_TOKEN = '{"access_token": "acces-connu-789", "refresh_token": "refresh-connu-abc"}'


@pytest.fixture
def world(tmp_path):
    repo, cfg, data = tmp_path / "repo", tmp_path / "cfg", tmp_path / "data"
    repo.mkdir()
    (repo / "config.toml").write_text('wake_mode = "voice"\n', encoding="utf-8")
    (repo / "secrets.toml").write_text(f'spotify_client_id = "{CLIENT_ID}"\ndiscord_bot_token = "{BOT_TOKEN}"\n',
                                       encoding="utf-8")
    (repo / ".spotify-cache").write_text(SPOTIFY_TOKEN, encoding="utf-8")
    return tmp_path, repo, cfg, SecretStore(data / "secrets")


def _all_bytes(root):
    return b"\n".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


def test_migration_leaves_no_clear_secret_anywhere(world):
    tmp_path, repo, cfg, store = world
    done = migrate_legacy(repo, cfg, store)
    assert done == ["config.toml", "secrets.toml", ".spotify-cache"]
    blob = _all_bytes(tmp_path)
    for secret in (CLIENT_ID, BOT_TOKEN, "acces-connu-789", "refresh-connu-abc"):
        assert secret.encode() not in blob
    assert store.get("spotify_client_id") == CLIENT_ID
    assert store.get("discord_bot_token") == BOT_TOKEN
    assert store.get("spotify_token") == SPOTIFY_TOKEN
    assert (cfg / "config.toml").read_text(encoding="utf-8") == 'wake_mode = "voice"\n'
    assert (repo / "config.toml.migrated").exists() and not (repo / "config.toml").exists()


def test_migration_is_idempotent(world):
    _, repo, cfg, store = world
    migrate_legacy(repo, cfg, store)
    assert migrate_legacy(repo, cfg, store) == []
    assert store.get("discord_bot_token") == BOT_TOKEN


def test_existing_config_is_not_overwritten(world):
    _, repo, cfg, store = world
    cfg.mkdir()
    (cfg / "config.toml").write_text("deja = 1\n", encoding="utf-8")
    assert "config.toml" not in migrate_legacy(repo, cfg, store)
    assert (cfg / "config.toml").read_text(encoding="utf-8") == "deja = 1\n"
    assert (repo / "config.toml").exists()


class BrokenStore:
    def set(self, name, value):
        raise OSError("echec simule")

    def get(self, name):
        return None


class ForgetfulStore(BrokenStore):
    def set(self, name, value):
        pass  # accepte mais ne retient rien : la relecture doit echouer


@pytest.mark.parametrize("store_class", [BrokenStore, ForgetfulStore])
def test_failing_store_loses_nothing(world, store_class, caplog):
    _, repo, cfg, _ = world
    done = migrate_legacy(repo, cfg, store_class())
    assert done == ["config.toml"]
    assert BOT_TOKEN in (repo / "secrets.toml").read_text(encoding="utf-8")
    assert (repo / ".spotify-cache").read_text(encoding="utf-8") == SPOTIFY_TOKEN
    assert BOT_TOKEN not in caplog.text and "acces-connu-789" not in caplog.text


def test_invalid_secret_name_keeps_file(world):
    _, repo, cfg, store = world
    (repo / "secrets.toml").write_text('"Nom Invalide" = "x"\n', encoding="utf-8")
    assert "secrets.toml" not in migrate_legacy(repo, cfg, store)
    assert (repo / "secrets.toml").exists()


def test_nothing_to_migrate(tmp_path):
    assert migrate_legacy(tmp_path / "rien", tmp_path / "cfg", SecretStore(tmp_path / "s")) == []
