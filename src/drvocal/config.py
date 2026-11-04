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
    wake_mode: str = "key"  # "voice" ou "key" : touche tant que le modele vocal n'est pas valide
    push_to_talk_key: str = "mouse5"
    wake_models_dir: Path = Path("models/wake")  # relatif a la racine du projet (resolu par l'app)
    wake_threshold: float = 0.9
    tts_voice: Path = Path("models/piper/fr_FR-siwis-medium.onnx")  # idem, relatif a la racine
    sounds: dict[str, Path] = field(default_factory=dict)
    command_log: bool = True
    stt_hotwords: bool = True
    stt_vocabulary: list[str] = field(default_factory=list)


def _as_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"booleen attendu, recu {value!r}")
    return value


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"liste attendue, recu {value!r}")
    return [str(v).strip() for v in value if str(v).strip()]


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

    from drvocal.audio.push_to_talk import resolve_key  # import tardif : evite un cycle avec actions_hotkeys

    discord = data.get("discord", {})
    try:
        wake_mode = str(data.get("wake_mode", "key")).strip().lower()
        if wake_mode not in ("voice", "key"):
            raise ValueError(f"wake_mode doit valoir 'voice' ou 'key', recu {wake_mode!r}")
        key = str(data.get("push_to_talk_key", "mouse5")).strip().lower()
        if resolve_key(key) is None:
            raise ValueError(f"push_to_talk_key inconnue : {key!r}")
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
            wake_mode=wake_mode,
            push_to_talk_key=key,
            wake_models_dir=Path(data.get("wake_models_dir", "models/wake")),
            wake_threshold=float(data.get("wake_threshold", 0.9)),
            tts_voice=Path(data.get("tts_voice", "models/piper/fr_FR-siwis-medium.onnx")),
            sounds={str(k): Path(v) for k, v in data.get("sounds", {}).items()},
            command_log=_as_bool(data.get("command_log", True)),
            stt_hotwords=_as_bool(data.get("stt_hotwords", True)),
            stt_vocabulary=_as_str_list(data.get("stt_vocabulary", [])),
        )
    except (TypeError, ValueError, AttributeError) as e:
        raise ConfigError(f"Valeur invalide dans {config_path} : {e}") from e
