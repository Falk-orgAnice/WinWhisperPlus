"""
Headless smoke tests for the Application lifecycle.

These tests exercise the full signal/slot pipeline without touching real
hardware (microphone, clipboard, model files, hotkeys).  A QApplication
is created once per session; events are pumped manually via
``Application.wait_for_idle()``.

Run with::

    pytest tests/test_app_smoke.py -v
"""

from __future__ import annotations

import pytest
import numpy as np

from PyQt6.QtWidgets import QApplication

from app import Application
from tests.fakes import FakeRecorder, FakeTextOptimizer, FakeTranscriber, FakeTextSink


# ---------------------------------------------------------------------------
# Session-scoped QApplication (only one allowed per process)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Per-test helpers
# ---------------------------------------------------------------------------

def _make_app(
    qapp,
    *,
    live: bool = False,
    transcribe_text: str = "hello world",
    transcriber_raise: Exception | None = None,
    transcriber_delay: float = 0.0,
    text_optimizer: FakeTextOptimizer | None = None,
) -> tuple[Application, FakeRecorder, FakeTextSink]:
    """Build an Application in test mode with fake dependencies."""
    fake_final = FakeTranscriber(
        return_text=transcribe_text,
        delay=transcriber_delay,
        raise_exc=transcriber_raise,
    )
    fake_live = FakeTranscriber(return_text=transcribe_text)
    fake_sink = FakeTextSink()

    # Patch settings so live_transcription_enabled matches the *live* flag.
    fake_rec = FakeRecorder()
    app = Application(
        qapp,
        test_mode=True,
        recorder=fake_rec,
        transcriber_live=fake_live,
        transcriber_final=fake_final,
        text_optimizer=text_optimizer,
        text_sink=fake_sink,
    )
    # Override persisted user settings so smoke tests never start the real
    # bundled optimizer. Individual tests enable it explicitly with a fake.
    app._settings.live_transcription_enabled = live
    app._settings.text_optimization_enabled = False
    app._settings.text_optimization_formatting_enabled = True
    app._settings.text_optimization_cleanup_enabled = False
    app._settings.text_optimization_redact_enabled = False
    app._settings.text_translation_enabled = False
    app._settings.text_translation_target_language = "en"
    app._settings.emoji_mode_enabled = False
    # Re-wire on_chunk on the fake recorder to match the live setting
    app._recorder = app._build_recorder(app._settings)

    return app, fake_rec, fake_sink


# ---------------------------------------------------------------------------
# Test: App starts and reaches "ready"
# ---------------------------------------------------------------------------

class TestStartup:
    def test_start_reaches_ready(self, qapp):
        app, _, _ = _make_app(qapp)
        app.start()
        assert app.get_status() == "ready"

    def test_history_empty_at_start(self, qapp):
        app, _, _ = _make_app(qapp)
        app.start()
        assert app.get_history() == []

    def test_microphone_index_is_restored_from_name(self, qapp, monkeypatch):
        app, _, _ = _make_app(qapp)
        app._settings.microphone_index = 9
        app._settings.microphone_name = "Mikrofon 2"
        monkeypatch.setattr(app._settings, "save", lambda: None)

        import app as app_module

        monkeypatch.setattr(
            app_module,
            "list_microphones",
            lambda: [
                {"index": 3, "name": "Mikrofon 2"},
                {"index": 4, "name": "Mikrofon 3"},
            ],
        )

        resolved_index = app._resolve_microphone_index(app._settings)

        assert resolved_index == 3
        assert app._settings.microphone_index == 3
        assert app._settings.microphone_name == "Mikrofon 2"


# ---------------------------------------------------------------------------
# Test: Normal (non-live) record → stop → final transcription
# ---------------------------------------------------------------------------

