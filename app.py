"""
Main application orchestrator.

Wires together:
  - Settings
  - Recorder
  - Transcriber
  - TextInserter
  - HotkeyManager
  - TrayIcon
  - SettingsWindow / StatusWindow
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from config.localization import localized_spoken_language_name, tr
from config.settings import Settings
from core.hotkey_manager import HotkeyManager
from core.live_text import extract_enter_command, merge_live_tail
from core.emoji_enricher import enrich_with_emojis
from core.failed_transcriptions import FailedTranscription, FailedTranscriptionStore
from core.recorder import Recorder, SAMPLE_RATE, list_microphones
from core.statistics import StatisticsStore
from core.text_inserter import insert_text, press_enter, replace_text
from core.transcriber import Transcriber
from gui.history_window import HistoryWindow
from gui.statistics_window import StatisticsWindow
from gui.settings_window import SettingsWindow
from gui.tray_icon import TrayIcon
from gui.status_window import StatusWindow


def _log_file_path() -> Path:
    """Return the per-user log path shared by the logger and menu action."""
    app_data = os.environ.get("APPDATA") or str(Path.home())
    return Path(app_data) / "WinWhisperPlus" / "winwhisperplus.log"


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("winwhisperplus")
    if logger.handlers:
        return logger

    log_file = _log_file_path()
    log_dir = log_file.parent
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(threadName)s %(message)s")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
        log_file = None

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.info("Logger initialisiert: %s", log_file or "<null>")
    return logger


LOGGER = _build_logger()


class Application(QObject):
    """Top-level application controller."""

    # Signals are used to safely update the Qt GUI from background threads
    _status_changed = pyqtSignal(str)
    _transcription_done = pyqtSignal(str, object)
    _transcription_failed = pyqtSignal(str, bool)
    _partial_transcription_done = pyqtSignal(str)
    _model_preload_started = pyqtSignal(str)
    _model_preload_finished = pyqtSignal(str, bool)
    _open_history_requested = pyqtSignal()
    _open_statistics_requested = pyqtSignal()
    _toggle_recording_requested = pyqtSignal()
    _cycle_language_requested = pyqtSignal()

    def __init__(
        self,
        qapp: QApplication,
        *,
        test_mode: bool = False,
        recorder=None,
        transcriber_live=None,
        transcriber_final=None,
        text_sink=None,
        status_window=None,
        settings=None,
        statistics_store=None,
        failed_transcription_dir=None,
    ) -> None:
        super().__init__()
        self._qapp = qapp
        self._test_mode = test_mode
        self._text_sink = text_sink   # object with insert_text/replace_text/press_enter; None → real OS calls
        self._status = "initializing"
        # Use pre-loaded settings from main.py if provided (avoids re-reading disk)
        self._settings = settings if settings is not None else Settings()
        self._statistics = (
            statistics_store if statistics_store is not None else StatisticsStore(persist=not test_mode)
        )
        LOGGER.info(
            "App start | live_enabled=%s live_model=%s final_model=%s test_mode=%s",
            self._settings.live_transcription_enabled,
            self._settings.live_whisper_model,
            self._settings.final_whisper_model,
            test_mode,
        )
        self._transcriber_live = transcriber_live or Transcriber(
            model_name=self._settings.live_whisper_model,
            compute_device=self._settings.compute_device,
            keep_model_loaded=self._settings.keep_model_loaded,
        )
        self._transcriber_final = transcriber_final or Transcriber(
            model_name=self._settings.final_whisper_model,
            compute_device=self._settings.compute_device,
            keep_model_loaded=self._settings.keep_model_loaded,
        )
        self._injected_recorder = recorder   # kept to skip rebuild in test mode
        self._hotkey_mgr = HotkeyManager()
        self._history: list[str] = []  # Session history of recognized texts (max 50)
        self._max_history = 50
        self._audio_chunk_queue: queue.Queue = queue.Queue(maxsize=8)
        self._insert_queue: queue.Queue = queue.Queue()
        self._live_stop_requested = threading.Event()
        self._live_worker: threading.Thread | None = None
        self._committed_live_text = ""
        self._tail_live_text = ""
        self._rendered_live_text = ""
        self._last_live_emit_at = 0.0
        self._active_preloads = 0
        self._recording_started_at: datetime | None = None
        self._last_recording_duration_seconds = 0.0
        self._pending_stats_session = False
        self._failed_transcriptions = (
            FailedTranscriptionStore(failed_transcription_dir)
            if not test_mode or failed_transcription_dir is not None
            else None
        )
        self._recorder = self._build_recorder(self._settings)

        self._insertion_worker = threading.Thread(
            target=self._run_insertion_worker,
            daemon=True,
        )
        self._insertion_worker.start()

        # GUI – skipped in headless test mode.
        # Reuse a pre-created StatusWindow if main.py already showed one,
        # otherwise create it here (fallback for direct instantiation in tests etc.)
        if not test_mode:
            self._tray = TrayIcon(parent=self, settings=self._settings)
            self._status_window = status_window or StatusWindow(
                hotkey_record=self._settings.hotkey_record, settings=self._settings
            )
            self._history_window = HistoryWindow(parent=None, settings=self._settings)
            self._statistics_window = StatisticsWindow(parent=None, settings=self._settings)

        self._connect_signals()
        # NOTE: _apply_settings() is intentionally NOT called here.
        # It is called once in start(), after the window is already visible.

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Complete initialization and make the application ready.

        When launched via main.py the StatusWindow is already visible (shown
        before the heavy imports).  start() shows the tray icon, registers
        hotkeys, schedules model pre-loading, and emits the "ready" signal.
        """
        if not self._test_mode:
            self._tray.show()
            # Keep status at "initializing" until all startup work is complete.
            self._status_changed.emit("initializing")
            # If the window was NOT pre-created by main.py (e.g. direct usage),
            # show it here with the loading spinner as a fallback.
            if not self._status_window.isVisible():
                self._status_window.load_position()
                self._status_window.set_loading(True, tr("loading_app", self._settings))
                self._status_window.show()

        # Register hotkeys, wire recorder/transcriber, schedule model pre-load.
        self._apply_settings(self._settings)

        # In headless tests no GUI preload runs; keep previous behavior.
        if self._test_mode:
            self._status_changed.emit("ready")

    def shutdown(self) -> None:
        self._hotkey_mgr.unregister_all()
        self._live_stop_requested.set()
        if self._recorder.is_recording:
            self._recorder.stop()
        self._transcriber_live.close()
        self._transcriber_final.close()

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        # Route cross-thread requests safely into the Qt main thread.
        self._toggle_recording_requested.connect(self._toggle_recording)
        self._cycle_language_requested.connect(self._cycle_language)

        if not self._test_mode:
            self._tray.toggle_recording_requested.connect(self._toggle_recording)
            self._tray.open_settings_requested.connect(self._open_settings)
            self._tray.open_history_requested.connect(self._open_history)
            self._tray.open_statistics_requested.connect(self._open_statistics)
            self._tray.open_log_requested.connect(self._open_log)
            self._tray.retry_failed_transcription_requested.connect(self._retry_last_failed_transcription)
            self._tray.quit_requested.connect(self._quit)

            # Connect StatusWindow signals to same handlers as TrayIcon
            self._status_window.toggle_recording_requested.connect(self._toggle_recording)
            self._status_window.open_settings_requested.connect(self._open_settings)
            self._status_window.open_history_requested.connect(self._open_history)
            self._status_window.open_statistics_requested.connect(self._open_statistics)
            self._status_window.open_log_requested.connect(self._open_log)
            self._status_window.retry_failed_transcription_requested.connect(self._retry_last_failed_transcription)
            self._status_window.quit_requested.connect(self._quit)

            self._history_window.text_selected.connect(self._on_history_text_selected)

        self._status_changed.connect(self._on_status_changed)
        self._transcription_done.connect(self._on_transcription_done)
        self._transcription_failed.connect(self._on_transcription_failed)
        self._partial_transcription_done.connect(self._on_partial_transcription_done)
        self._model_preload_started.connect(self._on_model_preload_started)
        self._model_preload_finished.connect(self._on_model_preload_finished)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _apply_settings(self, settings: Settings) -> None:
        """Register hotkeys and update recorder/transcriber from settings."""
        if not self._test_mode:
            self._hotkey_mgr.unregister_all()
            # keyboard callbacks can arrive on a background thread;
            # emit Qt signals so UI work executes on the main thread.
            self._hotkey_mgr.register(
                settings.hotkey_record,
                self._toggle_recording_requested.emit,
            )
            self._hotkey_mgr.register(
                settings.hotkey_language,
                self._cycle_language_requested.emit,
            )
        self._recorder = self._build_recorder(settings)
        self._transcriber_live.set_model(settings.live_whisper_model)
        self._transcriber_final.set_model(settings.final_whisper_model)
        self._transcriber_live.set_compute_device(settings.compute_device)
        self._transcriber_final.set_compute_device(settings.compute_device)
        self._transcriber_live.set_keep_model_loaded(settings.keep_model_loaded)
        self._transcriber_final.set_keep_model_loaded(settings.keep_model_loaded)
        LOGGER.info(
            "Settings angewendet | live_enabled=%s live_model=%s final_model=%s compute_device=%s keep_model_loaded=%s",
            settings.live_transcription_enabled,
            settings.live_whisper_model,
            settings.final_whisper_model,
            settings.compute_device,
            settings.keep_model_loaded,
        )
        if not self._test_mode:
            # Update the displayed hotkey in the status window
            self._status_window.set_hotkey(settings.hotkey_record)
            self._status_window.retranslate_ui()
            self._tray.retranslate_ui(self._status)
            self._history_window.retranslate_ui()
            self._statistics_window.retranslate_ui()
            # Schedule model preloading to start after UI is ready
            self._schedule_model_preload(delay_ms=250)

    def _schedule_model_preload(self, delay_ms: int) -> None:
        QTimer.singleShot(delay_ms, self._preload_models_async)

    def _preload_models_async(self) -> None:
        threading.Thread(target=self._load_live_model, daemon=True).start()
        threading.Thread(target=self._load_final_model, daemon=True).start()

    def _load_live_model(self) -> None:
        self._model_preload_started.emit("live")
        try:
            LOGGER.info("Preload Live-Modell gestartet | model=%s", self._settings.live_whisper_model)
            self._transcriber_live.load()
            LOGGER.info("Preload Live-Modell fertig | model=%s", self._settings.live_whisper_model)
            self._model_preload_finished.emit("live", True)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Preload Live-Modell fehlgeschlagen")
            self._model_preload_finished.emit("live", False)

    def _load_final_model(self) -> None:
        self._model_preload_started.emit("final")
        try:
            LOGGER.info("Preload Final-Modell gestartet | model=%s", self._settings.final_whisper_model)
            self._transcriber_final.load()
            LOGGER.info("Preload Final-Modell fertig | model=%s", self._settings.final_whisper_model)
            self._model_preload_finished.emit("final", True)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Preload Final-Modell fehlgeschlagen")
            self._model_preload_finished.emit("final", False)

    def _build_recorder(self, settings: Settings) -> Recorder:
        on_chunk = self._on_audio_chunk if settings.live_transcription_enabled else None
        resolved_device_index = self._resolve_microphone_index(settings)
        if self._injected_recorder is not None:
            # Wire live callback onto the injected recorder instead of creating a new one
            self._injected_recorder._on_chunk = on_chunk
            return self._injected_recorder
        return Recorder(
            device_index=resolved_device_index,
            on_chunk=on_chunk,
            chunk_seconds=settings.live_chunk_seconds,
            overlap_seconds=settings.live_overlap_seconds,
        )

    def _resolve_microphone_index(self, settings: Settings):
        requested_index = settings.microphone_index
        requested_name = settings.microphone_name
        if requested_index is None and not requested_name:
            return None

        microphones = list_microphones()
        by_index = {mic["index"]: mic["name"] for mic in microphones}

        if requested_index in by_index:
            current_name = by_index[requested_index]
            if settings.microphone_name != current_name:
                settings.microphone_name = current_name
                settings.save()
            return requested_index

        if requested_name:
            for mic in microphones:
                if mic["name"] == requested_name:
                    settings.microphone_index = mic["index"]
                    settings.save()
                    return mic["index"]

        settings.microphone_index = None
        settings.microphone_name = None
        settings.save()
        return None

    def _open_settings(self) -> None:
        dlg = SettingsWindow(self._settings)
        dlg.settings_saved.connect(self._apply_settings)
        dlg.exec()

    def _open_log(self) -> None:
        log_path = _log_file_path()
        try:
            os.startfile(str(log_path))
            LOGGER.info("Logdatei über Kontextmenü geöffnet | path=%s", log_path)
        except OSError:
            LOGGER.exception("Logdatei kann nicht geöffnet werden | path=%s", log_path)
            if not self._test_mode:
                self._status_window.show_message(tr("log_open_failed", self._settings))

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _toggle_recording(self) -> None:
        if self._recorder.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        if not self._test_mode:
            # Ensure window is visible when recording starts
            self._status_window.raise_()
            self._status_window.showNormal()
        LOGGER.info("Aufnahme gestartet")
        self._recording_started_at = datetime.now()
        self._last_recording_duration_seconds = 0.0
        self._pending_stats_session = False
        self._reset_live_session()
        if self._settings.live_transcription_enabled:
            self._start_live_worker(self._settings.language)
        self._recorder.start()
        self._status_changed.emit("recording")

    def _stop_recording(self) -> None:
        LOGGER.info("Aufnahme wird gestoppt")
        audio = self._recorder.stop()
        LOGGER.info("Audio gestoppt | samples=%s", len(audio))
        self._last_recording_duration_seconds = len(audio) / SAMPLE_RATE if len(audio) else 0.0
        self._pending_stats_session = True
        self._status_changed.emit("processing")
        self._stop_live_worker()
        language = self._settings.language
        LOGGER.info("Starte finale Transkriptions-Thread | language=%s", language)
        # Run transcription in a daemon thread to keep the UI responsive
        threading.Thread(
            target=self._transcribe_and_emit,
            args=(audio, language),
            daemon=True,
        ).start()

    def _transcribe_and_emit(
        self,
        audio,
        language: str,
        recovered_recording: FailedTranscription | None = None,
    ) -> None:
        start = time.monotonic()
        LOGGER.info(
            "Finale Transkription gestartet | samples=%s recovered_recording=%s",
            len(audio),
            recovered_recording.audio_path if recovered_recording else None,
        )
        try:
            text = self._transcriber_final.transcribe(audio, language=language)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Finale Transkription fehlgeschlagen")
            recording_saved = recovered_recording is not None
            if recovered_recording is None and self._failed_transcriptions is not None:
                try:
                    recovered_recording = self._failed_transcriptions.save(audio, language)
                    recording_saved = True
                    LOGGER.info(
                        "Fehlgeschlagene Aufnahme gesichert | path=%s language=%s samples=%s",
                        recovered_recording.audio_path,
                        language,
                        len(audio),
                    )
                except OSError:
                    LOGGER.exception("Fehlgeschlagene Aufnahme konnte nicht gesichert werden")
            self._transcription_failed.emit(str(exc), recording_saved)
            return

        elapsed = time.monotonic() - start
        LOGGER.info("Finale Transkription fertig | chars=%s duration=%.2fs", len(text), elapsed)
        self._transcription_done.emit(text, recovered_recording)

    def _retry_last_failed_transcription(self) -> None:
        recording = self._failed_transcriptions.latest() if self._failed_transcriptions is not None else None
        if recording is None:
            LOGGER.info("Keine gesicherte Aufnahme zum erneuten Transkribieren gefunden")
            if not self._test_mode:
                self._status_window.show_message(tr("no_saved_transcription", self._settings))
            return
        try:
            assert self._failed_transcriptions is not None
            audio = self._failed_transcriptions.load_audio(recording)
        except (OSError, ValueError):
            LOGGER.exception("Gesicherte Aufnahme kann nicht gelesen werden | path=%s", recording.audio_path)
            if not self._test_mode:
                self._status_window.show_message(tr("saved_transcription_unreadable", self._settings))
            return

        LOGGER.info("Wiederhole gesicherte Aufnahme | path=%s language=%s samples=%s", recording.audio_path, recording.language, len(audio))
        self._recording_started_at = datetime.now()
        self._last_recording_duration_seconds = len(audio) / SAMPLE_RATE if len(audio) else 0.0
        self._pending_stats_session = True
        self._status_changed.emit("processing")
        threading.Thread(
            target=self._transcribe_and_emit,
            args=(audio, recording.language, recording),
            daemon=True,
        ).start()

    def _on_audio_chunk(self, audio_chunk) -> None:
        try:
            self._audio_chunk_queue.put_nowait(audio_chunk)
        except queue.Full:
            LOGGER.warning("Audio-Chunk verworfen (Queue voll)")

    def _start_live_worker(self, language: str) -> None:
        self._live_stop_requested.clear()
        LOGGER.info("Live-Worker gestartet | language=%s", language)
        self._live_worker = threading.Thread(
            target=self._run_live_worker,
            args=(language,),
            daemon=True,
        )
        self._live_worker.start()

    def _stop_live_worker(self) -> None:
        self._live_stop_requested.set()
        self._drain_queue(self._audio_chunk_queue)
        if self._live_worker is not None:
            # Do not block stop/final transcription while a chunk inference is still running.
            self._live_worker.join(timeout=0.2)
            if self._live_worker.is_alive():
                LOGGER.warning("Live-Worker läuft noch kurz im Hintergrund aus")
            else:
                LOGGER.info("Live-Worker beendet")
            self._live_worker = None

    def _run_live_worker(self, language: str) -> None:
        tail_samples = max(1, int(self._settings.live_stable_window_seconds * SAMPLE_RATE))
        while not self._live_stop_requested.is_set():
            try:
                audio_chunk = self._audio_chunk_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                if len(audio_chunk) > tail_samples:
                    audio_for_live = audio_chunk[-tail_samples:]
                else:
                    audio_for_live = audio_chunk
                start = time.monotonic()
                text = self._transcriber_live.transcribe_chunk(audio_for_live, language=language)
                elapsed = time.monotonic() - start
                LOGGER.info(
                    "Live-Chunk transkribiert | input_samples=%s tail_samples=%s chars=%s duration=%.2fs",
                    len(audio_chunk),
                    len(audio_for_live),
                    len(text),
                    elapsed,
                )
            except Exception:  # noqa: BLE001
                LOGGER.exception("Live-Transkription fehlgeschlagen")
                text = ""
            finally:
                self._audio_chunk_queue.task_done()

            if self._live_stop_requested.is_set():
                continue

            if text:
                self._partial_transcription_done.emit(text)

    def _run_insertion_worker(self) -> None:
        while True:
            action, *payload = self._insert_queue.get()
            try:
                if action == "insert":
                    time.sleep(0.2)
                    self._do_insert(payload[0])
                elif action == "replace":
                    time.sleep(0.2)
                    self._do_replace(payload[0], payload[1])
                elif action == "enter":
                    time.sleep(0.3)
                    self._do_enter()
            except Exception:  # noqa: BLE001
                LOGGER.exception("Einfüge-Worker Fehler | action=%s", action)
            finally:
                self._insert_queue.task_done()

    def _do_insert(self, text: str) -> None:
        if self._text_sink is not None:
            self._text_sink.insert_text(text)
        else:
            insert_text(text)

    def _do_replace(self, previous: str, new: str) -> None:
        if self._text_sink is not None:
            self._text_sink.replace_text(previous, new)
        else:
            replace_text(previous, new)

    def _do_enter(self) -> None:
        if self._text_sink is not None:
            self._text_sink.press_enter()
        else:
            press_enter()

    def _reset_live_session(self) -> None:
        self._drain_queue(self._audio_chunk_queue)
        self._committed_live_text = ""
        self._tail_live_text = ""
        self._rendered_live_text = ""
        self._last_live_emit_at = 0.0
        LOGGER.info("Live-Session zurückgesetzt")

    def _drain_queue(self, work_queue: queue.Queue) -> None:
        while True:
            try:
                work_queue.get_nowait()
            except queue.Empty:
                return
            else:
                work_queue.task_done()

    def _queue_insert(self, text: str) -> None:
        if text:
            self._insert_queue.put(("insert", text))

    def _queue_replace(self, previous_text: str, new_text: str) -> None:
        if previous_text == new_text:
            return
        self._insert_queue.put(("replace", previous_text, new_text))

    def _queue_enter(self) -> None:
        self._insert_queue.put(("enter",))

    # ------------------------------------------------------------------
    # Language cycling
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _cycle_language(self) -> None:
        lang = self._settings.cycle_language()
        self._settings.save()
        if not self._test_mode:
            lang_name = localized_spoken_language_name(lang, self._settings)
            self._status_window.show_message(tr("language_message", self._settings, language=lang_name))

    # ------------------------------------------------------------------
    # Slots (always run on the Qt main thread via signal)
    # ------------------------------------------------------------------

    @pyqtSlot(str)
    def _on_status_changed(self, status: str) -> None:
        self._status = status
        if not self._test_mode:
            self._tray.set_status(status)
            self._status_window.set_status(status)
            if status == "initializing":
                if self._active_preloads > 0:
                    self._status_window.set_loading(
                        True,
                        tr("loading_models", self._settings, count=self._active_preloads),
                    )
                else:
                    self._status_window.set_loading(True, tr("loading_app", self._settings))
            elif status == "processing":
                self._status_window.set_loading(True, tr("processing", self._settings))
            elif self._active_preloads > 0:
                self._status_window.set_loading(
                    True,
                    tr("loading_models", self._settings, count=self._active_preloads),
                )
            else:
                self._status_window.set_loading(False)

    @pyqtSlot(str, object)
    def _on_transcription_done(self, text: str, recovered_recording: FailedTranscription | None = None) -> None:
        LOGGER.info("Transkription empfangen | chars=%s", len(text or ""))
        if self._pending_stats_session and self._recording_started_at is not None:
            self._statistics.record_session(
                started_at=self._recording_started_at,
                duration_seconds=self._last_recording_duration_seconds,
                language=self._settings.language,
            )
        self._pending_stats_session = False
        self._recording_started_at = None
        self._last_recording_duration_seconds = 0.0
        # Save to history
        if text and text.strip():
            self._history.append(text)
            # Keep only last 50 items
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
        final_text, should_press_enter = extract_enter_command(text)
        if self._settings.emoji_mode_enabled:
            final_text = enrich_with_emojis(final_text, language=self._settings.language)
        if self._settings.auto_insert:
            if self._settings.live_transcription_enabled:
                self._queue_replace(self._rendered_live_text, final_text)
                self._committed_live_text = ""
                self._tail_live_text = ""
                self._rendered_live_text = ""
            else:
                self._queue_insert(final_text)
            if should_press_enter:
                self._queue_enter()

        if recovered_recording is not None and self._failed_transcriptions is not None:
            try:
                self._failed_transcriptions.delete(recovered_recording)
                LOGGER.info("Erfolgreich wiederhergestellte Aufnahme entfernt | path=%s", recovered_recording.audio_path)
            except OSError:
                LOGGER.exception("Erfolgreich wiederhergestellte Aufnahme konnte nicht entfernt werden")

        self._status_changed.emit("inserted")
        # Reset to ready after a moment so the user sees the confirmation
        threading.Timer(2.0, lambda: self._status_changed.emit("ready")).start()

    @pyqtSlot(str, bool)
    def _on_transcription_failed(self, message: str, recording_saved: bool) -> None:
        LOGGER.error("Transkription fehlgeschlagen | %s", message)
        self._pending_stats_session = False
        self._recording_started_at = None
        self._last_recording_duration_seconds = 0.0
        if not self._test_mode:
            message_key = "transcription_saved" if recording_saved else "transcription_failed"
            self._status_window.show_message(tr(message_key, self._settings), duration_ms=6000)
        self._status_changed.emit("ready")

    @pyqtSlot(str)
    def _on_model_preload_started(self, model_kind: str) -> None:
        self._active_preloads += 1
        LOGGER.info("UI Preload gestartet | kind=%s active=%s", model_kind, self._active_preloads)
        if not self._test_mode:
            model_name = self._settings.live_whisper_model if model_kind == "live" else self._settings.final_whisper_model
            model_kind_label = tr(f"model_kind_{model_kind}", self._settings)
            self._status_window.set_loading(
                True,
                tr("loading_model_kind", self._settings, model_kind=model_kind_label, model_name=model_name)
            )

    @pyqtSlot(str, bool)
    def _on_model_preload_finished(self, model_kind: str, success: bool) -> None:
        self._active_preloads = max(0, self._active_preloads - 1)
        LOGGER.info(
            "UI Preload beendet | kind=%s success=%s active=%s",
            model_kind,
            success,
            self._active_preloads,
        )
        if self._test_mode:
            return
        if self._active_preloads > 0:
            # Still loading other models
            remaining_model = "final" if model_kind == "live" else "live"
            model_name = self._settings.final_whisper_model if remaining_model == "final" else self._settings.live_whisper_model
            model_kind_label = tr(f"model_kind_{remaining_model}", self._settings)
            self._status_window.set_loading(
                True,
                tr("loading_model_kind", self._settings, model_kind=model_kind_label, model_name=model_name)
            )
            return
        # All models loaded
        self._status_window.set_loading(False)
        if not success:
            self._status_window.show_message(tr("model_load_failed", self._settings))
        self._status_changed.emit("ready")

    @pyqtSlot(str)
    def _on_partial_transcription_done(self, text: str) -> None:
        if not self._settings.auto_insert:
            return

        now = time.monotonic()
        if now - self._last_live_emit_at < self._settings.live_emit_min_interval_seconds:
            return

        (
            self._committed_live_text,
            self._tail_live_text,
            new_rendered_text,
        ) = merge_live_tail(
            self._committed_live_text,
            self._tail_live_text,
            text,
        )
        if new_rendered_text == self._rendered_live_text:
            return
        self._queue_replace(self._rendered_live_text, new_rendered_text)
        self._rendered_live_text = new_rendered_text
        self._last_live_emit_at = now
        LOGGER.info(
            "Live-Text aktualisiert | committed_words=%s tail_words=%s rendered_words=%s",
            len(self._committed_live_text.split()),
            len(self._tail_live_text.split()),
            len(self._rendered_live_text.split()),
        )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _open_history(self) -> None:
        """Show history window with recent transcriptions."""
        if not self._test_mode:
            self._history_window.set_history(self._history)
            self._history_window.show()

    @pyqtSlot()
    def _open_statistics(self) -> None:
        """Show statistics window with period aggregates."""
        if not self._test_mode:
            self._statistics_window.set_data(
                day_rows=self._statistics.get_aggregates("day"),
                week_rows=self._statistics.get_aggregates("week"),
                month_rows=self._statistics.get_aggregates("month"),
            )
            self._statistics_window.show()
            self._statistics_window.raise_()

    @pyqtSlot(str)
    def _on_history_text_selected(self, text: str) -> None:
        """Handle text selected from history - insert it."""
        if text:
            self._queue_insert(text)
            self._status_changed.emit("inserted")
            threading.Timer(2.0, lambda: self._status_changed.emit("ready")).start()

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _quit(self) -> None:
        self.shutdown()
        self._qapp.quit()

    # ------------------------------------------------------------------
    # Testability hooks
    # ------------------------------------------------------------------

    def get_status(self) -> str:
        """Return the current application status string."""
        return self._status

    def get_history(self) -> list[str]:
        """Return a copy of the transcription history."""
        return list(self._history)

    def wait_for_idle(self, timeout_sec: float = 10.0) -> bool:
        """Block (pumping Qt events) until the app is idle or *timeout_sec* elapses.

        Returns True if idle was reached, False on timeout.
        Useful for headless smoke tests.
        """
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if self._is_idle():
                return True
            time.sleep(0.05)
        return False

    def _is_idle(self) -> bool:
        # unfinished_tasks == 0 means all queued inserts have been task_done()'d,
        # i.e. the insertion worker has fully dispatched them (not just dequeued).
        return (
            not self._recorder.is_recording
            and self._active_preloads == 0
            and self._insert_queue.unfinished_tasks == 0
            and self._status in ("ready", "inserted", "")
        )
