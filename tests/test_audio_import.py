from pathlib import Path
import subprocess
import wave
import threading
import numpy as np
import pytest
from core.audio import find_ffmpeg, convert_audio, wav_duration
from core.models import Cancelled


@pytest.mark.parametrize("extension", ["wav", "mp3", "m4a", "flac"])
def test_real_ffmpeg_converts_stereo_formats_to_mono_16khz(tmp_path, extension):
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setparams((2, 2, 44100, 0, "NONE", ""))
        samples = (np.sin(np.arange(44100) * 2 * np.pi * 440 / 44100) * 10000).astype("<i2")
        wav.writeframes(np.repeat(samples[:, None], 2, axis=1).tobytes())
    input_file = source
    if extension != "wav":
        input_file = tmp_path / f"source.{extension}"
        subprocess.run([str(find_ffmpeg()), "-v", "error", "-y", "-i", str(source), str(input_file)], check=True)
    before = input_file.read_bytes()
    destination = tmp_path / "normalized.wav"
    convert_audio(input_file, destination)
    assert wav_duration(destination) == pytest.approx(1, abs=0.06)
    assert input_file.read_bytes() == before


def test_bad_file_does_not_leave_partial_audio(tmp_path):
    source = tmp_path / "broken.mp3"
    source.write_bytes(b"not audio")
    destination = tmp_path / "normalized.wav"
    with pytest.raises(RuntimeError):
        convert_audio(source, destination)
    assert not destination.exists()


def test_cancelled_import_does_not_start_converter(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        convert_audio(tmp_path / "missing.wav", tmp_path / "output.wav", cancel)
