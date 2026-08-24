import numpy as np

from core.failed_transcriptions import FailedTranscriptionStore


def test_failed_recording_round_trips_and_can_be_deleted(tmp_path):
    store = FailedTranscriptionStore(tmp_path)
    audio = np.array([-0.5, 0.0, 0.5], dtype=np.float32)

    recording = store.save(audio, "de")

    assert recording.audio_path.is_file()
    assert store.latest() == recording
    assert np.allclose(store.load_audio(recording), audio, atol=1 / 32_000)

    store.delete(recording)

    assert store.latest() is None
