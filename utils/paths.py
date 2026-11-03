"""Paths for installed and self-contained portable distributions."""
import os
import sys
from pathlib import Path


def portable_root() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    root = Path(sys.executable).resolve().parent
    return root if (root / "portable.txt").is_file() else None


def config_directory() -> Path:
    root = portable_root()
    return root / "data" if root else Path(os.environ.get("APPDATA") or Path.home()) / "WinWhisperPlus"


def local_directory() -> Path:
    root = portable_root()
    return root / "data" if root else Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home()) / "WinWhisperPlus"


def model_directory() -> Path:
    return local_directory() / "models"
