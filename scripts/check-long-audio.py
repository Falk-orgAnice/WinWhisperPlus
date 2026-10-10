"""Real speech across chunk boundaries; repeated speech must remain repeated."""
from pathlib import Path
import os
import sys
import wave
import json
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from config.settings import Settings
from core.audio import RATE
from core.pipeline import run_job
from core.session import AudioJob, ResultVersion
from core.transcriber import Transcriber
from core.text_optimizer import TextOptimizer

root = Path(__file__).resolve().parents[1]
directory = root / "build/inference-check"
os.environ["APPDATA"] = str(directory / "profile")
os.environ["LOCALAPPDATA"] = str(directory / "profile")
with wave.open(str(directory / "sample.wav"), "rb") as source:
    speech = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
audio = np.zeros(RATE * 70, dtype="<i2")
for position in (0, 23, 54):
    audio[position * RATE:position * RATE + len(speech)] = speech
path = directory / "long-speech.wav"
with wave.open(str(path), "wb") as output:
    output.setparams((1, 2, RATE, 0, "NONE", ""))
    output.writeframes(audio.tobytes())
settings = Settings()
settings.final_whisper_model = "large-v3-turbo-q5_0"
transcriber = Transcriber(settings.final_whisper_model, model_dir=directory / "models", keep_model_loaded=True)
transcriber._model_path = directory / "models/ggml-large-v3-turbo-q5_0.bin"
optimizer = TextOptimizer()
job = AudioJob(path, source="file")
version = ResultVersion(settings.final_whisper_model, "en", None)
try:
    run_job(job, version, settings, transcriber, optimizer)
    print(version.status, len(version.sections), "sections", version.raw_text)
    (directory / "long-sections.json").write_text(json.dumps({str(i): [{"start": s.start, "end": s.end, "text": s.text} for s in section["segments"]] for i, section in version.sections.items()}, indent=2))
    assert version.status == "complete", version.error
    assert version.raw_text.casefold().count("country") == 6, "Lost or duplicated real repetition"
    assert version.raw_text.casefold().rstrip(".! ").endswith("country"), "Missing final sentence"
finally:
    transcriber.close()
    optimizer.close()
