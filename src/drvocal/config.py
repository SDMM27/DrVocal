"""Chargement des reglages (config.toml) et des secrets (secrets.toml)."""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_WAKE_PHRASES = ["salut doc vocal"]


class ConfigError(Exception):
    """Fichier de configuration illisible ou invalide."""


@dataclass(frozen=True)
class Settings:
    wake_phrases: list[str]
    notes_dir: Path
    projects: dict[str, Path]
    discord_hotkeys: dict[str, str]
    discord_channels: dict[str, int]
    discord_members: dict[str, int]
    spotify_client_id: str
    discord_bot_token: str
    stt_model: str
    stt_device: str
    second_screen_index: int
    synonyms: dict[str, str] = field(default_factory=dict)
    simulated_hotkeys_enabled: bool = False
    discord_owner_id: int = 0


def _as_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"booleen attendu, recu {value!r}")
    return value


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"Impossible de lire {path} : {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"TOML invalide dans {path} : {e}") from e


def load_settings(config_path: Path, secrets_path: Path | None = None) -> Settings:
    data = _read_toml(config_path)
    secrets: dict = {}
    if secrets_path is not None and secrets_path.exists():
        secrets = _read_toml(secrets_path)

    discord = data.get("discord", {})
    try:
        return Settings(
            wake_phrases=[str(p).strip().lower() for p in data.get("wake_phrases", DEFAULT_WAKE_PHRASES)],
            notes_dir=Path(data.get("notes_dir", Path.home() / "Documents" / "NOTES")),
            projects={str(k).strip().lower(): Path(v) for k, v in data.get("projects", {}).items()},
            discord_hotkeys={str(k): str(v) for k, v in discord.get("hotkeys", {}).items()},
            discord_channels={str(k): int(v) for k, v in discord.get("channels", {}).items()},
            discord_members={str(k): int(v) for k, v in discord.get("members", {}).items()},
            spotify_client_id=str(secrets.get("spotify_client_id", "")),
            discord_bot_token=str(secrets.get("discord_bot_token", "")),
            stt_model=str(data.get("stt_model", "small")),
            stt_device=str(data.get("stt_device", "cpu")),
            second_screen_index=int(data.get("second_screen_index", 1)),
            synonyms={str(k).strip().lower(): str(v).strip().lower()
                      for k, v in data.get("synonyms", {}).items()},
            simulated_hotkeys_enabled=_as_bool(data.get("simulated_hotkeys_enabled", False)),
            discord_owner_id=int(discord.get("owner_id", 0)),
        )
    except (TypeError, ValueError, AttributeError) as e:
        raise ConfigError(f"Valeur invalide dans {config_path} : {e}") from e
