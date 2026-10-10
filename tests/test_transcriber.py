"""Tests for the whisper.cpp transcription adapter."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from core.transcriber import Transcriber, list_vulkan_devices


@pytest.fixture
def transcriber(tmp_path) -> Transcriber:
    executable = tmp_path / "whisper-cli.exe"
    executable.touch()
    return Transcriber("base", executable_path=executable, model_dir=tmp_path / "models")


def test_transcribe_returns_text_file_content(transcriber, monkeypatch):
    monkeypatch.setattr(transcriber, "_load_model", lambda: Path("model.bin"))

    def run(command, **_kwargs):
        Path(command[command.index("--output-file") + 1]).with_suffix(".txt").write_text(" Hallo Welt ")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("core.transcriber.subprocess.run", run)

    assert transcriber.transcribe(np.ones(16_000, dtype=np.float32) * 0.01, language="de") == "Hallo Welt"


def test_transcribe_empty_audio_does_not_load_model(transcriber):
    assert transcriber.transcribe(np.zeros(0, dtype=np.float32), language="de") == ""


def test_near_silent_audio_does_not_hallucinate_or_load_model(transcriber, monkeypatch):
    monkeypatch.setattr(transcriber, "_load_model", lambda: pytest.fail("model must not load"))

    assert transcriber.transcribe(np.zeros(16_000, dtype=np.float32), language="de") == ""


def test_set_model_invalidates_cached_model(transcriber, monkeypatch):
    loaded = []
    monkeypatch.setattr(transcriber, "_load_model", lambda: loaded.append(Path("model.bin")) or loaded[-1])
    monkeypatch.setattr(transcriber, "_run_cli", lambda *_args: "text")

    transcriber.transcribe(np.ones(4, dtype=np.float32) * 0.01)
    transcriber.set_model("small")
    transcriber.transcribe(np.ones(4, dtype=np.float32) * 0.01)

    assert len(loaded) == 2


def test_load_preloads_model(transcriber, monkeypatch):
    loaded = []
    monkeypatch.setattr(transcriber, "_load_model", lambda: loaded.append(Path("model.bin")) or loaded[-1])
    transcriber.load()
    transcriber.load()
    assert len(loaded) == 1


def test_cli_failure_includes_backend_error(transcriber, monkeypatch):
    monkeypatch.setattr(transcriber, "_load_model", lambda: Path("model.bin"))
    monkeypatch.setattr(
        "core.transcriber.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="Vulkan error"),
    )

    with pytest.raises(RuntimeError, match="Vulkan error"):
        transcriber.transcribe(np.ones(4, dtype=np.float32) * 0.01)


def test_cpu_mode_adds_no_gpu_flag(transcriber, monkeypatch):
    transcriber.set_compute_device("cpu")
    monkeypatch.setattr(transcriber, "_load_model", lambda: Path("model.bin"))
    captured = {}

    def run(command, **_kwargs):
        captured["command"] = command
        Path(command[command.index("--output-file") + 1]).with_suffix(".txt").write_text("text")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("core.transcriber.subprocess.run", run)
    transcriber.transcribe(np.ones(4, dtype=np.float32) * 0.01)

    assert "--no-gpu" in captured["command"]


def test_selected_gpu_is_passed_to_cli(transcriber, monkeypatch):
    transcriber.set_compute_device("gpu:2")
    monkeypatch.setattr(transcriber, "_load_model", lambda: Path("model.bin"))
    captured = {}

    def run(command, **_kwargs):
        captured["command"] = command
        Path(command[command.index("--output-file") + 1]).with_suffix(".txt").write_text("text")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("core.transcriber.subprocess.run", run)
    transcriber.transcribe(np.ones(4, dtype=np.float32) * 0.01)

    assert captured["command"][-2:] == ["--device", "2"]


def test_list_vulkan_devices_parses_cli_inventory(tmp_path, monkeypatch):
    executable = tmp_path / "whisper-cli.exe"
    executable.touch()
    monkeypatch.setattr(
        "core.transcriber.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="",
            stderr=(
                "ggml_vulkan: Found 2 Vulkan devices:\n"
                "ggml_vulkan: 0 = AMD Radeon 890M | uma: 1 | fp16: 1\n"
                "ggml_vulkan: 1 = AMD Radeon RX 9070 XT | uma: 0 | fp16: 1\n"
            ),
        ),
    )

    assert list_vulkan_devices(executable) == [
        (0, "AMD Radeon 890M"),
        (1, "AMD Radeon RX 9070 XT"),
    ]


def test_resident_model_mode_uses_server(transcriber, monkeypatch):
    transcriber.set_keep_model_loaded(True)
    monkeypatch.setattr(transcriber, "_load_model", lambda: Path("model.bin"))
    monkeypatch.setattr(transcriber, "_run_server", lambda *_args: "resident text")
    monkeypatch.setattr(transcriber, "_run_cli", lambda *_args: pytest.fail("CLI must not run"))

    assert transcriber.transcribe(np.ones(4, dtype=np.float32) * 0.01, language="de") == "resident text"


def test_multipart_request_contains_wav_and_language():
    body, content_type = Transcriber._multipart_request(b"WAV", "de")

    assert "multipart/form-data" in content_type
    assert b'name="language"' in body
    assert b"\r\n\r\nde\r\n" in body
    assert b'filename="audio.wav"' in body
    assert b"WAV" in body


def test_server_keeps_zero_duration_words_and_maps_vad_timeline():
    result = {"segments": [{"start": 10, "end": 12, "text": " do for you",
              "words": [{"start": 1, "end": 1.4, "word": " do"},
                        {"start": 1.4, "end": 1.4, "word": " for"},
                        {"start": 1.4, "end": 2, "word": " you"}]}]}
    segments = Transcriber._server_segments(result)
    assert "".join(s.text for s in segments) == " do for you"
    assert segments[0].start == 10
    assert segments[1].start == segments[1].end


def test_invalid_word_timestamps_preserve_complete_segment_text():
    result = {"segments": [{"start": 0, "end": 1, "text": " all words",
              "words": [{"start": -1, "end": -1, "word": " all"},
                        {"start": 0, "end": 1, "word": " words"}]}]}
    assert "".join(s.text for s in Transcriber._server_segments(result)) == " all words"
