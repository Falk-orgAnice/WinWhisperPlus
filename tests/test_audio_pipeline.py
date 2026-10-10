from pathlib import Path
import threading
import wave
import numpy as np
import pytest
from core.audio import Segment, audio_windows, merge_segments, repetition_loop
from core.session import SessionStore, ResultVersion
from core.pipeline import run_job
from config.settings import Settings


def write_audio(path, seconds, tail=0):
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", ""))
        block = np.full(16000, 327, dtype="<i2").tobytes()
        for _ in range(seconds):
            wav.writeframesraw(block)
        if tail:
            wav.writeframesraw(np.full(tail, 1000, dtype="<i2").tobytes())


class TimestampTranscriber:
    def __init__(self):
        self.calls = 0
        self.fail = set()
    def transcribe_segments(self, audio, language, **kwargs):
        self.calls += 1
        if self.calls in self.fail:
            raise RuntimeError("section failed")
        return [Segment(0, len(audio)/16000, f" section{self.calls}.")], language or "de"


class Optimizer:
    def __init__(self, broken=False):
        self.broken = broken
    def optimize(self, text, **kwargs):
        if self.broken:
            raise RuntimeError("translation failed")
        return text


def test_two_hour_windows_include_short_end_and_bound_memory(tmp_path):
    path = tmp_path / "long.wav"
    write_audio(path, 7200, tail=3)
    last = None
    covered_until = 0
    for start, samples in audio_windows(path):
        assert len(samples) <= 30 * 16000
        assert start <= covered_until
        covered_until = start + len(samples)/16000
        last = samples
    assert covered_until == pytest.approx(7200 + 3/16000)
    assert len(last) > 0
    from core.session import AudioJob
    class EndTranscriber(TimestampTranscriber):
        def transcribe_segments(self, audio, language, **kwargs):
            self.calls += 1
            text = " Final spoken sentence." if audio[-1] > 0.02 else f" Section {self.calls}."
            return [Segment(0, len(audio)/16000, text)], "de"
    version = ResultVersion("small", "de", None)
    run_job(AudioJob(path, source="file"), version, Settings(), EndTranscriber(), Optimizer())
    assert version.status == "complete"
    assert version.raw_text.endswith("Final spoken sentence.")


def test_dedup_only_matching_overlapping_audio():
    previous = [Segment(0, 1, " hello"), Segment(28.5, 29.8, " again")]
    incoming = [Segment(28.6, 29.8, " again"), Segment(30, 31, " again")]
    assert merge_segments(previous, incoming, 29) == previous + [incoming[1]]


def test_conflicting_overlap_hypotheses_never_interleave_words():
    previous = [Segment(27, 28, " your country"), Segment(28, 29, " can do"),
                Segment(29, 30, " for you.")]
    incoming = [Segment(29, 29.5, " What the"), Segment(29.5, 30.1, " country"),
                Segment(30.1, 30.5, " can do"), Segment(30.5, 31, " for you,"),
                Segment(31, 32, " ask what you can do for your country.")]
    merged = merge_segments(previous, incoming, 29)
    assert "".join(s.text for s in merged) == (
        " your country can do for you. ask what you can do for your country.")


def test_same_phrase_after_overlap_is_preserved():
    previous = [Segment(28, 30, " Repeat these words.")]
    incoming = [Segment(30.1, 31.8, " Repeat these words.")]
    assert merge_segments(previous, incoming, 29) == previous + incoming


def test_unaligned_overlap_keeps_one_ordered_hypothesis():
    previous = [Segment(29, 30, " previous words")]
    incoming = [Segment(29, 29.5, " competing"), Segment(30, 31, " next words")]
    assert merge_segments(previous, incoming, 29) == previous + [incoming[1]]


def test_source_survives_failed_translation_and_sections_retry(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    job = store.create("file")
    write_audio(job.audio_path, 61)
    settings = Settings()
    version = ResultVersion("small", "de", "en")
    transcriber = TimestampTranscriber()
    transcriber.fail = {2}
    run_job(job, version, settings, transcriber, Optimizer())
    assert version.status == "failed"
    assert len(version.sections) == 3
    assert transcriber.calls == 3
    run_job(job, version, settings, transcriber, Optimizer(broken=True))
    assert transcriber.calls == 4  # successful sections reused
    assert version.status == "translation_failed"
    assert version.raw_text
    assert version.text == ""
    store.close()


def test_text_model_preparation_reports_progress_after_raw_transcript(tmp_path):
    from core.session import AudioJob
    path = tmp_path / "speech.wav"
    write_audio(path, 1)
    job = AudioJob(path, source="file")
    version = ResultVersion("small", "de", "en")
    class PreparingOptimizer(Optimizer):
        def prepare(self, *, cancel, progress):
            assert version.raw_text  # recognition must finish before downloads
            progress(50, 100)
            raise OSError("download failed")
    phases = []
    run_job(job, version, Settings(), TimestampTranscriber(), PreparingOptimizer(),
            lambda _value: phases.append(job.phase))
    assert version.status == "translation_failed"
    assert version.raw_text and not version.text
    assert any("50%" in phase for phase in phases)
    assert "download failed" in version.error


def test_import_does_not_consume_enter_and_names_survive(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    job = store.create("file")
    write_audio(job.audio_path, 1)
    class Transcriber:
        def transcribe_segments(self, *_args, **_kwargs):
            return [Segment(0, 1, "Organize enter")], "de"
    settings = Settings()
    settings.correction_rules = [{"source": "Organize", "target": "orgAnice"}]
    version = ResultVersion("small", None, "en")
    assert run_job(job, version, settings, Transcriber(), Optimizer()) is False
    assert version.raw_text == "Organize enter"
    assert version.text == "orgAnice enter"
    assert version.language == "de"
    store.close()


def test_formatting_failure_keeps_corrected_source_for_safe_fallback(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    job = store.create()
    write_audio(job.audio_path, 1)
    settings = Settings()
    settings.text_optimization_enabled = True
    version = ResultVersion("small", "de", None)
    run_job(job, version, settings, TimestampTranscriber(), Optimizer(broken=True))
    assert version.status == "optimization_failed"
    assert version.text == version.corrected_text
    assert version.raw_text
    store.close()


def test_cancellation_and_session_cleanup(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    job = store.create()
    write_audio(job.audio_path, 1)
    job.cancel.set()
    version = ResultVersion("small", "de", None)
    run_job(job, version, Settings(), TimestampTranscriber(), Optimizer())
    assert version.status == "cancelled"
    assert job.audio_path.exists()
    directory = store.directory
    store.close()
    assert not directory.exists()


def test_repetition_detection_flags_without_deleting():
    assert repetition_loop("one two three " * 4)
    assert not repetition_loop("yes yes yes yes")


def test_active_session_is_not_cleaned_by_second_instance(tmp_path):
    first = SessionStore(tmp_path / "sessions")
    second = SessionStore(tmp_path / "sessions")
    assert first.directory.exists()
    second.close()
    first.close()
