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
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from config.localization import localized_spoken_language_name, tr
from config.settings import Settings
from core.hotkey_manager import HotkeyManager
from core.live_text import extract_enter_command, merge_live_tail
from core.emoji_enricher import enrich_with_emojis
from core.recorder import Recorder, SAMPLE_RATE, list_microphones
from core.statistics import StatisticsStore
from core.text_inserter import insert_text, press_enter, replace_text
from core.text_optimizer import TextOptimizationOptions, TextOptimizer
from core.transcriber import Transcriber
from core.corrections import apply_corrections, protect_names, restore_names
from core.session import SessionStore, ResultVersion
from core.pipeline import run_job
from core.audio import convert_audio, wav_duration
from gui.history_window import HistoryWindow
from gui.statistics_window import StatisticsWindow
from gui.settings_window import SettingsWindow
from gui.tray_icon import TrayIcon
from gui.status_window import StatusWindow


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("winwhisperplus")
    if logger.handlers:
        return logger

    app_data = os.environ.get("APPDATA") or str(Path.home())
    log_dir = Path(app_data) / "WinWhisperPlus"
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(threadName)s %(message)s")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "winwhisperplus.log"
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
    _transcription_done = pyqtSignal(str)
    _transcription_failed = pyqtSignal(str)
    _text_optimization_done = pyqtSignal(str, bool, bool)
    _partial_transcription_done = pyqtSignal(str)
    _model_preload_started = pyqtSignal(str)
    _model_preload_finished = pyqtSignal(str, bool)
    _open_history_requested = pyqtSignal()
    _open_statistics_requested = pyqtSignal()
    _toggle_recording_requested = pyqtSignal()
    _cycle_language_requested = pyqtSignal()
    _job_finished = pyqtSignal(object, object, object, bool, bool)
    _job_progress = pyqtSignal(object)

    def __init__(
        self,
        qapp: QApplication,
        *,
        test_mode: bool = False,
        recorder=None,
        transcriber_live=None,
        transcriber_final=None,
        text_optimizer=None,
        text_sink=None,
        status_window=None,
        settings=None,
        statistics_store=None,
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
        self._text_optimizer = text_optimizer or TextOptimizer(
            compute_device=self._settings.compute_device,
        )
        self._injected_recorder = recorder   # kept to skip rebuild in test mode
        self._hotkey_mgr = HotkeyManager()
        self._history: list[str] = []  # Session history of recognized texts (max 50)
        self._max_history = 50
        self._session = SessionStore() if not test_mode else None
        self._recording_job = None
        self._recording_settings = None
        self._job_lock = threading.Lock()
        self._job_threads = []
        self._closing = False
        self._recording_health = QTimer(self)
        self._recording_health.timeout.connect(self._check_recording_health)
        if not test_mode:
            self._recording_health.start(250)
        self._audio_chunk_queue: queue.Queue = queue.Queue(maxsize=8)
        self._insert_queue: queue.Queue = queue.Queue()
        self._live_stop_requested = threading.Event()
        self._live_worker: threading.Thread | None = None
        self._committed_live_text = ""
        self._tail_live_text = ""
        self._rendered_live_text = ""
        self._last_live_emit_at = 0.0
        self._active_preloads = 0
        self._active_text_optimizations = 0
        self._recording_started_at: datetime | None = None
        self._last_recording_duration_seconds = 0.0
        self._pending_stats_session = False
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
        if self._settings.rules_error:
            self._notify_rules_error(self._settings)

        # In headless tests no GUI preload runs; keep previous behavior.
        if self._test_mode:
            self._status_changed.emit("ready")

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._recording_health.stop()
        if not self._test_mode:
            self._history_window.stop_playback()
            QApplication.processEvents()
        if self._session is not None:
            for job in self._session.jobs:
                job.cancel.set()
        self._hotkey_mgr.unregister_all()
        self._live_stop_requested.set()
        if self._recorder.is_recording:
            try:
                self._recorder.stop(read_audio=False) if self._session is not None else self._recorder.stop()
            except Exception:
                LOGGER.exception("Failed to stop microphone during shutdown")
        if self._session is not None:
            self._closing = True
            for job in self._session.jobs:
                job.cancel.set()
            for thread in self._job_threads:
                thread.join(timeout=10)
            if not any(t.is_alive() for t in self._job_threads):
                try:
                    self._session.close()
                except OSError:
                    LOGGER.exception("Session cleanup deferred until next startup")
        self._transcriber_live.close()
        self._transcriber_final.close()
        self._text_optimizer.close()

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
            self._tray.quit_requested.connect(self._quit)
            self._tray.open_audio_requested.connect(self._open_audio)

            # Connect StatusWindow signals to same handlers as TrayIcon
            self._status_window.toggle_recording_requested.connect(self._toggle_recording)
            self._status_window.open_settings_requested.connect(self._open_settings)
            self._status_window.open_history_requested.connect(self._open_history)
            self._status_window.open_statistics_requested.connect(self._open_statistics)
            self._status_window.quit_requested.connect(self._quit)

            self._history_window.text_selected.connect(self._on_history_text_selected)
            self._history_window.open_audio_requested.connect(self._open_audio)
            self._history_window.recognize_requested.connect(self._recognize_job)
            self._history_window.retry_requested.connect(self._retry_job)
            self._history_window.delete_requested.connect(self._delete_job)

        self._status_changed.connect(self._on_status_changed)
        self._transcription_done.connect(self._on_transcription_done)
        self._transcription_failed.connect(self._on_transcription_failed)
        self._text_optimization_done.connect(self._on_text_optimization_done)
        self._partial_transcription_done.connect(self._on_partial_transcription_done)
        self._model_preload_started.connect(self._on_model_preload_started)
        self._model_preload_finished.connect(self._on_model_preload_finished)
        self._job_finished.connect(self._on_job_finished)
        self._job_progress.connect(self._on_job_progress)

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
        if not self._recorder.is_recording:
            self._recorder = self._build_recorder(settings)
        self._transcriber_live.set_model(settings.live_whisper_model)
        jobs_running = self._session is not None and any(j.running for j in self._session.jobs)
        if not jobs_running:
            self._transcriber_final.set_model(settings.final_whisper_model)
        self._transcriber_live.set_compute_device(settings.compute_device)
        if not jobs_running:
            self._transcriber_final.set_compute_device(settings.compute_device)
        self._transcriber_live.set_keep_model_loaded(settings.keep_model_loaded)
        if not jobs_running:
            self._transcriber_final.set_keep_model_loaded(settings.keep_model_loaded)
            self._text_optimizer.set_compute_device(settings.compute_device)
            if hasattr(self._text_optimizer, "set_model"):
                self._text_optimizer.set_model(settings.text_model)
        LOGGER.info(
            "Settings angewendet | live_enabled=%s live_model=%s final_model=%s text_optimization=%s formatting=%s cleanup=%s redact=%s translation=%s target=%s compute_device=%s keep_model_loaded=%s",
            settings.live_transcription_enabled,
            settings.live_whisper_model,
            settings.final_whisper_model,
            settings.text_optimization_enabled,
            settings.text_optimization_formatting_enabled,
            settings.text_optimization_cleanup_enabled,
            settings.text_optimization_redact_enabled,
            settings.text_translation_enabled,
            settings.text_translation_target_language,
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
        if self._settings.live_transcription_enabled:
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
        if self._session is not None and any(j.running for j in self._session.jobs):
            return
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
                self._save_settings(settings)
            return requested_index

        if requested_name:
            for mic in microphones:
                if mic["name"] == requested_name:
                    settings.microphone_index = mic["index"]
                    self._save_settings(settings)
                    return mic["index"]

        settings.microphone_index = None
        settings.microphone_name = None
        self._save_settings(settings)
        return None

    def _save_settings(self, settings):
        try:
            settings.save()
        except OSError:
            LOGGER.exception("Settings could not be saved")
            if not self._test_mode:
                self._status_window.show_message(tr("save_failed", settings))

    def _open_settings(self) -> None:
        dlg = SettingsWindow(self._settings)
        dlg.settings_saved.connect(self._apply_settings)
        dlg.exec()

    def _notify_rules_error(self, settings):
        error = settings.rules_error
        if not error:
            return
        message = tr(error.key, settings) + "\n" + str(error.path)
        if error.detail:
            message += "\n" + error.detail
        message += "\n" + tr("rules_using_cached" if settings._rules_available else "rules_no_valid", settings)
        LOGGER.warning("Correction rules: %s", message)
        if not self._test_mode:
            self._status_window.show_message(message, duration_ms=10000)

    def _prepare_rules(self, settings):
        if not settings.correction_rules_enabled:
            return True
        available = settings.refresh_rules()
        if settings.rules_error:
            self._notify_rules_error(settings)
        elif settings is not self._settings and settings.correction_rules_path == self._settings.correction_rules_path:
            # Keep the most recently validated file as fallback for later jobs.
            self._settings._data["correction_rules"] = settings.correction_rules
            self._settings._rules_available = True
            self._settings._rules_revision = settings._rules_revision
            self._settings.rules_error = None
        return available

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
        if self._closing:
            return
        if self._session is not None and any(j.running for j in self._session.jobs):
            self._open_history()
            return
        if not self._prepare_rules(self._settings):
            return
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
        if self._session is not None:
            self._recording_job = self._session.create()
            self._recording_settings = self._settings.snapshot()
            self._recorder.set_audio_path(self._recording_job.audio_path)
        try:
            self._recorder.start()
        except Exception as exc:
            if self._recording_job is not None:
                self._recording_job.versions.append(ResultVersion(self._recording_settings.final_whisper_model,
                                                                 self._recording_settings.language, None,
                                                                 status="failed", error=str(exc)))
                self._recording_job = None
            self._on_transcription_failed(str(exc))
            return
        self._status_changed.emit("recording")

    def _check_recording_health(self):
        if self._recording_job is not None and not self._recorder.is_recording:
            self._stop_recording()

    def _stop_recording(self) -> None:
        if self._session is not None:
            self._stop_live_worker()
            job = self._recording_job
            snapshot = self._recording_settings
            if job is None:
                return
            self._recording_job = None
            try:
                self._recorder.stop(read_audio=False)
                job.duration = wav_duration(job.audio_path)
            except Exception as exc:
                version = ResultVersion(snapshot.final_whisper_model, snapshot.language, None, status="failed", error=str(exc))
                job.versions.append(version)
                self._on_transcription_failed(str(exc))
                return
            self._submit_job(job, snapshot, auto_insert=True)
            self._recorder = self._build_recorder(self._settings)
            return
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

    def _transcribe_and_emit(self, audio, language: str) -> None:
        start = time.monotonic()
        LOGGER.info("Finale Transkription gestartet | samples=%s", len(audio))
        try:
            text = self._transcriber_final.transcribe(audio, language=language)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Finale Transkription fehlgeschlagen")
            self._transcription_failed.emit(str(exc))
            return

        elapsed = time.monotonic() - start
        LOGGER.info("Finale Transkription fertig | chars=%s duration=%.2fs", len(text), elapsed)
        self._transcription_done.emit(text)

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
        self._save_settings(self._settings)
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

    @pyqtSlot(str)
    def _on_transcription_done(self, text: str) -> None:
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
        final_text, should_press_enter = extract_enter_command(text)
        if self._settings.correction_rules_enabled:
            final_text = apply_corrections(final_text, self._settings.correction_rules)
        options = self._build_text_optimization_options()
        if (self._settings.text_optimization_enabled or self._settings.text_translation_enabled) and final_text.strip() and options.has_work(self._settings.language):
            self._active_text_optimizations += 1
            self._status_changed.emit("processing")
            threading.Thread(
                target=self._optimize_and_emit,
                args=(
                    final_text,
                    should_press_enter,
                    options,
                    self._settings.language,
                ),
                daemon=True,
            ).start()
            return
        self._finalize_text(final_text, should_press_enter)

    def _optimize_and_emit(
        self,
        text: str,
        should_press_enter: bool,
        options: TextOptimizationOptions,
        language: str,
    ) -> None:
        """Run the local model off the Qt thread and retain a safe fallback."""
        try:
            protected, names = protect_names(text, self._settings.correction_rules if self._settings.correction_rules_enabled else [])
            optimized_text = self._text_optimizer.optimize(
                protected,
                options=options,
                language=language,
            )
            optimized_text = restore_names(optimized_text, names)
            used_fallback = False
            LOGGER.info(
                "Textoptimierung fertig | formatting=%s cleanup=%s redact=%s translation_target=%s input_chars=%s output_chars=%s",
                options.formatting,
                options.cleanup,
                options.redact,
                options.translation_target,
                len(text),
                len(optimized_text),
            )
        except Exception:  # noqa: BLE001 - the raw transcription is the documented fallback
            LOGGER.exception("Textoptimierung fehlgeschlagen; Originaltext wird verwendet")
            optimized_text = text
            used_fallback = True
        self._text_optimization_done.emit(optimized_text, should_press_enter, used_fallback)

    def _build_text_optimization_options(self) -> TextOptimizationOptions:
        """Snapshot independent options before starting the worker thread."""
        target = (
            self._settings.text_translation_target_language
            if self._settings.text_translation_enabled
            else None
        )
        return TextOptimizationOptions(
            formatting=self._settings.text_optimization_enabled and self._settings.text_optimization_formatting_enabled,
            cleanup=self._settings.text_optimization_enabled and self._settings.text_optimization_cleanup_enabled,
            redact=self._settings.text_optimization_enabled and self._settings.text_optimization_redact_enabled,
            translation_target=target,
        )

    @pyqtSlot(str, bool, bool)
    def _on_text_optimization_done(
        self,
        text: str,
        should_press_enter: bool,
        used_fallback: bool,
    ) -> None:
        self._active_text_optimizations = max(0, self._active_text_optimizations - 1)
        if used_fallback and not self._test_mode:
            self._status_window.show_message(tr("text_optimization_failed", self._settings))
        self._finalize_text(text, should_press_enter)

    def _finalize_text(self, final_text: str, should_press_enter: bool) -> None:
        """Apply local enrichments, save the actual result, and insert it."""
        if self._settings.emoji_mode_enabled:
            final_text = enrich_with_emojis(final_text, language=self._settings.language)
        if final_text and final_text.strip():
            self._history.append(final_text)
            # Keep only last 50 items
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
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

        self._status_changed.emit("inserted")
        # Reset to ready after a moment so the user sees the confirmation
        threading.Timer(2.0, lambda: self._status_changed.emit("ready")).start()

    @pyqtSlot(str)
    def _on_transcription_failed(self, message: str) -> None:
        LOGGER.error("Transkription fehlgeschlagen | %s", message)
        self._pending_stats_session = False
        self._recording_started_at = None
        self._last_recording_duration_seconds = 0.0
        if not self._test_mode:
            self._status_window.show_message(tr("transcription_failed", self._settings))
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
            self._history_window.set_jobs(self._session.jobs)
            self._history_window.show()

    def _open_audio(self) -> None:
        if self._recorder.is_recording or self._closing:
            return
        path, _ = QFileDialog.getOpenFileName(None, tr("audio_open", self._settings), "", "Audio (*.wav *.mp3 *.m4a *.flac)")
        if not path:
            return
        from gui.audio_dialog import AudioOptionsDialog
        dialog = AudioOptionsDialog(self._settings)
        if not dialog.exec():
            return
        job = self._session.create(source="file")
        self._submit_job(job, dialog.snapshot(), source_path=Path(path))
        self._open_history()

    def _recognize_job(self, job) -> None:
        if job.running or self._recorder.is_recording:
            return
        from gui.audio_dialog import AudioOptionsDialog
        dialog = AudioOptionsDialog(self._settings)
        if dialog.exec():
            self._submit_job(job, dialog.snapshot())
            self._open_history()

    def _retry_job(self, job) -> None:
        if job.running or not job.versions or self._recorder.is_recording:
            return
        version = job.versions[-1]
        settings = version.settings_snapshot or self._settings.snapshot()
        self._submit_job(job, settings, retry=version)

    def _delete_job(self, job) -> None:
        try:
            self._session.delete(job)
            self._history_window.set_jobs(self._session.jobs)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(None, tr("error", self._settings), str(exc))

    def _submit_job(self, job, settings, *, auto_insert=False, source_path=None, retry=None):
        if self._closing or job.running:
            return
        if source_path is not None:
            job.original_path = source_path
        if source_path is None and not job.audio_path.exists():
            source_path = job.original_path
        # Microphone settings were frozen when recording began. A retry keeps
        # its original snapshot; imports and new recognitions refresh once.
        refresh_needed = not auto_insert and (retry is None or retry.settings_snapshot is None)
        if refresh_needed and not self._prepare_rules(settings):
            if retry is None:
                job.versions.append(ResultVersion(settings.final_whisper_model, settings.language or None,
                    settings.text_translation_target_language if settings.text_translation_enabled else None,
                    status="failed", error=str(settings.rules_error)))
            else:
                retry.status, retry.error = "failed", str(settings.rules_error)
            return
        snapshot = settings.snapshot()
        version = retry or ResultVersion(snapshot.final_whisper_model, snapshot.language or None,
                                        snapshot.text_translation_target_language if snapshot.text_translation_enabled else None,
                                        text_model=snapshot.text_model)
        version.settings_snapshot = snapshot
        if retry is None and snapshot.correction_rules_enabled and snapshot.rules_error:
            version.warnings.append(str(snapshot.rules_error) + "\n" + tr("rules_using_cached", snapshot))
        if auto_insert:
            version.warnings.extend(getattr(self._recorder, "capture_warnings", []))
        if retry is None:
            job.versions.append(version)
        version.status, version.error = "processing", ""
        job.phase = ""
        job.cancel.clear()
        job.running = True
        self._status_changed.emit("processing")

        def worker():
            enter = False
            with self._job_lock:
                try:
                    if job.cancel.is_set():
                        version.status = "cancelled"
                        return
                    if source_path:
                        convert_audio(source_path, job.audio_path, job.cancel)
                    self._transcriber_final.set_model(version.model)
                    self._transcriber_final.set_compute_device(snapshot.compute_device)
                    self._transcriber_final.set_keep_model_loaded(snapshot.keep_model_loaded)
                    if snapshot.text_optimization_enabled or snapshot.text_translation_enabled:
                        self._text_optimizer.set_compute_device(snapshot.compute_device)
                        self._text_optimizer.set_model(snapshot.text_model)
                    enter = run_job(job, version, snapshot, self._transcriber_final, self._text_optimizer,
                                    lambda value: self._job_progress.emit(job))
                except Exception as exc:
                    LOGGER.exception("Job %s failed before processing completed", job.id)
                    version.status = "cancelled" if job.cancel.is_set() else "failed"
                    version.error = str(exc)
                finally:
                    job.running = False
                    self._job_finished.emit(job, version, snapshot, auto_insert, enter)
        thread = threading.Thread(target=worker, name=f"audio-{job.id[:8]}", daemon=True)
        self._job_threads = [t for t in self._job_threads if t.is_alive()]
        self._job_threads.append(thread)
        thread.start()

    def _on_job_progress(self, job):
        if not self._test_mode and job.running:
            self._status_window.set_loading(True, job.phase or tr("processing", self._settings))
        if not self._test_mode and self._history_window.isVisible():
            self._history_window.refresh_job(job)

    def _on_job_finished(self, job, version, snapshot, auto_insert, enter):
        if self._closing:
            return
        if version.status in {"complete", "optimization_failed"}:
            text = version.text
            if snapshot.emoji_mode_enabled:
                text = enrich_with_emojis(text, language=version.language)
            version.text = text
            self._history.append(text)
            self._history = self._history[-self._max_history:]
            if auto_insert and snapshot.auto_insert:
                if snapshot.live_transcription_enabled:
                    self._queue_replace(self._rendered_live_text, text)
                    self._rendered_live_text = ""
                else:
                    self._queue_insert(text)
                if enter:
                    self._queue_enter()
            if auto_insert:
                self._statistics.record_session(started_at=job.created, duration_seconds=job.duration, language=version.language or snapshot.language)
            if version.status == "optimization_failed" and not self._test_mode:
                self._status_window.show_message(tr("optimization_failed", snapshot))
        elif not self._test_mode:
            self._status_window.show_message(tr("translation_failed" if version.status == "translation_failed" else "transcription_failed", snapshot))
            self._open_history()
        self._recording_started_at = None
        self._pending_stats_session = False
        self._status_changed.emit("processing" if any(j.running for j in self._session.jobs) else "ready")
        if not self._test_mode:
            self._history_window.refresh_job(job)

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
            and (self._session is None or not any(j.running for j in self._session.jobs))
            and self._active_preloads == 0
            and self._active_text_optimizations == 0
            and self._insert_queue.unfinished_tasks == 0
            and self._status in ("ready", "inserted", "")
        )
