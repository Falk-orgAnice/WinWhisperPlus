"""Revision-pinned model catalogue and verified, cancellable installations."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request
import urllib.error

from utils.resources import resource_path, app_version

CATALOG_URL = "https://github.com/Falk-orgAnice/WinWhisperPlus/releases/latest/download/model-catalog.json"


class Cancelled(RuntimeError):
    pass


class CatalogNotPublished(RuntimeError):
    """The release channel has no model catalogue attachment yet."""
    pass


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    kind: str
    repo: str
    revision: str
    filename: str
    sha256: str
    size: int
    minimum_app_version: str = "1.2.0"
    runtime: str = "whisper.cpp 1.9.4"

    @property
    def url(self):
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.filename}"

    @property
    def compatible(self):
        def version(value):
            return tuple(int(x) for x in value.split("."))
        try:
            return version(app_version()) >= version(self.minimum_app_version)
        except ValueError:
            return False


def parse_catalog(data: dict) -> dict[str, ModelSpec]:
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("models"), list):
        raise ValueError("Unsupported model catalogue")
    result = {}
    for item in data["models"]:
        model = ModelSpec(**item)
        if (not re.fullmatch(r"[a-zA-Z0-9._-]+", model.id)
            or model.kind not in {"speech", "text", "vad"}
            or not re.fullmatch(r"[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+", model.repo)
            or not re.fullmatch(r"[0-9a-f]{40}", model.revision)
            or not re.fullmatch(r"[0-9a-f]{64}", model.sha256)
            or Path(model.filename).name != model.filename or "/" in model.filename or "\\" in model.filename
            or model.size <= 0 or model.id in result
            or not re.fullmatch(r"\d+\.\d+\.\d+", model.minimum_app_version)):
            raise ValueError("Invalid model catalogue entry")
        result[model.id] = model
    return result


class ModelManager:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WinWhisperPlus" / "models"
        self.catalog = parse_catalog(json.loads(Path(resource_path("assets/model-catalog.json")).read_text(encoding="utf-8")))
        self._bundled_catalog = dict(self.catalog)
        cached = self.directory / "catalog.json"
        if cached.is_file():
            try:
                self.catalog.update(parse_catalog(json.loads(cached.read_text(encoding="utf-8"))))
            except (ValueError, TypeError, OSError):
                pass
        self._verified: dict[str, tuple] = {}

    def path(self, model: ModelSpec):
        return self.directory / model.filename

    def installed(self, model: ModelSpec) -> bool:
        path = self.path(model)
        receipt = path.with_suffix(path.suffix + ".receipt.json")
        try:
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            return path.stat().st_size == model.size and saved["sha256"] == model.sha256
        except (OSError, ValueError, KeyError):
            return False

    def installed_spec(self, model_id):
        """Find the activated revision independently of catalogue updates."""
        current = self.catalog[model_id]
        if self.installed(current):
            return current
        for receipt in self.directory.glob("*.receipt.json"):
            try:
                saved = json.loads(receipt.read_text(encoding="utf-8"))
                if "model" in saved:
                    spec = next(iter(parse_catalog({"schema_version": 1, "models": [saved["model"]]}).values()))
                else:
                    spec = self._bundled_catalog[model_id]  # older receipts
                if (spec.id == model_id and spec.kind == self.catalog[model_id].kind
                    and saved["sha256"] == spec.sha256 and self.installed(spec)):
                    return spec
            except (OSError, ValueError, KeyError, TypeError, StopIteration):
                continue
        return None

    def verify(self, model: ModelSpec, cancel=None, progress=None) -> bool:
        path = self.path(model)
        if not path.is_file() or path.stat().st_size != model.size:
            return False
        stat = path.stat()
        key = (stat.st_size, stat.st_mtime_ns, model.sha256)
        if self._verified.get(model.id) == key:
            return True
        digest, read = hashlib.sha256(), 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if cancel and cancel.is_set():
                    raise Cancelled("Cancelled")
                digest.update(chunk)
                read += len(chunk)
                if progress:
                    progress(read, model.size)
        if digest.hexdigest() != model.sha256:
            return False
        self._verified[model.id] = key
        self._write_receipt(model)
        return True

    def _write_receipt(self, model):
        path = self.path(model).with_suffix(self.path(model).suffix + ".receipt.json")
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="receipt-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"sha256": model.sha256, "revision": model.revision, "model": asdict(model)}, stream)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def ensure(self, model_id, cancel=None, progress=None, *, allow_incompatible=False, prefer_installed=True) -> Path:
        model = self.catalog[model_id]
        if prefer_installed:
            installed = self.installed_spec(model_id)
            if installed and installed.sha256 != model.sha256 and installed.compatible:
                if self.verify(installed, cancel, progress):
                    return self.path(installed)
        if not allow_incompatible and not model.compatible:
            raise RuntimeError(f"Requires WinWhisperPlus {model.minimum_app_version} / {model.runtime}")
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.verify(model, cancel, progress):
            return self.path(model)
        if cancel and cancel.is_set():
            raise Cancelled("Cancelled")
        # Unique staging files allow independent jobs to use the same model safely.
        import uuid
        temporary = self.directory / f"{model.filename}.{uuid.uuid4().hex}.part"
        digest, written = hashlib.sha256(), 0
        try:
            with urllib.request.urlopen(model.url, timeout=30) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    if cancel and cancel.is_set():
                        raise Cancelled("Cancelled")
                    output.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if written > model.size:
                        raise ValueError("Model exceeds declared size")
                    if progress:
                        progress(written, model.size)
            if cancel and cancel.is_set():
                raise Cancelled("Cancelled")
            if written != model.size or digest.hexdigest() != model.sha256:
                raise ValueError("Model checksum mismatch")
            os.replace(temporary, self.path(model))
            self._write_receipt(model)
            return self.path(model)
        finally:
            temporary.unlink(missing_ok=True)

    def refresh(self):
        try:
            with urllib.request.urlopen(CATALOG_URL, timeout=30) as response:
                data = response.read(1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise CatalogNotPublished("No model catalogue has been published for this release channel") from exc
            raise
        if len(data) > 1024 * 1024:
            raise ValueError("Model catalogue is too large")
        catalog = parse_catalog(json.loads(data))
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "catalog.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        self.catalog.update(catalog)
