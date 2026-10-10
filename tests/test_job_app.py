import pytest
from PyQt6.QtWidgets import QApplication
from app import Application
from core.session import SessionStore
from tests.fakes import FakeRecorder, FakeTranscriber, FakeTextOptimizer, FakeTextSink


@pytest.fixture
def job_app(tmp_path):
    qapp = QApplication.instance() or QApplication([])
    sink = FakeTextSink()
    app = Application(qapp, test_mode=True, recorder=FakeRecorder(), transcriber_live=FakeTranscriber(),
                      transcriber_final=FakeTranscriber("Organize enter"), text_optimizer=FakeTextOptimizer(), text_sink=sink)
    app._session = SessionStore(tmp_path / "sessions")
    app._settings.correction_rules = [{"source": "Organize", "target": "orgAnice"}]
    app.start()
    yield app, sink
    app.shutdown()


def test_recording_uses_settings_snapshot_and_retains_audio(job_app):
    app, sink = job_app
    app._start_recording()
    app._settings.correction_rules = []
    app._stop_recording()
    assert app.wait_for_idle()
    job = app._session.jobs[0]
    assert job.audio_path.exists()
    assert job.versions[0].raw_text == "Organize enter"
    assert job.versions[0].text == "orgAnice"
    assert sink.inserts == ["orgAnice"]
    assert sink.enters == 1


def test_re_recognition_adds_version_without_automatic_insertion(job_app):
    app, sink = job_app
    app._start_recording()
    app._stop_recording()
    assert app.wait_for_idle()
    job = app._session.jobs[0]
    app._settings.correction_rules = []
    app._submit_job(job, app._settings)
    assert app.wait_for_idle()
    assert len(job.versions) == 2
    assert job.versions[0].text == "orgAnice"
    assert job.versions[1].text == "Organize"
    assert sink.inserts == ["orgAnice"]


def test_failed_translation_does_not_insert_source_as_translation(job_app):
    app, sink = job_app
    app._settings.text_translation_enabled = True
    app._text_optimizer.raise_exc = RuntimeError("broken translation")
    app._start_recording()
    app._stop_recording()
    assert app.wait_for_idle()
    version = app._session.jobs[0].versions[0]
    assert version.status == "translation_failed"
    assert version.raw_text == "Organize enter"
    assert version.text == ""
    assert sink.inserts == []


def test_unused_selected_text_model_does_not_download_or_block_dictation(job_app, monkeypatch):
    app, sink = job_app
    app._settings.text_model = "qwen3.5-4b"
    app._settings.text_optimization_enabled = False
    app._settings.text_translation_enabled = False
    def forbidden(*_a, **_k):
        raise AssertionError("Unused text model must not be downloaded")
    monkeypatch.setattr("core.models.ModelManager.ensure", forbidden)
    app._text_optimizer.set_model = forbidden
    app._start_recording()
    app._stop_recording()
    assert app.wait_for_idle()
    assert app._session.jobs[0].versions[0].status == "complete"
    assert sink.inserts == ["orgAnice"]
