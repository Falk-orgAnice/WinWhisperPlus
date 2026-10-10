"""Owned per-process audio storage and versioned recognition jobs."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
import json
import os
import shutil
import threading
import uuid
import ctypes

if TYPE_CHECKING:
    from config.settings import Settings


@dataclass
class ResultVersion:
    model: str
    language: str | None
    target: str | None
    text_model: str = "bundled-qwen3-4b"
    created: datetime = field(default_factory=datetime.now)
    raw_text: str = ""
    corrected_text: str = ""
    text: str = ""
    status: str = "processing"
    error: str = ""
    sections: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    settings_snapshot: Settings | None = field(default=None, repr=False)


@dataclass
class AudioJob:
    audio_path: Path
    source: str = "microphone"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created: datetime = field(default_factory=datetime.now)
    duration: float = 0.0
    versions: list[ResultVersion] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)
    running: bool = False
    progress: float = 0.0
    phase: str = ""
    original_path: Path | None = None


def _process_exists(pid: int) -> bool:
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5  # access denied is not proof of death
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class SessionStore:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WinWhisperPlus" / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        self._cleanup_abandoned()
        self.directory = self.root / uuid.uuid4().hex
        self.directory.mkdir()
        (self.directory / "owner.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        self.jobs: list[AudioJob] = []

    def _remove_owned_directory(self, path: Path):
        # Only immediate UUID children owned by this store may be deleted.
        if path.is_symlink() or path.resolve().parent != self.root.resolve():
            return
        if len(path.name) != 32 or any(c not in "0123456789abcdef" for c in path.name):
            return
        shutil.rmtree(path)

    def _cleanup_abandoned(self):
        for path in self.root.iterdir():
            if not path.is_dir() or path.is_symlink():
                continue
            try:
                owner = json.loads((path / "owner.json").read_text(encoding="utf-8"))
                if not _process_exists(int(owner["pid"])):
                    self._remove_owned_directory(path)
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def create(self, source="microphone") -> AudioJob:
        job = AudioJob(self.directory / f"{uuid.uuid4().hex}.wav", source=source)
        self.jobs.append(job)
        return job

    def delete(self, job: AudioJob):
        if job.running:
            raise ValueError("Job is still running")
        if job.audio_path.resolve().parent != self.directory.resolve():
            raise ValueError("Audio is outside this session")
        job.audio_path.unlink(missing_ok=True)
        self.jobs.remove(job)

    def close(self):
        if any(job.running for job in self.jobs):
            raise RuntimeError("Stop workers before closing the session")
        self._remove_owned_directory(self.directory)
