"""Speech transcription through the bundled whisper.cpp CPU/Vulkan runtimes."""

from __future__ import annotations

import os
import re
import json
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
import urllib.error
import wave
from pathlib import Path
from typing import Optional
from core.audio import Segment
from core.models import ModelManager, Cancelled
from core.cancellation import interrupt_on_cancel
from utils.runtime import runtime_executable, select_runtime, vulkan_devices

import numpy as np

MODEL_FILENAMES = {
    "tiny": "ggml-tiny.bin",
    "base": "ggml-base.bin",
    "small": "ggml-small.bin",
    "medium": "ggml-medium.bin",
    "large": "ggml-large-v3.bin",
    "large-v3": "ggml-large-v3.bin",
    "large-v3-turbo": "ggml-large-v3-turbo.bin",
    "large-v3-turbo-q5_0": "ggml-large-v3-turbo-q5_0.bin",
}
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{filename}"
COMPUTE_DEVICE_AUTO = "auto"
COMPUTE_DEVICE_CPU = "cpu"
SILENCE_RMS_THRESHOLD = 0.0001


def list_vulkan_devices(executable_path: str | Path | None = None) -> list[tuple[int, str]]:
    """Return Vulkan devices reported by the bundled whisper.cpp runtime.

    The CLI writes its Vulkan inventory while processing ``--help``.  Failure
    to query it is intentionally treated as an empty list, so CPU-only mode
    remains available on machines without a working Vulkan driver.
    """
    executable = Path(executable_path) if executable_path else Transcriber._find_executable()
    return vulkan_devices(executable)


