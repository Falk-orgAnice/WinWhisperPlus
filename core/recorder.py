"""
Audio recorder – captures microphone input into a NumPy float32 array.
Recording runs on a background thread; the result is retrieved via
``stop()`` which blocks until the thread finishes.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import numpy as np

try:
    import sounddevice as sd
except ImportError as exc:  # pragma: no cover
    raise ImportError("sounddevice is required: pip install sounddevice") from exc

SAMPLE_RATE = 16_000   # Hz – Whisper expects 16 kHz
CHANNELS = 1
LOGGER = logging.getLogger("winwhisperplus")


class Recorder:
    """Manages a single recording session."""

    def __init__(
        self,
        device_index: Optional[int] = None,
        on_chunk: Callable[[np.ndarray], None] | None = None,
        chunk_seconds: float = 2.0,
        overlap_seconds: float = 0.5,
    ) -> None:
        self._device_index = device_index
        self._input_sample_rate = self._resolve_input_sample_rate()
        self._on_chunk = on_chunk
        self._chunk_samples = max(1, int(chunk_seconds * SAMPLE_RATE))
        self._step_samples = max(1, int((chunk_seconds - overlap_seconds) * SAMPLE_RATE))
        self._frames: list[np.ndarray] = []
        self._captured_samples = 0
        self._next_chunk_at = self._chunk_samples
        self._stream: Optional[sd.InputStream] = None
        self._recording = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin capturing audio in a background thread."""
        if self._recording.is_set():
            return
        self._frames = []
        self._captured_samples = 0
        self._next_chunk_at = self._chunk_samples
        self._recording.set()
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()

    def stop(self) -> np.ndarray:
        """Stop capturing and return the recorded audio as float32 array."""
        self._recording.clear()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        if not self._frames:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(self._frames, axis=0).flatten()
        return audio.astype(np.float32)

    @property
    def is_recording(self) -> bool:
        return self._recording.is_set()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _record_loop(self) -> None:
        def callback(indata: np.ndarray, frames: int, time, status) -> None:  # noqa: ARG001
            if self._recording.is_set():
                frame = self._resample_to_whisper_rate(indata.copy(), self._input_sample_rate)
                self._frames.append(frame)
                if self._on_chunk is not None:
                    self._append_chunk_frame(frame)

        try:
            with sd.InputStream(
                samplerate=self._input_sample_rate,
                channels=CHANNELS,
                dtype="float32",
                device=self._device_index,
                callback=callback,
            ):
                LOGGER.info(
                    "Mikrofonaufnahme gestartet | device=%s input_rate=%s target_rate=%s",
                    self._device_index,
                    self._input_sample_rate,
                    SAMPLE_RATE,
                )
                while self._recording.is_set():
                    sd.sleep(100)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Mikrofonaufnahme konnte nicht gestartet werden | device=%s", self._device_index)
            self._recording.clear()

    def _resolve_input_sample_rate(self) -> int:
        """Use 16 kHz when supported, otherwise the device's native rate."""
        if self._device_index is None:
            return SAMPLE_RATE
        try:
            sd.check_input_settings(
                device=self._device_index,
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
            )
            return SAMPLE_RATE
        except Exception:  # noqa: BLE001
            try:
                native_rate = int(sd.query_devices(self._device_index)["default_samplerate"])
                if native_rate > 0:
                    LOGGER.info(
                        "Mikrofon nutzt native Samplerate | device=%s input_rate=%s",
                        self._device_index,
                        native_rate,
                    )
                    return native_rate
            except Exception:  # noqa: BLE001
                LOGGER.exception("Samplerate des Mikrofons konnte nicht ermittelt werden | device=%s", self._device_index)
            return SAMPLE_RATE

    @staticmethod
    def _resample_to_whisper_rate(frame: np.ndarray, source_rate: int) -> np.ndarray:
        """Linearly resample a callback frame to Whisper's required 16 kHz."""
        if source_rate == SAMPLE_RATE:
            return frame.astype(np.float32, copy=False)
        samples = np.asarray(frame, dtype=np.float32).reshape(-1)
        if len(samples) == 0:
            return samples.reshape(0, 1)
        target_size = max(1, round(len(samples) * SAMPLE_RATE / source_rate))
        positions = np.arange(target_size, dtype=np.float64) * source_rate / SAMPLE_RATE
        resampled = np.interp(positions, np.arange(len(samples)), samples)
        return resampled.astype(np.float32).reshape(-1, 1)

    def _append_chunk_frame(self, frame: np.ndarray) -> None:
        self._captured_samples += len(frame)
        if self._captured_samples < self._next_chunk_at:
            return

        chunk_audio = np.concatenate(self._frames, axis=0).flatten().astype(np.float32)
        try:
            self._on_chunk(chunk_audio)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Recorder on_chunk callback fehlgeschlagen")
        self._next_chunk_at += self._step_samples


def list_microphones() -> list[dict]:
    """Return a list of available input devices with 'index' and 'name'."""
    devices = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            devices.append({"index": idx, "name": dev["name"]})
    return devices
