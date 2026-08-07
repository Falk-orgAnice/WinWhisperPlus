"""
Fake/stub implementations of core components for headless smoke tests.

These fakes satisfy the same interface as the real Recorder, Transcriber,
and text-insert functions, but never touch hardware, the OS clipboard, or
the file-system model cache.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

import numpy as np


# ---------------------------------------------------------------------------
# FakeRecorder
# ---------------------------------------------------------------------------

class FakeRecorder:
    """Drop-in replacement for ``core.recorder.Recorder`` used in tests.

    When ``start()`` is called the recorder immediately delivers a single
    audio chunk via ``on_chunk`` (if live transcription is wired up) and
    marks itself as recording.  ``stop()`` returns the pre-canned audio.
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        on_chunk: Callable[[np.ndarray], None] | None = None,
        chunk_seconds: float = 2.0,
        overlap_seconds: float = 0.5,
        audio_data: Optional[np.ndarray] = None,
    ) -> None:
        self._on_chunk = on_chunk
        # 1 second of silence at 16 kHz by default
        self._audio_data: np.ndarray = (
            audio_data if audio_data is not None
            else np.zeros(16_000, dtype=np.float32)
        )
        self._recording = False

    # -- Public API (mirrors Recorder) --------------------------------------

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        self._recording = True
        if self._on_chunk is not None:
            # Deliver the canned chunk synchronously so the live worker
            # has data to process immediately.
            self._on_chunk(self._audio_data.copy())

    def stop(self) -> np.ndarray:
        self._recording = False
        return self._audio_data.copy()


# ---------------------------------------------------------------------------
# FakeTranscriber
# ---------------------------------------------------------------------------

class FakeTranscriber:
    """Drop-in replacement for ``core.transcriber.Transcriber`` used in tests.

    Returns a configurable text string.  Optionally raises an exception or
    introduces a small delay to exercise error- and timing-related paths.
    """

    def __init__(
        self,
        return_text: str = "hello world",
        delay: float = 0.0,
        raise_exc: Optional[Exception] = None,
    ) -> None:
        self._return_text = return_text
        self._delay = delay
        self._raise_exc = raise_exc
        self.load_called = False
        self.transcribe_call_count = 0

    # -- Public API (mirrors Transcriber) ------------------------------------

    def load(self) -> None:
        self.load_called = True

    def set_model(self, model_name: str) -> None:  # noqa: ARG002
        pass

    def set_compute_device(self, compute_device: str) -> None:  # noqa: ARG002
        pass

    def set_keep_model_loaded(self, keep_model_loaded: bool) -> None:  # noqa: ARG002
        pass

    def close(self) -> None:
        pass

    def transcribe(self, audio: np.ndarray, language: Optional[str] = None) -> str:  # noqa: ARG002
        self.transcribe_call_count += 1
        if self._delay:
            time.sleep(self._delay)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._return_text

    def transcribe_chunk(self, audio: np.ndarray, language: Optional[str] = None) -> str:
        return self.transcribe(audio, language=language)


# ---------------------------------------------------------------------------
# FakeTextSink
# ---------------------------------------------------------------------------

class FakeTextSink:
    """Collects text-insert operations instead of pasting them into the OS.

    Attributes
    ----------
    inserts:
        Texts passed to ``insert_text``.
    replaces:
        ``(previous, new)`` tuples passed to ``replace_text``.
    enters:
        Number of times ``press_enter`` was called.
    """

    def __init__(self) -> None:
        self.inserts: list[str] = []
        self.replaces: list[tuple[str, str]] = []
        self.enters: int = 0

    def insert_text(self, text: str) -> None:
        self.inserts.append(text)

    def replace_text(self, previous: str, new: str) -> None:
        self.replaces.append((previous, new))

    def press_enter(self) -> None:
        self.enters += 1

    # Convenience ---------------------------------------------------------

    @property
    def all_text(self) -> str:
        """Concatenation of all directly inserted texts."""
        return " ".join(self.inserts)

    def final_replaced_text(self) -> str | None:
        """The *new* text from the very last replace call, or None."""
        return self.replaces[-1][1] if self.replaces else None


class FakeTextOptimizer:
    """Deterministic local-optimizer stand-in for app integration tests."""

    def __init__(self, return_text: str | None = None, raise_exc: Exception | None = None) -> None:
        self.return_text = return_text
        self.raise_exc = raise_exc
        self.calls: list[tuple[str, str, str | None]] = []
        self.compute_device = "auto"
        self.closed = False

    def optimize(self, text: str, *, options, language: str | None = None) -> str:
        self.calls.append((text, options, language))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.return_text if self.return_text is not None else text

    def set_compute_device(self, compute_device: str) -> None:
        self.compute_device = compute_device

    def close(self) -> None:
        self.closed = True