class TestFinalTranscription:
    def test_record_stop_inserts_text(self, qapp):
        app, _, sink = _make_app(qapp, transcribe_text="guten morgen")
        app.start()

        app._toggle_recording()          # start
        assert app.get_status() == "recording"

        app._toggle_recording()          # stop → triggers final transcription
        idle = app.wait_for_idle(timeout_sec=8)

        assert idle, "App did not reach idle within timeout – possible hang"
        assert app.get_status() in ("inserted", "ready")
        assert app.get_history() == ["guten morgen"]

        # Text was delivered to the sink (direct insert or via replace)
        received = sink.all_text or sink.final_replaced_text() or ""
        assert "guten morgen" in received

    def test_record_stop_sequence_status_flow(self, qapp):
        """Status must pass through 'processing' before becoming 'inserted'."""
        statuses: list[str] = []

        app, _, _ = _make_app(qapp, transcribe_text="test")
        app._status_changed.connect(statuses.append)
        app.start()

        app._toggle_recording()
        app._toggle_recording()
        app.wait_for_idle(timeout_sec=8)

        assert "recording" in statuses
        assert "processing" in statuses
        assert "inserted" in statuses

    def test_history_grows_on_each_transcription(self, qapp):
        app, _, _ = _make_app(qapp, transcribe_text="eins")
        app.start()

        for _ in range(3):
            app._toggle_recording()
            app._toggle_recording()
            app.wait_for_idle(timeout_sec=8)

        assert len(app.get_history()) == 3

    def test_successful_transcription_records_statistics(self, qapp):
        app, _, _ = _make_app(qapp, transcribe_text="stat test")
        app.start()

        app._toggle_recording()
        app._toggle_recording()
        app.wait_for_idle(timeout_sec=8)

        day_rows = app._statistics.get_aggregates("day")
        assert len(day_rows) == 1
        assert day_rows[0]["count"] == 1
        assert day_rows[0]["total_seconds"] > 0.0

    def test_text_optimization_inserts_and_saves_optimized_text(self, qapp):
        optimizer = FakeTextOptimizer(return_text="Strukturiert.\n\n- Punkt")
        app, _, sink = _make_app(
            qapp,
            transcribe_text="strukturiert punkt",
            text_optimizer=optimizer,
        )
        app._settings.text_optimization_enabled = True
        app._settings.text_optimization_cleanup_enabled = True
        app.start()

        app._toggle_recording()
        app._toggle_recording()
        assert app.wait_for_idle(timeout_sec=8)
        _, options, language = optimizer.calls[0]
        assert options.formatting is True
        assert options.cleanup is True
        assert options.redact is False
        assert options.translation_target is None
        assert language == "de"
        assert app.get_history() == ["Strukturiert.\n\n- Punkt"]
        assert "Strukturiert." in sink.all_text

    def test_text_optimization_failure_retries_then_inserts_raw_text(self, qapp):
        optimizer = FakeTextOptimizer(raise_exc=RuntimeError("local model failed"))
        app, _, sink = _make_app(
            qapp,
            transcribe_text="roher text",
            text_optimizer=optimizer,
        )
        app._settings.text_optimization_enabled = True
        app.start()

        app._toggle_recording()
        app._toggle_recording()
        assert app.wait_for_idle(timeout_sec=8)
        assert app.get_history() == ["roher text"]
        assert "roher text" in sink.all_text

    def test_combined_text_options_include_translation_target(self, qapp):
        optimizer = FakeTextOptimizer(return_text="Translated text")
        app, _, _ = _make_app(qapp, transcribe_text="Original", text_optimizer=optimizer)
        app._settings.text_optimization_enabled = True
        app._settings.text_optimization_cleanup_enabled = True
        app._settings.text_optimization_redact_enabled = True
        app._settings.text_translation_enabled = True
        app._settings.text_translation_target_language = "en"
        app.start()

        app._toggle_recording()
        app._toggle_recording()
        assert app.wait_for_idle(timeout_sec=8)

        _, options, language = optimizer.calls[0]
        assert language == "de"
        assert options.formatting is True
        assert options.cleanup is True
        assert options.redact is True
        assert options.translation_target == "en"

# ---------------------------------------------------------------------------
# Test: Stop does not hang
# ---------------------------------------------------------------------------

class TestHangPrevention:
    def test_stop_does_not_hang(self, qapp):
        """wait_for_idle must return True well within the timeout."""
        app, _, _ = _make_app(qapp)
        app.start()
        app._toggle_recording()
        app._toggle_recording()

        reached = app.wait_for_idle(timeout_sec=10)
        assert reached, (
            f"App hung! status={app.get_status()!r} "
            f"recording={app._recorder.is_recording} "
            f"preloads={app._active_preloads} "
            f"queue_size={app._insert_queue.qsize()}"
        )

    def test_double_stop_is_safe(self, qapp):
        """Calling _stop_recording twice must not raise."""
        app, _, _ = _make_app(qapp)
        app.start()
        app._toggle_recording()   # start
        app._stop_recording()     # stop once
        app._stop_recording()     # stop again – should be a no-op
        assert app.wait_for_idle(timeout_sec=8)


# ---------------------------------------------------------------------------
# Test: Transcriber exception → app recovers
# ---------------------------------------------------------------------------

class TestErrorRecovery:
    def test_transcriber_exception_returns_to_ready(self, qapp):
        app, _, _ = _make_app(
            qapp,
            transcriber_raise=RuntimeError("model exploded"),
        )
        app.start()
        app._toggle_recording()
        app._toggle_recording()

        reached = app.wait_for_idle(timeout_sec=8)
        assert reached
        assert app.get_status() == "ready", (
            f"Expected 'ready' after exception, got {app.get_status()!r}"
        )
        # History must NOT contain anything (transcription failed)
        assert app.get_history() == []

    def test_transcriber_exception_does_not_hang(self, qapp):
        app, _, _ = _make_app(
            qapp,
            transcriber_raise=ValueError("bad audio"),
        )
        app.start()
        app._toggle_recording()
        app._toggle_recording()

        assert app.wait_for_idle(timeout_sec=8), "App hung after transcriber exception"

    def test_failed_transcription_does_not_record_statistics(self, qapp):
        app, _, _ = _make_app(
            qapp,
            transcriber_raise=RuntimeError("no model"),
        )
        app.start()

        app._toggle_recording()
        app._toggle_recording()
        app.wait_for_idle(timeout_sec=8)

        assert app._statistics.get_aggregates("day") == []


# ---------------------------------------------------------------------------
# Test: Live transcription (partial texts emitted before final)
# ---------------------------------------------------------------------------

class TestLiveTranscription:
    def test_live_partial_then_final(self, qapp):
        partials: list[str] = []

        app, _, sink = _make_app(qapp, live=True, transcribe_text="live text")
        app._partial_transcription_done.connect(partials.append)
        app.start()

        app._toggle_recording()   # FakeRecorder.start() delivers one chunk immediately
        # Give live worker a brief moment to process the synchronously delivered chunk
        app.wait_for_idle(timeout_sec=2)  # may not be fully idle yet

        app._toggle_recording()   # stop → final transcription
        app.wait_for_idle(timeout_sec=8)

        assert app.get_status() in ("inserted", "ready")
        # The live partial OR the final text should have reached the sink
        assert app.get_history() == ["live text"]
