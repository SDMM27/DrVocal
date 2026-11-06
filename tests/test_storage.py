from pathlib import Path

from drvocal import storage


def test_dirs_follow_overrides_and_are_created(tmp_path, monkeypatch):
    monkeypatch.setenv("DRVOCAL_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("DRVOCAL_DATA_DIR", str(tmp_path / "data"))
    assert storage.config_dir() == tmp_path / "cfg" and (tmp_path / "cfg").is_dir()
    assert storage.data_dir() == tmp_path / "data"
    assert storage.logs_dir() == tmp_path / "data" / "logs" and storage.logs_dir().is_dir()
    assert storage.default_store().directory == tmp_path / "data" / "secrets"


def test_default_dirs_use_appdata(tmp_path, monkeypatch):
    monkeypatch.delenv("DRVOCAL_CONFIG_DIR", raising=False)
    monkeypatch.delenv("DRVOCAL_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert storage.config_dir() == tmp_path / "roaming" / "DrVocal"
    assert storage.data_dir() == tmp_path / "local" / "DrVocal"


def test_documents_dir_exists():
    assert storage.documents_dir().is_dir()


def test_documents_dir_falls_back_to_home(monkeypatch):
    monkeypatch.setattr(storage, "_known_folder", lambda _id: None)
    assert storage.documents_dir() == Path.home() / "Documents"


def test_relative_paths_resolve_data_then_legacy_then_data(tmp_path, monkeypatch):
    data, legacy = tmp_path / "data", tmp_path / "repo"
    monkeypatch.setenv("DRVOCAL_DATA_DIR", str(data))
    rel = Path("models/wake")
    assert storage.resolve_data_path(rel, legacy) == data / rel  # nulle part : chemin pour les messages d'erreur
    (legacy / rel).mkdir(parents=True)
    assert storage.resolve_data_path(rel, legacy) == legacy / rel
    assert storage.resolve_data_path(rel, None) == data / rel
    (data / rel).mkdir(parents=True)
    assert storage.resolve_data_path(rel, legacy) == data / rel
    absolute = tmp_path / "ailleurs" / "v.onnx"
    assert storage.resolve_data_path(absolute, legacy) == absolute


def test_legacy_root_only_for_drvocal_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "PACKAGE_ROOT", tmp_path)
    assert storage.legacy_root() is None
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "autre"\n', encoding="utf-8")
    assert storage.legacy_root() is None
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "drvocal"\n', encoding="utf-8")
    assert storage.legacy_root() == tmp_path
