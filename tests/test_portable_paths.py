from pathlib import Path

from config.settings import Settings
from core.models import ModelManager
from core.transcriber import Transcriber
from core.text_optimizer import TextOptimizer
from core.statistics import _statistics_path
from core.session import SessionStore
from utils import paths


def test_portable_uses_executable_folder_and_never_user_profile(tmp_path, monkeypatch):
    app = tmp_path / "usb"
    app.mkdir()
    (app / "portable.txt").write_text("portable")
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(app / "WinWhisperPlus.exe"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "profile"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    legacy = tmp_path / "profile" / "MyWhisper"
    legacy.mkdir(parents=True)
    (legacy / "settings.json").write_text('{"language": "pl"}')
    settings = Settings()
    models = app / "data" / "models"
    assert settings._path == app / "data" / "settings.json"
    assert settings.language == "de"
    assert ModelManager().directory == models
    assert Transcriber(executable_path=app / "whisper-cli.exe")._model_dir == models
    assert TextOptimizer(executable_path=app / "llama-server.exe")._model_path.parent == models
    assert _statistics_path() == app / "data" / "statistics.json"
    store = SessionStore()
    assert store.root == app / "data" / "sessions"
    store.close()


def test_installed_and_source_use_profile_without_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(tmp_path / "WinWhisperPlus.exe"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert paths.config_directory() == tmp_path / "roaming" / "WinWhisperPlus"
    assert paths.model_directory() == tmp_path / "local" / "WinWhisperPlus" / "models"

