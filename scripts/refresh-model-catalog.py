"""Maintainer tool: pin upstream revisions and LFS SHA-256 metadata.

Review and test the resulting catalogue before attaching it to a GitHub release.
This never runs in the application or as an automatic build step.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.downloads import open_https

SOURCES = [
    ("ggerganov/whisper.cpp", "speech", [(m, f"ggml-{m}.bin") for m in
     ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo", "large-v3-turbo-q5_0"]]),
    ("ggml-org/whisper-vad", "vad", [("silero-v6.2.0", "ggml-silero-v6.2.0.bin")]),
    ("unsloth/Qwen3-4B-Instruct-2507-GGUF", "text", [("qwen3-4b-instruct-2507", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")]),
    ("unsloth/Qwen3.5-4B-GGUF", "text", [("qwen3.5-4b", "Qwen3.5-4B-Q4_K_M.gguf")]),
]


if __name__ == "__main__":
    models = []
    for repo, kind, selections in SOURCES:
        with open_https(f"https://huggingface.co/api/models/{repo}?blobs=true", timeout=30) as response:
            info = json.load(response)
        files = {f["rfilename"]: f for f in info["siblings"]}
        for model_id, filename in selections:
            f = files[filename]
            models.append(dict(id=model_id, name=model_id, kind=kind, repo=repo, revision=info["sha"],
                               filename=filename, sha256=f["lfs"]["sha256"], size=f["size"],
                               minimum_app_version="1.2.0", runtime="llama.cpp v0.6.0" if kind == "text" else "whisper.cpp 1.9.4"))
    path = Path(__file__).resolve().parents[1] / "assets/model-catalog.json"
    path.write_text(json.dumps({"schema_version": 1, "catalog_version": "2026-10-10", "models": models}, indent=2) + "\n", encoding="utf-8")