class Transcriber:
    """Run a whisper.cpp CLI process for float32 mono 16 kHz audio."""

    def __init__(
        self,
        model_name: str = "base",
        *,
        executable_path: str | Path | None = None,
        model_dir: str | Path | None = None,
        compute_device: str = COMPUTE_DEVICE_AUTO,
        keep_model_loaded: bool = False,
    ) -> None:
        self._model_name = model_name
        self._model_path: Path | None = None
        self._model_stat = None
        self._executable_path = Path(executable_path).resolve() if executable_path else self._find_executable()
        self._custom_executable = executable_path is not None
        self._runtime_selected = False
        self._effective_compute_device = compute_device
        app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        self._model_dir = Path(model_dir).resolve() if model_dir else Path(app_data) / "WinWhisperPlus" / "models"
        self._lock = threading.Lock()
        self._compute_device = COMPUTE_DEVICE_AUTO
        self._keep_model_loaded = bool(keep_model_loaded)
        self._server_process: subprocess.Popen | None = None
        self._server_port: int | None = None
        self._server_model_path: Path | None = None
        self._vad_path: Path | None = None
        self.set_compute_device(compute_device)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Pre-load the Whisper model (blocking).  Call once at startup."""
        with self._lock:
            self._select_runtime()
            if self._model_path is None:
                self._model_path = self._load_model()
                self._remember_model_stat()
            if self._keep_model_loaded:
                self._ensure_server()

    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
    ) -> str:
        """
        Transcribe *audio* (float32, 16 kHz, mono) and return the text.

        Parameters
        ----------
        audio:
            Raw float32 samples at 16 000 Hz.
        language:
            ISO-639-1 code ('de', 'pl', 'en') or None for auto-detect.
        """
        if audio is None or len(audio) == 0:
            return ""
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if float(np.sqrt(np.mean(np.square(samples)))) < SILENCE_RMS_THRESHOLD:
            return ""

        with self._lock:
            self._select_runtime()
            if self._model_path is None:
                self._model_path = self._load_model()
                self._remember_model_stat()
            if self._keep_model_loaded:
                return self._run_server(audio, language)
            return self._run_cli(audio, language)

    def transcribe_chunk(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
    ) -> str:
        """Transcribe a live audio chunk using the same model instance."""
        return self.transcribe(audio, language=language)

    def set_model(self, model_name: str) -> None:
        """Switch model (invalidates any cached model)."""
        with self._lock:
            if self._model_name == model_name:
                manager = ModelManager(self._model_dir)
                activated = manager.installed_spec("large-v3" if model_name == "large" else model_name)
                desired = manager.path(activated) if activated else self._model_path
                stat = (desired.stat().st_size, desired.stat().st_mtime_ns) if desired and desired.is_file() else None
                if desired == self._model_path and (self._model_stat is None or stat == self._model_stat):
                    return
            self._stop_server()
            self._model_name = model_name
            self._model_path = None
            self._model_stat = None

    def _remember_model_stat(self):
        if self._model_path and self._model_path.is_file():
            stat = self._model_path.stat()
            self._model_stat = (stat.st_size, stat.st_mtime_ns)

    def set_compute_device(self, compute_device: str) -> None:
        """Select automatic Vulkan, one Vulkan device, or CPU-only inference."""
        if not self._is_valid_compute_device(compute_device):
            raise ValueError(f"Unsupported compute device: {compute_device}")
        with self._lock:
            if self._compute_device != compute_device:
                self._stop_server()
                self._runtime_selected = False
            self._compute_device = compute_device
            if self._custom_executable:
                self._effective_compute_device = compute_device

    def _select_runtime(self) -> None:
        if not self._runtime_selected and not self._custom_executable:
            self._executable_path, self._effective_compute_device = select_runtime("whispercpp", self._compute_device)
            self._runtime_selected = True

    def set_keep_model_loaded(self, keep_model_loaded: bool) -> None:
        """Keep the selected model in a local whisper.cpp server process."""
        with self._lock:
            self._keep_model_loaded = bool(keep_model_loaded)
            if not self._keep_model_loaded:
                self._stop_server()

    def close(self) -> None:
        """Release a resident whisper.cpp server and its model memory."""
        with self._lock:
            self._stop_server()

    def _load_model(self) -> Path:
        """Download the selected whisper.cpp GGML model once, if necessary."""
        manager = ModelManager(self._model_dir)
        model_id = "large-v3" if self._model_name == "large" else self._model_name
        if model_id not in manager.catalog or manager.catalog[model_id].kind != "speech":
            raise ValueError(f"Unsupported whisper.cpp model: {self._model_name}")
        return manager.ensure(model_id)

    def transcribe_segments(self, audio, language=None, *, cancel=None, no_context=False) -> tuple[list[Segment], str | None]:
        """Timestamped, VAD-enabled inference for one bounded job section."""
        if cancel and cancel.is_set():
            raise Cancelled("Cancelled")
        if len(audio) == 0 or float(np.sqrt(np.mean(np.asarray(audio) ** 2))) < SILENCE_RMS_THRESHOLD:
            return [], language
        with self._lock:
            self._select_runtime()
            manager = ModelManager(self._model_dir)
            if self._model_path is None:
                self._model_path = manager.ensure("large-v3" if self._model_name == "large" else self._model_name, cancel)
                self._remember_model_stat()
            if self._vad_path is None:
                self._vad_path = manager.ensure("silero-v6.2.0", cancel)
                self._stop_server()  # a preloaded server must restart with VAD
            if self._keep_model_loaded:
                with interrupt_on_cancel(cancel, self._stop_server):
                    try:
                        result = self._run_server(audio, language, detailed=True, no_context=no_context)
                    except Exception:
                        if cancel and cancel.is_set():
                            raise Cancelled("Cancelled")
                        raise
                # Verbose server word timestamps are available on current runtimes.
                segments = self._server_segments(result)
                detected = result.get("language", language)
                detected = {"german": "de", "english": "en", "polish": "pl", "french": "fr", "dutch": "nl"}.get(str(detected).lower(), detected)
                # Unknown full language names must not become invalid ISO codes
                # on the next section. Keep auto-detection for such sources.
                if detected is not None and not re.fullmatch(r"[a-z]{2,3}", str(detected)):
                    detected = None
                return segments, detected
            return self._run_cli_segments(audio, language, cancel, no_context=no_context)

    @staticmethod
    def _server_segments(result):
        segments = []
        for section in result.get("segments", []):
            words = section.get("words", [])
            # Zero-duration tokens contain real words too; never drop them.
            valid = all(w.get("start", -1) >= 0 and w.get("end", -1) >= w.get("start", -1) for w in words)
            joined = "".join(str(w.get("word", "")) for w in words)
            if words and valid and joined.strip() == str(section["text"]).strip():
                # VAD maps segment times to original audio; token times may still
                # be in the compressed speech timeline. Align each segment.
                shift = max(0, float(section["start"]) - float(words[0]["start"]))
                for word in words:
                    start = min(float(section["end"]), float(word["start"]) + shift)
                    end = min(float(section["end"]), float(word["end"]) + shift)
                    segments.append(Segment(start, max(start, end), str(word["word"])))
            else:
                segments.append(Segment(float(section["start"]), float(section["end"]), str(section["text"])))
        return segments

    def _run_cli_segments(self, audio, language, cancel, *, no_context=False):
        self._select_runtime()
        if not self._executable_path.is_file():
            raise RuntimeError("whisper.cpp runtime missing; build a release first")
        with tempfile.TemporaryDirectory(prefix="winwhisperplus-") as directory:
            audio_path = Path(directory) / "audio.wav"
            output = Path(directory) / "transcript"
            self._write_wav(audio_path, audio)
            command = [str(self._executable_path), "--model", str(self._model_path), "--file", str(audio_path),
                       "--language", language or "auto", "--output-json-full", "--output-file", str(output),
                       "--max-context", "0", "--vad", "--vad-model", str(self._vad_path)]
            if no_context:
                command.extend(["--temperature", "0.2"])
            self._append_compute_device_arguments(command)
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       cwd=self._executable_path.parent,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                while True:
                    if cancel and cancel.is_set():
                        raise Cancelled("Cancelled")
                    try:
                        stdout, stderr = process.communicate(timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if process.returncode:
                    raise RuntimeError(stderr.decode("utf-8", errors="replace")[-8192:])
                result = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
                return self._cli_segments(result), result.get("result", {}).get("language", language)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=5)

    @staticmethod
    def _cli_segments(result):
        sections = []
        for s in result.get("transcription", []):
            tokens = [t for t in s.get("tokens", []) if not str(t.get("text", "")).startswith("[_")]
            words = []
            for token in tokens:
                offsets = token.get("offsets", {})
                words.append({"start": offsets.get("from", -1000) / 1000,
                              "end": offsets.get("to", -1000) / 1000,
                              "word": token.get("text", "")})
            sections.append({"start": s["offsets"]["from"] / 1000,
                             "end": s["offsets"]["to"] / 1000,
                             "text": s["text"], "words": words})
        return Transcriber._server_segments({"segments": sections})

    def _run_cli(self, audio: np.ndarray, language: Optional[str]) -> str:
        self._select_runtime()
        if not self._executable_path.is_file():
            raise RuntimeError(
                "whisper.cpp executable not found. Build a release or set "
                "WINWHISPERPLUS_WHISPERCPP_DIR to its runtime directory."
            )
        assert self._model_path is not None

        with tempfile.TemporaryDirectory(prefix="winwhisperplus-") as temporary_dir:
            temporary_path = Path(temporary_dir)
            audio_path = temporary_path / "audio.wav"
            output_base = temporary_path / "transcript"
            self._write_wav(audio_path, audio)
            command = [
                str(self._executable_path),
                "--model", str(self._model_path),
                "--file", str(audio_path),
                "--language", language or "auto",
                "--no-timestamps",
                "--output-txt",
                "--output-file", str(output_base),
            ]
            self._append_compute_device_arguments(command)
            completed = subprocess.run(
                command,
                cwd=self._executable_path.parent,
                capture_output=True,
                text=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(f"whisper.cpp transcription failed: {detail}")

            text_path = output_base.with_suffix(".txt")
            if text_path.is_file():
                return text_path.read_text(encoding="utf-8").strip()
            return completed.stdout.strip()

    def _ensure_server(self) -> None:
        """Start a local server once so the model stays loaded between requests."""
        self._select_runtime()
        assert self._model_path is not None
        if (
            self._server_process is not None
            and self._server_process.poll() is None
            and self._server_model_path == self._model_path
        ):
            return
        self._stop_server()

        server_executable = self._executable_path.with_name("whisper-server.exe")
        if not server_executable.is_file():
            raise RuntimeError(
                "whisper.cpp server executable not found. Build a current release "
                "or disable 'model loaded in memory'."
            )
        port = self._reserve_local_port()
        command = [
            str(server_executable),
            "--model", str(self._model_path),
            "--host", "127.0.0.1",
            "--port", str(port),
        ]
        if self._vad_path:
            command.extend(["--vad", "--vad-model", str(self._vad_path)])
        self._append_compute_device_arguments(command)
        self._server_process = subprocess.Popen(
            command,
            cwd=server_executable.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._server_port = port
        self._server_model_path = self._model_path

        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self._server_process is None or self._server_process.poll() is not None:
                self._stop_server()
                raise RuntimeError("whisper.cpp server could not load the model")
            try:
                with urllib.request.urlopen(self._server_url("/"), timeout=0.5):
                    return
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        self._stop_server()
        raise RuntimeError("Timed out while loading the whisper.cpp model server")

    def _run_server(self, audio: np.ndarray, language: Optional[str], *, detailed=False, no_context=False):
        self._ensure_server()
        with tempfile.TemporaryDirectory(prefix="winwhisperplus-") as temporary_dir:
            audio_path = Path(temporary_dir) / "audio.wav"
            self._write_wav(audio_path, audio)
            body, content_type = self._multipart_request(
                audio_path.read_bytes(), language or "auto", detailed=detailed, no_context=no_context
            )
            request = urllib.request.Request(
                self._server_url("/inference"),
                data=body,
                headers={"Content-Type": content_type},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"whisper.cpp server transcription failed: {exc}") from exc
            return result if detailed else str(result.get("text", "")).strip()

    def _append_compute_device_arguments(self, command: list[str]) -> None:
        if self._effective_compute_device == COMPUTE_DEVICE_CPU:
            command.append("--no-gpu")
        elif self._compute_device.startswith("gpu:"):
            command.extend(["--device", self._compute_device.removeprefix("gpu:")])

    @staticmethod
    def _multipart_request(audio_data: bytes, language: str, *, detailed=False, no_context=False) -> tuple[bytes, str]:
        boundary = "----WinWhisperPlusBoundary"
        chunks: list[bytes] = []
        fields = [("language", language), ("response_format", "verbose_json" if detailed else "json")]
        if no_context:
            fields.append(("temperature", "0.2"))
        for name, value in fields:
            chunks.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ])
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n',
            b"Content-Type: audio/wav\r\n\r\n",
            audio_data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    @staticmethod
    def _reserve_local_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _server_url(self, path: str) -> str:
        assert self._server_port is not None
        return f"http://127.0.0.1:{self._server_port}{path}"

    def _stop_server(self) -> None:
        if self._server_process is not None and self._server_process.poll() is None:
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
        self._server_process = None
        self._server_port = None
        self._server_model_path = None

    @staticmethod
    def _write_wav(path: Path, audio: np.ndarray) -> None:
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        pcm = np.clip(samples, -1.0, 1.0)
        pcm = (pcm * np.iinfo(np.int16).max).astype("<i2", copy=False)
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16_000)
            wav_file.writeframes(pcm.tobytes())

    @staticmethod
    def _find_executable() -> Path:
        return runtime_executable("whispercpp")

    @staticmethod
    def _is_valid_compute_device(compute_device: str) -> bool:
        return compute_device in {COMPUTE_DEVICE_AUTO, COMPUTE_DEVICE_CPU} or (
            isinstance(compute_device, str)
            and compute_device.startswith("gpu:")
            and compute_device.removeprefix("gpu:").isdigit()
        )
