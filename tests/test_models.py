import hashlib
import io
import json
import threading
from dataclasses import replace
import pytest
from core.models import ModelManager, Cancelled, parse_catalog


def fake_manager(tmp_path):
    manager = ModelManager(tmp_path)
    model = replace(manager.catalog["tiny"], size=5, sha256=hashlib.sha256(b"model").hexdigest())
    manager.catalog = {"tiny": model}
    return manager, model


def test_download_verifies_and_records_revision(tmp_path, monkeypatch):
    manager, model = fake_manager(tmp_path)
    monkeypatch.setattr("core.models.open_https", lambda *_a, **_k: io.BytesIO(b"model"))
    path = manager.ensure("tiny")
    assert path.read_bytes() == b"model"
    assert manager.installed(model)
    assert model.revision in json.loads(path.with_suffix(".bin.receipt.json").read_text())["revision"]


def test_bad_download_preserves_previous_model(tmp_path, monkeypatch):
    manager, model = fake_manager(tmp_path)
    manager.path(model).write_bytes(b"prior")
    monkeypatch.setattr("core.models.open_https", lambda *_a, **_k: io.BytesIO(b"wrong"))
    with pytest.raises(ValueError, match="checksum"):
        manager.ensure("tiny")
    assert manager.path(model).read_bytes() == b"prior"
    assert not list(tmp_path.glob("*.part"))


def test_certificate_error_preserves_existing_model_and_catalog(tmp_path, monkeypatch):
    from utils.downloads import DownloadCertificateError
    manager, model = fake_manager(tmp_path)
    manager.path(model).write_bytes(b"prior")
    (tmp_path / "catalog.json").write_text("existing catalogue", encoding="utf8")
    def invalid_certificate(*_a, **_k):
        raise DownloadCertificateError("huggingface.co")
    monkeypatch.setattr("core.models.open_https", invalid_certificate)
    with pytest.raises(DownloadCertificateError):
        manager.ensure("tiny")
    with pytest.raises(DownloadCertificateError):
        manager.refresh()
    assert manager.path(model).read_bytes() == b"prior"
    assert (tmp_path / "catalog.json").read_text(encoding="utf8") == "existing catalogue"
    assert not list(tmp_path.glob("*.part"))


def test_cancelled_download_is_not_activated(tmp_path, monkeypatch):
    manager, model = fake_manager(tmp_path)
    cancel = threading.Event()
    monkeypatch.setattr("core.models.open_https", lambda *_a, **_k: io.BytesIO(b"model"))
    with pytest.raises(Cancelled):
        manager.ensure("tiny", cancel, lambda *_: cancel.set())
    assert not manager.path(model).exists()
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("filename", ["ggml-tiny.bin", "updated-tiny.bin"])
def test_catalog_update_preserves_offline_activated_revision(tmp_path, monkeypatch, filename):
    manager, original = fake_manager(tmp_path)
    monkeypatch.setattr("core.models.open_https", lambda *_a, **_k: io.BytesIO(b"model"))
    old_path = manager.ensure("tiny")
    update = replace(original, filename=filename, revision="a" * 40,
                     sha256=hashlib.sha256(b"newer").hexdigest())
    manager.catalog["tiny"] = update
    def offline(*_a, **_k):
        raise OSError("offline")
    monkeypatch.setattr("core.models.open_https", offline)
    assert manager.ensure("tiny") == old_path
    with pytest.raises(OSError, match="offline"):
        manager.ensure("tiny", prefer_installed=False)
    assert manager.ensure("tiny") == old_path
    assert old_path.read_bytes() == b"model"
    monkeypatch.setattr("core.models.open_https", lambda *_a, **_k: io.BytesIO(b"newer"))
    new_path = manager.ensure("tiny", prefer_installed=False)
    assert manager.installed_spec("tiny") == update
    assert manager.ensure("tiny") == new_path
    assert new_path.read_bytes() == b"newer"


def test_catalog_rejects_paths_and_unknown_schema(tmp_path):
    manager, model = fake_manager(tmp_path)
    from dataclasses import asdict
    data = {"schema_version": 1, "models": [asdict(replace(model, filename="../model.bin"))]}
    with pytest.raises(ValueError):
        parse_catalog(data)
    with pytest.raises(ValueError):
        parse_catalog({"schema_version": 2, "models": []})


def test_text_optimizer_uses_verified_activated_revision_after_catalog_update(tmp_path, monkeypatch):
    from core.text_optimizer import TextOptimizer
    manager, speech = fake_manager(tmp_path)
    original = replace(speech, id="test-text", kind="text", filename="original.gguf")
    manager.catalog = {original.id: original}
    manager.path(original).write_bytes(b"model")
    assert manager.verify(original)
    manager.catalog[original.id] = replace(original, revision="b" * 40, filename="updated.gguf",
                                          sha256=hashlib.sha256(b"newer").hexdigest())
    monkeypatch.setattr("core.text_optimizer.ModelManager", lambda *_a: manager)
    optimizer = TextOptimizer(model_id=original.id)
    assert optimizer._model_path == manager.path(original)
    optimizer._verify_model_hash()
    assert optimizer._hash_verified


def test_unpublished_catalog_has_specific_error_and_preserves_local_catalog(tmp_path, monkeypatch):
    from urllib.error import HTTPError
    from core.models import CatalogNotPublished
    manager, model = fake_manager(tmp_path)
    def unavailable(*_a, **_k):
        raise HTTPError("url", 404, "Not Found", {}, None)
    monkeypatch.setattr("core.models.open_https", unavailable)
    with pytest.raises(CatalogNotPublished):
        manager.refresh()
    assert manager.catalog == {"tiny": model}
    assert not (tmp_path / "catalog.json").exists()
