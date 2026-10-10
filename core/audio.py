"""Bounded WAV decoding, pause-aware windows and local file conversion."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile
import wave
import numpy as np
from core.models import Cancelled

RATE = 16_000


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("Expected 16 kHz mono PCM16 WAV")
        return wav.getnframes() / RATE


def audio_windows(path: Path):
    """Read <=30 seconds; seek back one second without ever dropping the tail."""
    with wave.open(str(path), "rb") as wav:
        total = wav.getnframes()
        start = 0
        while start < total:
            wav.setpos(start)
            samples = np.frombuffer(wav.readframes(RATE * 30), dtype="<i2").astype(np.float32) / 32768
            end = start + len(samples)
            if end < total:
                # Choose the quietest 100 ms near the end, preferring a pause.
                candidates = np.arange(RATE * 25, len(samples) - RATE // 10, RATE // 10)
                if len(candidates):
                    rms = [float(np.sqrt(np.mean(samples[i:i + RATE // 10] ** 2))) for i in candidates]
                    best = int(np.argmin(rms))
                    if rms[best] < 0.005:
                        end = start + int(candidates[best]) + RATE // 20
                        samples = samples[:end - start]
            yield start / RATE, samples
            if end >= total:
                break
            start = max(start + 1, end - RATE)


def merge_segments(previous: list[Segment], incoming: list[Segment], overlap_start: float) -> list[Segment]:
    """Join hypotheses in speech order, aligning only the shared audio tail.

    Token times are estimates. Sorting competing hypotheses by time would
    interleave their words. Instead retain the previous hypothesis and trim
    a matching incoming prefix, including punctuation, at a shared word run.
    Matches outside the physical overlap are never candidates for removal.
    """
    if not previous:
        return list(incoming)
    if not incoming:
        return list(previous)
    boundary = max(s.end for s in previous)
    if boundary <= overlap_start:
        return previous + incoming

    def words(segments):
        result = []
        for index, segment in enumerate(segments):
            for match in re.finditer(r"\w+", segment.text, re.UNICODE):
                result.append((match.group().casefold(), index, match.end()))
        return result

    old = words(previous)
    new = words(incoming)
    # The incoming prefix must originate in the overlapping second. A small
    # lexical disagreement at its clipped beginning is allowed; the common
    # suffix still anchors the join. Require two words for such disagreement.
    for length in range(min(20, len(old), len(new)), 0, -1):
        tail = old[-length:]
        if previous[tail[-1][1]].end <= overlap_start:
            continue
        for prefix in range(min(3, len(new) - length + 1)):
            if prefix and length < 2:
                continue
            match = new[prefix:prefix + length]
            if incoming[match[0][1]].start >= boundary:
                continue
            if [w[0] for w in tail] != [w[0] for w in match]:
                continue
            index, end = match[-1][1:]
            remainder = incoming[index].text[end:]
            # Punctuation belonging to the shared final word is duplicated
            # too; keep whitespace before the next new word.
            remainder = re.sub(r"^[^\w\s]+", "", remainder)
            rest = ([Segment(incoming[index].start, incoming[index].end, remainder)]
                    if remainder else []) + incoming[index + 1:]
            while rest and not re.search(r"\w", rest[0].text):
                rest.pop(0)
            return previous + rest
    # Without a lexical anchor, make one chronological cut rather than
    # interleaving hypotheses. A segment spanning the cut must be retained
    # because it can contain speech beyond the previous window.
    return previous + [s for s in incoming if s.end > boundary]


def repetition_loop(text: str) -> bool:
    # Flag, never silently remove, a phrase repeated at least four times.
    words = text.casefold().split()
    for size in range(3, min(25, len(words) // 4) + 1):
        for start in range(len(words) - size * 4 + 1):
            phrase = words[start:start + size]
            if all(words[start + n * size:start + (n + 1) * size] == phrase for n in range(1, 4)):
                return True
    return False


def find_ffmpeg() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "ffmpeg" / "ffmpeg.exe"
    configured = os.environ.get("WINWHISPERPLUS_FFMPEG")
    if configured:
        return Path(configured)
    import imageio_ffmpeg
    return Path(imageio_ffmpeg.get_ffmpeg_exe())


def convert_audio(source: Path, destination: Path, cancel=None):
    """Convert using a file argument (no shell); retain stderr and clean failures."""
    if source.suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac"}:
        raise ValueError("Unsupported audio format")
    if source.resolve() == destination.resolve():
        raise ValueError("Source and destination must differ")
    if cancel and cancel.is_set():
        raise Cancelled("Cancelled")
    with tempfile.TemporaryFile() as error_log:
        process = subprocess.Popen([str(find_ffmpeg()), "-nostdin", "-hide_banner", "-loglevel", "error",
                                    "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
                                    "-c:a", "pcm_s16le", str(destination)],
                                   stdout=subprocess.DEVNULL, stderr=error_log,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            while process.poll() is None:
                if cancel and cancel.wait(0.1):
                    raise Cancelled("Cancelled")
                if not cancel:
                    import time
                    time.sleep(0.1)
            if process.returncode:
                error_log.seek(0)
                raise RuntimeError(error_log.read(8192).decode("utf-8", errors="replace"))
            if wav_duration(destination) <= 0:
                raise ValueError("Audio file is empty")
        except BaseException:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            destination.unlink(missing_ok=True)
            raise
