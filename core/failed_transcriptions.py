"""Persistent recovery copies for recordings whose transcription failed."""

from __future__ import annotations

import json
import os
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class FailedTranscription:
    """One recoverable recording and the language used to transcribe it."""

    audio_path: Path
    language: str


class FailedTranscriptionStore:
    """Store failed recordings locally until a later retry succeeds.

    Recordings are saved as ordinary WAV files so they remain recoverable even
    if the application cannot be started again.  The adjacent JSON file keeps
    the selected dictation language for a faithful retry.
    """

    def __init__(self, directory: str | Path | None = None) -> None:
        app_data = os.environ.get("APPDATA") or str(Path.home())
        self._directory = Path(directory) if directory else Path(app_data) / "WinWhisperPlus" / "failed-transcriptions"

    def save(self, audio: np.ndarray, language: str) -> FailedTranscription:
        self._directory.mkdir(parents=True, exist_ok=True)
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        audio_path = self._directory / f"recording-{identifier}.wav"
        metadata_path = audio_path.with_suffix(".json")
        self._write_wav(audio_path, audio)
        metadata_path.write_text(
            json.dumps({"audio_file": audio_path.name, "language": language}, ensure_ascii=False),
            encoding="utf-8",
        )
        return FailedTranscription(audio_path=audio_path, language=language)

    def latest(self) -> FailedTranscription | None:
        if not self._directory.is_dir():
            return None
        for metadata_path in sorted(self._directory.glob("recording-*.json"), reverse=True):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                audio_name = str(metadata["audio_file"])
                audio_path = self._directory / audio_name
                if audio_path.parent != self._directory or not audio_path.is_file():
                    continue
                return FailedTranscription(audio_path=audio_path, language=str(metadata["language"]))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return None

    def load_audio(self, recording: FailedTranscription) -> np.ndarray:
        with wave.open(str(recording.audio_path), "rb") as wav_file:
            if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2 or wav_file.getframerate() != SAMPLE_RATE:
                raise ValueError("Recovered recording has an unsupported WAV format")
            frames = wav_file.readframes(wav_file.getnframes())
        return np.frombuffer(frames, dtype="<i2").astype(np.float32) / np.iinfo(np.int16).max

    def delete(self, recording: FailedTranscription) -> None:
        recording.audio_path.unlink(missing_ok=True)
        recording.audio_path.with_suffix(".json").unlink(missing_ok=True)

    @staticmethod
    def _write_wav(path: Path, audio: np.ndarray) -> None:
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        pcm = np.clip(samples, -1.0, 1.0)
        pcm = (pcm * np.iinfo(np.int16).max).astype("<i2", copy=False)
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(pcm.tobytes())
