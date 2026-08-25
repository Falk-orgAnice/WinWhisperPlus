"""Speech transcription through the bundled whisper.cpp Vulkan runtime."""

from __future__ import annotations

import os
import re
import json
import logging
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
import wave
from pathlib import Path
from typing import Optional

import numpy as np

LOGGER = logging.getLogger("winwhisperplus")

MODEL_FILENAMES = {
    "tiny": "ggml-tiny.bin",
    "base": "ggml-base.bin",
    "small": "ggml-small.bin",
    "medium": "ggml-medium.bin",
    "large": "ggml-large-v3.bin",
}
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{filename}"
COMPUTE_DEVICE_AUTO = "auto"
COMPUTE_DEVICE_CPU = "cpu"
SILENCE_RMS_THRESHOLD = 0.0001
_VULKAN_DEVICE_PATTERN = re.compile(r"^ggml_vulkan:\s*(\d+)\s*=\s*(.*?)(?:\s*\|.*)?$")


def list_vulkan_devices(executable_path: str | Path | None = None) -> list[tuple[int, str]]:
    """Return Vulkan devices reported by the bundled whisper.cpp runtime.

    The CLI writes its Vulkan inventory while processing ``--help``.  Failure
    to query it is intentionally treated as an empty list, so CPU-only mode
    remains available on machines without a working Vulkan driver.
    """
    executable = Path(executable_path) if executable_path else Transcriber._find_executable()
    if not executable.is_file():
        return []
    try:
        completed = subprocess.run(
            [str(executable), "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []

    devices: list[tuple[int, str]] = []
    for line in f"{completed.stdout}\n{completed.stderr}".splitlines():
        match = _VULKAN_DEVICE_PATTERN.match(line.strip())
        if match:
            devices.append((int(match.group(1)), match.group(2).strip()))
    return devices


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
        self._executable_path = Path(executable_path) if executable_path else self._find_executable()
        app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        self._model_dir = Path(model_dir) if model_dir else Path(app_data) / "WinWhisperPlus" / "models"
        self._lock = threading.Lock()
        self._compute_device = COMPUTE_DEVICE_AUTO
        self._keep_model_loaded = bool(keep_model_loaded)
        self._server_process: subprocess.Popen | None = None
        self._server_port: int | None = None
        self._server_model_path: Path | None = None
        self._server_log_handle = None
        self.set_compute_device(compute_device)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Pre-load the Whisper model (blocking).  Call once at startup."""
        with self._lock:
            if self._model_path is None:
                self._model_path = self._load_model()
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
            if self._model_path is None:
                self._model_path = self._load_model()
            if self._keep_model_loaded:
                try:
                    return self._run_server(audio, language)
                except Exception as server_error:  # noqa: BLE001
                    # A resident server is an optimization.  Never discard a
                    # recording merely because that optimization became unavailable.
                    LOGGER.exception(
                        "Residenter whisper.cpp-Server fehlgeschlagen; versuche CLI-Fallback | executable=%s model=%s",
                        self._executable_path,
                        self._model_path,
                    )
                    try:
                        text = self._run_cli(audio, language)
                    except Exception as cli_error:  # noqa: BLE001
                        LOGGER.exception(
                            "CLI-Fallback nach Serverfehler fehlgeschlagen | executable=%s model=%s",
                            self._executable_path,
                            self._model_path,
                        )
                        raise RuntimeError(
                            f"Resident server failed ({server_error}); CLI fallback also failed ({cli_error})"
                        ) from cli_error
                    LOGGER.warning("CLI-Fallback nach Serverfehler erfolgreich")
                    return text
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
            if self._model_name != model_name:
                self._stop_server()
            self._model_name = model_name
            self._model_path = None

    def set_compute_device(self, compute_device: str) -> None:
        """Select automatic Vulkan, one Vulkan device, or CPU-only inference."""
        if not self._is_valid_compute_device(compute_device):
            raise ValueError(f"Unsupported compute device: {compute_device}")
        with self._lock:
            if self._compute_device != compute_device:
                self._stop_server()
            self._compute_device = compute_device

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
        filename = MODEL_FILENAMES.get(self._model_name)
        if filename is None:
            raise ValueError(f"Unsupported whisper.cpp model: {self._model_name}")
        self._model_dir.mkdir(parents=True, exist_ok=True)
        model_path = self._model_dir / filename
        if model_path.is_file() and model_path.stat().st_size > 0:
            return model_path

        temporary_path = model_path.with_suffix(".part")
        try:
            urllib.request.urlretrieve(MODEL_URL.format(filename=filename), temporary_path)
            temporary_path.replace(model_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return model_path

    def _run_cli(self, audio: np.ndarray, language: Optional[str]) -> str:
        if not self._executable_path.is_file():
            raise RuntimeError(
                "whisper.cpp executable not found. Build a release or set "
                "WINWHISPERPLUS_WHISPERCPP_DIR to its runtime directory."
            )
        assert self._model_path is not None

        LOGGER.info(
            "whisper.cpp CLI gestartet | executable=%s model=%s language=%s samples=%s compute_device=%s",
            self._executable_path,
            self._model_path,
            language or "auto",
            len(audio),
            self._compute_device,
        )

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
                capture_output=True,
                text=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                LOGGER.error("whisper.cpp CLI beendet mit returncode=%s | detail=%s", completed.returncode, detail)
                raise RuntimeError(f"whisper.cpp transcription failed: {detail}")

            text_path = output_base.with_suffix(".txt")
            if text_path.is_file():
                return text_path.read_text(encoding="utf-8").strip()
            return completed.stdout.strip()

    def _ensure_server(self) -> None:
        """Start a local server once so the model stays loaded between requests."""
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
            LOGGER.error(
                "whisper.cpp Server-Programm fehlt | cli=%s server=%s",
                self._executable_path,
                server_executable,
            )
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
            "--no-timestamps",
        ]
        self._append_compute_device_arguments(command)
        server_output = self._open_server_output_log()
        self._server_process = subprocess.Popen(
            command,
            stdout=server_output or subprocess.DEVNULL,
            stderr=server_output or subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._server_port = port
        self._server_model_path = self._model_path
        LOGGER.info(
            "whisper.cpp Server gestartet | pid=%s executable=%s model=%s port=%s compute_device=%s",
            self._server_process.pid,
            server_executable,
            self._model_path,
            port,
            self._compute_device,
        )

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self._server_process.poll() is not None:
                exit_code = self._server_process.returncode
                self._stop_server()
                LOGGER.error("whisper.cpp Server beim Laden beendet | exit_code=%s", exit_code)
                raise RuntimeError("whisper.cpp server could not load the model")
            try:
                with urllib.request.urlopen(self._server_url("/"), timeout=0.5):
                    return
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        self._stop_server()
        LOGGER.error("Zeitüberschreitung beim Laden des whisper.cpp Servers | model=%s", self._model_path)
        raise RuntimeError("Timed out while loading the whisper.cpp model server")

    def _run_server(self, audio: np.ndarray, language: Optional[str]) -> str:
        self._ensure_server()
        LOGGER.info(
            "whisper.cpp Server-Anfrage | port=%s model=%s language=%s samples=%s",
            self._server_port,
            self._model_path,
            language or "auto",
            len(audio),
        )
        with tempfile.TemporaryDirectory(prefix="winwhisperplus-") as temporary_dir:
            audio_path = Path(temporary_dir) / "audio.wav"
            self._write_wav(audio_path, audio)
            body, content_type = self._multipart_request(
                audio_path.read_bytes(), language or "auto"
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
                LOGGER.error("whisper.cpp Server-Anfrage fehlgeschlagen | port=%s error=%s", self._server_port, exc)
                raise RuntimeError(f"whisper.cpp server transcription failed: {exc}") from exc
            return str(result.get("text", "")).strip()

    def _append_compute_device_arguments(self, command: list[str]) -> None:
        if self._compute_device == COMPUTE_DEVICE_CPU:
            command.append("--no-gpu")
        elif self._compute_device.startswith("gpu:"):
            command.extend(["--device", self._compute_device.removeprefix("gpu:")])

    @staticmethod
    def _multipart_request(audio_data: bytes, language: str) -> tuple[bytes, str]:
        boundary = "----WinWhisperPlusBoundary"
        chunks: list[bytes] = []
        for name, value in (("language", language), ("response_format", "json")):
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
            LOGGER.info("whisper.cpp Server wird beendet | pid=%s", self._server_process.pid)
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
        self._server_process = None
        self._server_port = None
        self._server_model_path = None
        if self._server_log_handle is not None:
            self._server_log_handle.close()
            self._server_log_handle = None

    def _open_server_output_log(self):
        """Return a per-model native server log without blocking its output pipe."""
        app_data = os.environ.get("APPDATA") or str(Path.home())
        log_path = Path(app_data) / "WinWhisperPlus" / f"whisper-server-{self._model_name}.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._server_log_handle = log_path.open("a", encoding="utf-8")
        except OSError:
            LOGGER.exception("Native whisper.cpp Server-Ausgabe kann nicht protokolliert werden | path=%s", log_path)
            return None
        LOGGER.info("Native whisper.cpp Server-Ausgabe wird protokolliert | path=%s", log_path)
        return self._server_log_handle

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
        runtime_dir = os.environ.get("WINWHISPERPLUS_WHISPERCPP_DIR")
        if runtime_dir:
            return Path(runtime_dir) / "whisper-cli.exe"
        if getattr(sys, "frozen", False):
            bundle_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
            return bundle_dir / "whispercpp" / "whisper-cli.exe"
        return Path(__file__).resolve().parents[1] / "build" / "whispercpp-runtime" / "whisper-cli.exe"

    @staticmethod
    def _is_valid_compute_device(compute_device: str) -> bool:
        return compute_device in {COMPUTE_DEVICE_AUTO, COMPUTE_DEVICE_CPU} or (
            isinstance(compute_device, str)
            and compute_device.startswith("gpu:")
            and compute_device.removeprefix("gpu:").isdigit()
        )
