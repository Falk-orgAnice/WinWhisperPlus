"""Tests for core/recorder.py (mocking sounddevice)"""

import sys
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def mock_sounddevice(monkeypatch):
    """Replace sounddevice with a minimal mock so tests run without hardware."""
    sd_mock = MagicMock()

    # Simulate sd.query_devices() returning two devices
    sd_mock.query_devices.return_value = [
        {"name": "Mikrofon 1", "max_input_channels": 2},
        {"name": "Lautsprecher", "max_input_channels": 0},
        {"name": "Mikrofon 2", "max_input_channels": 1},
    ]
    sd_mock.sleep = time.sleep

    # InputStream context manager that does nothing
    stream_instance = MagicMock()
    stream_instance.__enter__ = lambda s: s
    stream_instance.__exit__ = MagicMock(return_value=False)
    sd_mock.InputStream.return_value = stream_instance

    monkeypatch.setitem(sys.modules, "sounddevice", sd_mock)
    # Force re-import so the module picks up the new sounddevice mock
    monkeypatch.delitem(sys.modules, "core.recorder", raising=False)
    yield sd_mock


def test_list_microphones():
    from core.recorder import list_microphones
    mics = list_microphones()
    assert len(mics) == 2
    assert mics[0]["name"] == "Mikrofon 1"
    assert mics[1]["name"] == "Mikrofon 2"


def test_recorder_initial_state():
    from core.recorder import Recorder
    r = Recorder()
    assert not r.is_recording


def test_recorder_start_stop():
    from core.recorder import Recorder
    r = Recorder()
    r.start()
    assert r.is_recording
    audio = r.stop()
    assert not r.is_recording
    assert isinstance(audio, np.ndarray)


def test_recorder_stop_without_start():
    from core.recorder import Recorder
    r = Recorder()
    audio = r.stop()
    assert len(audio) == 0


def test_recorder_double_start():
    """Calling start twice should not raise and should keep recording."""
    from core.recorder import Recorder
    r = Recorder()
    r.start()
    r.start()  # second call should be a no-op
    assert r.is_recording
    r.stop()


def test_resample_native_microphone_rate_to_whisper_rate():
    from core.recorder import Recorder

    frame = np.array([[0.0], [1.0], [0.0], [-1.0]], dtype=np.float32)
    resampled = Recorder._resample_to_whisper_rate(frame, source_rate=8_000)

    assert resampled.dtype == np.float32
    assert resampled.shape == (8, 1)
    assert resampled[0, 0] == pytest.approx(0.0)
