"""Opt-in real-runtime smoke check; never downloads a multi-GB speech model.

Requires a previously downloaded small Whisper model and built runtimes.
Writes only to build/inference-check, and releases all model processes.
"""
from pathlib import Path
import os
import sys
import hashlib
import argparse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from core.audio import convert_audio
from core.models import ModelManager
from core.transcriber import Transcriber
from core.text_optimizer import TextOptimizer, TextOptimizationOptions
from core.corrections import protect_names, restore_names
import wave

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--text-model", default="bundled-qwen3-4b", choices=["bundled-qwen3-4b", "qwen3-4b-instruct-2507", "qwen3.5-4b"])
parser.add_argument("--text-only", action="store_true")
parser.add_argument("--compute-device", default="auto", choices=["auto", "cpu"])
parser.add_argument("--speech-model", default="small", choices=["small", "large-v3", "large-v3-turbo-q5_0"])
args = parser.parse_args()
directory = root / "build/inference-check"
directory.mkdir(parents=True, exist_ok=True)
speech_spec = ModelManager(directory).catalog[args.speech_model]
model = Path(os.environ["LOCALAPPDATA"]) / "WinWhisperPlus/models" / speech_spec.filename
if not model.exists() and not args.text_only:
    model = ModelManager(directory / "models").ensure(args.speech_model)
if args.text_only:
    model = Path(os.environ["LOCALAPPDATA"]) / "WinWhisperPlus/models/ggml-small.bin"
    speech_spec = ModelManager(directory).catalog["small"]
expected = speech_spec.sha256
digest = hashlib.sha256()
with model.open("rb") as stream:
    for data in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(data)
assert digest.hexdigest() == expected
convert_audio(root / "build/validate-whisper-src/samples/jfk.wav", directory / "sample.wav")
with wave.open(str(directory / "sample.wav"), "rb") as wav:
    samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768
for resident in (() if args.text_only else (False, True)):
    transcriber = Transcriber(args.speech_model, model_dir=directory / "models", keep_model_loaded=resident, compute_device=args.compute_device)
    transcriber._model_path = model
    try:
        segments, language = transcriber.transcribe_segments(samples, "en")
        text = "".join(s.text for s in segments).strip()
        assert "country" in text.casefold() and "you" in text.casefold()
        assert all(0 <= s.start <= s.end <= len(samples) / 16000 + 1 for s in segments)
        print("Whisper", "server" if resident else "CLI", language, text)
    finally:
        transcriber.close()
text_path = None
if args.text_model != "bundled-qwen3-4b":
    last_percent = [-10]
    def download_progress(current, total):
        percent = int(current / total * 100)
        if percent >= last_percent[0] + 10:
            print(args.text_model, "download", percent, "%", flush=True)
            last_percent[0] = percent
    text_path = ModelManager(directory / "models").ensure(args.text_model, progress=download_progress)
optimizer = TextOptimizer(model_path=text_path, model_id=args.text_model, compute_device=args.compute_device, request_timeout_seconds=120)
try:
    protected, names = protect_names("Wir verwenden orgAnice für unsere Kundenverwaltung.", [{"target": "orgAnice"}])
    translated = restore_names(optimizer.optimize(protected, options=TextOptimizationOptions(formatting=False, translation_target="en"), language="de"), names)
    assert "orgAnice" in translated and "customer" in translated.casefold()
    print(args.text_model, "translation:", translated)
finally:
    optimizer.close()
