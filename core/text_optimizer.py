"""Local, optional post-processing of final speech transcriptions.

The module deliberately talks only to a loopback ``llama-server`` process.
It never sends recognised text to a remote service.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


MODEL_FILENAME = "Qwen_Qwen3-4B-Q4_K_M.gguf"
MODEL_SHA256_FILENAME = "text-model.sha256"
_DEFAULT_TIMEOUT_SECONDS = 45.0
_MESSAGE_GREETING_PATTERN = re.compile(
    r"^(?:hallo|hi|hey|hello|dear|liebe(?:r|s)?|guten\s+(?:morgen|tag|abend)|"
    r"good\s+(?:morning|afternoon|evening)|cześć|dzien dobry|dzień dobry|drogi|droga)\b",
    re.IGNORECASE,
)
_SENTENCE_LINE_BREAK_PATTERN = re.compile(
    r"(?<=[.!?])[ \t]+(?=[A-ZÄÖÜĄĆĘŁŃÓŚŹŻ])"
)


class TextOptimizationError(RuntimeError):
    """Raised when local text optimization cannot produce a safe result."""


@dataclass(frozen=True)
class TextOptimizationOptions:
    """Independently combinable operations for one local model request."""

    formatting: bool = True
    cleanup: bool = False
    redact: bool = False
    translation_target: str | None = None

    def has_work(self, source_language: str | None) -> bool:
        return any((
            self.formatting,
            self.cleanup,
            self.redact,
            bool(self.translation_target and self.translation_target != source_language),
        ))


_LANGUAGE_NAMES = {"de": "German", "pl": "Polish", "en": "English"}


def build_system_prompt(options: TextOptimizationOptions, language: str | None = None) -> str:
    """Return the fixed editing/translation instruction for the selected options."""
    instructions: list[str] = []
    if options.formatting:
        instructions.append(
            "Correct capitalization and punctuation, add meaningful paragraphs, and use simple "
            "'-' lists where clearly appropriate."
        )
    if options.cleanup:
        instructions.append("Remove only unmistakable verbatim repetitions and filler words.")
    if options.redact:
        instructions.append("Cautiously rewrite for readability and concision without changing meaning.")
    target = options.translation_target
    translation_instruction = ""
    if target and target != language:
        target_name = _LANGUAGE_NAMES.get(target, target)
        translation_instruction = (
            f" CRITICAL FINAL REQUIREMENT: Translate the complete final output, including greeting, "
            f"closing, and signature wording, into {target_name}. Use {target_name} for every "
            "translatable word; preserve only names, numbers, and untranslatable proper nouns. "
            "Keep every required paragraph break and line break in the translated output."
        )
    if not instructions:
        instructions.append("Return the transcription unchanged.")
    language_instruction = f"The recognised source language is {language}. " if language else ""
    formatting_instruction = (
        "Output universal plain text only: paragraphs and '-' list items are allowed, but no Markdown "
        "headings, emphasis, code fences, or HTML. Formatting is required, not optional. "
        "For a short message, chat, or email, put a greeting "
        "in its own paragraph followed by a blank line. Put each distinct body sentence on "
        "its own line, without blank lines between closely related body sentences. Put a "
        "closing phrase and a signature in their own final paragraphs, each separated by a blank "
        "line. Layout example only (replace placeholders with content in the required output language): "
        "GREETING,\n\nBODY SENTENCE 1.\nBODY SENTENCE 2.\n\nCLOSING,\n\nSIGNATURE."
        if options.formatting
        else "Output universal plain text only; do not use Markdown, HTML, or explanations."
    )
    return (
        "You edit a speech transcription. Return only the requested JSON object. "
        + language_instruction
        + " ".join(instructions)
        + " Return exactly one JSON object with this exact schema: {\"text\": \"the optimized "
        "plain text\"}. The only permitted key is text; never use a message key. Preserve names, "
        "numbers, commands, facts, intent, and tone. Never invent "
        "missing facts or content; leave ambiguous fragments intact. "
        + formatting_instruction
        + translation_instruction
    )


def _validate_optimized_text(value: object) -> str:
    """Validate the constrained response before it reaches the clipboard."""
    if not isinstance(value, str):
        raise TextOptimizationError("Model response field 'text' is not a string")
    text = value.strip()
    if not text:
        raise TextOptimizationError("Model response field 'text' is empty")
    if re.search(r"(?m)^\s{0,3}#{1,6}\s|```|\*\*|__|<\/?[A-Za-z][^>]*>", text):
        raise TextOptimizationError("Model response contains unsupported rich formatting")
    return text


def _format_short_message(text: str) -> str:
    """Apply the requested sentence layout to an already-structured message.

    The local model decides semantic paragraphs.  This intentionally narrow
    final pass handles a common plain-text message convention reliably: a
    greeting, one sentence per body line, and closing/signature paragraphs.
    Non-message dictations are returned unchanged.
    """
    paragraphs = text.replace("\r\n", "\n").split("\n\n")
    if not paragraphs or not _MESSAGE_GREETING_PATTERN.match(paragraphs[0].lstrip()):
        return text

    first_paragraph = paragraphs[0].strip()
    if "\n" not in first_paragraph and "," in first_paragraph:
        greeting, remainder = first_paragraph.split(",", 1)
        if remainder.strip():
            paragraphs = [greeting.strip() + ",", remainder.strip(), *paragraphs[1:]]

    formatted = [paragraphs[0]]
    for paragraph in paragraphs[1:]:
        formatted.append(_SENTENCE_LINE_BREAK_PATTERN.sub("\n", paragraph.strip()))
    return "\n\n".join(formatted)


class TextOptimizer:
    """Manage a bundled local llama.cpp server and optimize final text.

    ``request_callable`` is an intentionally small test seam.  Production uses
    the loopback HTTP client; tests can supply a deterministic response without
    starting a model process.
    """

    def __init__(
        self,
        *,
        compute_device: str = "auto",
        executable_path: str | Path | None = None,
        model_path: str | Path | None = None,
        model_hash_path: str | Path | None = None,
        request_timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        request_callable: Callable[[dict], object] | None = None,
    ) -> None:
        self._compute_device = compute_device
        self._executable_path = Path(executable_path) if executable_path else self._find_executable()
        self._model_path = Path(model_path) if model_path else self._find_model()
        self._model_hash_path = Path(model_hash_path) if model_hash_path else self._model_path.with_name(MODEL_SHA256_FILENAME)
        self._request_timeout_seconds = request_timeout_seconds
        self._request_callable = request_callable
        self._lock = threading.Lock()
        self._server_process: subprocess.Popen | None = None
        self._server_port: int | None = None
        self._hash_verified = False

    def optimize(
        self,
        text: str,
        *,
        options: TextOptimizationOptions,
        language: str | None = None,
    ) -> str:
        """Optimize *text*, retrying exactly once before raising an error."""
        if not text or not text.strip():
            return text
        payload = self._build_request(text, options=options, language=language)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with self._lock:
                    if self._request_callable is None:
                        self._ensure_server()
                    response = self._request(payload)
                return self._parse_response(response, format_message=options.formatting)
            except Exception as exc:  # noqa: BLE001 - converted to stable domain error below
                last_error = exc
                if attempt == 0:
                    self._stop_server()
        raise TextOptimizationError(f"Text optimization failed after retry: {last_error}") from last_error

    def set_compute_device(self, compute_device: str) -> None:
        if compute_device not in {"auto", "cpu"} and not (
            compute_device.startswith("gpu:") and compute_device[4:].isdigit()
        ):
            raise ValueError(f"Unsupported compute device: {compute_device}")
        with self._lock:
            if self._compute_device != compute_device:
                self._compute_device = compute_device
                self._stop_server()

    def close(self) -> None:
        with self._lock:
            self._stop_server()

    def _build_request(
        self,
        text: str,
        *,
        options: TextOptimizationOptions,
        language: str | None,
    ) -> dict:
        schema = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        }
        return {
            "model": "Qwen3-4B",
            "stream": False,
            "temperature": 0,
            "max_tokens": min(4096, max(256, len(text.split()) * 3)),
            "messages": [
                {"role": "system", "content": build_system_prompt(options, language)},
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_schema", "schema": schema},
            "chat_template_kwargs": {"enable_thinking": False},
        }

    def _request(self, payload: dict) -> object:
        if self._request_callable is not None:
            return self._request_callable(payload)
        request = urllib.request.Request(
            self._server_url("/v1/chat/completions"),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._request_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise TextOptimizationError(f"Local llama.cpp request failed: {exc}") from exc

    @staticmethod
    def _parse_response(response: object, *, format_message: bool) -> str:
        try:
            content = response["choices"][0]["message"]["content"]  # type: ignore[index]
            result = json.loads(content) if isinstance(content, str) else content
            if not isinstance(result, dict):
                raise TypeError("Model JSON response is not an object")
            # Older llama.cpp/Qwen chat templates can ignore the response schema
            # and use ``message`` as their default field.  The strict prompt above
            # prevents that on current builds; retaining this narrow fallback lets
            # a bundled model still return its verified plain-text result.
            text = _validate_optimized_text(result.get("text", result.get("message")))
            return _format_short_message(text) if format_message else text
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise TextOptimizationError("Invalid local llama.cpp response schema") from exc

    def _ensure_server(self) -> None:
        if self._server_process is not None and self._server_process.poll() is None:
            return
        if not self._executable_path.is_file():
            raise TextOptimizationError(f"Bundled llama-server not found: {self._executable_path}")
        if not self._model_path.is_file():
            raise TextOptimizationError(f"Bundled text model not found: {self._model_path}")
        self._verify_model_hash()
        port = self._reserve_local_port()
        command = [
            str(self._executable_path),
            "--model", str(self._model_path),
            "--host", "127.0.0.1",
            "--port", str(port),
            "--ctx-size", "8192",
            "--parallel", "1",
            "--n-gpu-layers", "0" if self._compute_device == "cpu" else "999",
        ]
        if self._compute_device.startswith("gpu:"):
            command.extend(["--device", f"Vulkan{self._compute_device[4:]}"])
        self._server_process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._server_port = port
        deadline = time.monotonic() + self._request_timeout_seconds
        while time.monotonic() < deadline:
            if self._server_process.poll() is not None:
                self._stop_server()
                raise TextOptimizationError("Bundled llama-server could not load the model")
            try:
                with urllib.request.urlopen(self._server_url("/health"), timeout=0.5):
                    return
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        self._stop_server()
        raise TextOptimizationError("Timed out while loading bundled text model")

    def _verify_model_hash(self) -> None:
        if self._hash_verified:
            return
        if not self._model_hash_path.is_file():
            raise TextOptimizationError(f"Text model checksum not found: {self._model_hash_path}")
        expected = self._model_hash_path.read_text(encoding="ascii").split()[0].lower()
        digest = hashlib.sha256()
        with self._model_path.open("rb") as model_file:
            for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if expected != actual:
            raise TextOptimizationError("Bundled text model checksum mismatch")
        self._hash_verified = True

    def _stop_server(self) -> None:
        if self._server_process is not None and self._server_process.poll() is None:
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
        self._server_process = None
        self._server_port = None

    @staticmethod
    def _reserve_local_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _server_url(self, path: str) -> str:
        assert self._server_port is not None
        return f"http://127.0.0.1:{self._server_port}{path}"

    @staticmethod
    def _find_runtime_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "textoptimizer"
        configured = os.environ.get("WINWHISPERPLUS_TEXTOPTIMIZER_DIR")
        if configured:
            return Path(configured)
        return Path(__file__).resolve().parents[1] / "build" / "textoptimizer-runtime"

    @classmethod
    def _find_executable(cls) -> Path:
        return cls._find_runtime_dir() / "llama-server.exe"

    @classmethod
    def _find_model(cls) -> Path:
        return cls._find_runtime_dir() / "models" / MODEL_FILENAME
