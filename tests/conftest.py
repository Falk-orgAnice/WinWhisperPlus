"""Pytest-wide setup that keeps test output out of the user's application data."""

from __future__ import annotations

import os
from pathlib import Path


# app.py initializes its file logger during import.  Pytest loads this module
# first, so all deliberately triggered error paths are written to this
# repository-local test location instead of the user's real WinWhisperPlus log.
os.environ["APPDATA"] = str(Path(__file__).resolve().parents[1] / ".tmp" / "pytest-appdata")
