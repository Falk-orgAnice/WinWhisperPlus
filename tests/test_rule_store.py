import json
from pathlib import Path
import pytest

from config.settings import Settings
from core.rule_store import RuleStore, RulesFileError, RulesConflict

RULES = [{"enabled": True, "source": "Organize", "target": "orgAnice"}]


def legacy_file(tmp_path, rules=RULES, **extra):
    path = tmp_path / "WinWhisperPlus/settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"correction_rules": rules, **extra}), encoding="utf-8")
    return path


def test_migrates_once_and_does_not_overwrite_external_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    old = legacy_file(tmp_path)
    settings = Settings()
    assert RuleStore(settings.correction_rules_path).load()[0] == RULES
    assert "correction_rules" not in json.loads(old.read_text())
    updated = [{"enabled": False, "source": "Ärger", "target": "Größe"}]
    RuleStore(settings.correction_rules_path).save(updated)
    settings.window_position_x = 13
    settings.save()
    assert Settings().correction_rules == updated
    assert "Größe" in settings.correction_rules_path.read_text(encoding="utf-8")


def test_existing_rule_file_wins_over_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    legacy_file(tmp_path)
    path = tmp_path / "WinWhisperPlus/correction-rules.json"
    RuleStore(path).save([])
    assert Settings().correction_rules == []


def test_failed_migration_retains_legacy_and_last_good_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    old = legacy_file(tmp_path)
    def fail(*_a, **_k):
        raise RulesFileError(old, "rules_write_failed")
    monkeypatch.setattr(RuleStore, "save", fail)
    settings = Settings()
    assert settings.rules_error and settings.correction_rules == RULES
    settings.save()
    assert json.loads(old.read_text())["correction_rules"] == RULES


def test_invalid_legacy_rules_are_not_silently_discarded(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    old = legacy_file(tmp_path, rules=[{"source": 42, "target": "name"}])
    settings = Settings()
    assert settings.rules_error and not settings._rules_available
    assert not settings.correction_rules_path.exists()
    assert json.loads(old.read_text())["correction_rules"][0]["source"] == 42


def test_paths_independent_of_working_directory_and_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "profile"))
    settings = Settings()
    settings.correction_rules_path = "shared/names.json"
    settings.correction_rules = RULES
    settings.save_rules()
    settings.save()
    other = tmp_path / "different-install"
    other.mkdir()
    monkeypatch.chdir(other)
    again = Settings()
    assert again.correction_rules_path == tmp_path / "profile/WinWhisperPlus/shared/names.json"
    assert again.correction_rules == RULES


def test_corruption_keeps_last_good_and_missing_file_blocks_fresh_instance():
    settings = Settings()
    settings.correction_rules = RULES
    settings.save_rules()
    settings.save()
    settings.correction_rules_path.write_text("{ broken", encoding="utf-8")
    assert settings.refresh_rules() and settings.correction_rules == RULES
    assert settings.rules_error.key == "rules_invalid_json"
    assert "1:" in settings.rules_error.detail
    fresh = Settings()
    assert not fresh._rules_available and fresh.rules_error
    fresh.save()  # must not turn a failed load into an embedded empty backup
    settings.correction_rules_path.unlink()
    assert not Settings()._rules_available
    assert not settings.correction_rules_path.exists()


@pytest.mark.parametrize("document,key", [
    ({"schema_version": 2, "rules": []}, "rules_invalid_version"),
    ({"schema_version": True, "rules": []}, "rules_invalid_version"),
    ({"schema_version": 1, "rules": {}}, "rules_invalid_format"),
    ({"schema_version": 1, "rules": [{"source": "x", "target": "y", "enabled": "false"}]}, "rules_invalid_fields"),
    ({"schema_version": 1, "rules": [{"source": 12, "target": "y"}]}, "rules_invalid_fields"),
    ({"schema_version": 1, "rules": [{"source": " ", "target": "x"}]}, "correction_empty"),
    ({"schema_version": 1, "rules": RULES + [dict(RULES[0], source="ORGANIZE")]}, "correction_duplicate"),
])
def test_strict_file_validation(tmp_path, document, key):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RulesFileError) as caught:
        RuleStore(path).load()
    assert caught.value.key == key and caught.value.path == path


def test_atomic_write_and_conflict_preserve_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "rules.json"
    store = RuleStore(path)
    _, baseline = store.save(RULES)
    store.save([])
    previous = path.read_bytes()
    with pytest.raises(RulesConflict):
        store.save(RULES, expected_revision=baseline)
    assert path.read_bytes() == previous
    def failure(*_a):
        raise OSError("disk full")
    monkeypatch.setattr("core.rule_store.os.replace", failure)
    with pytest.raises(RulesFileError, match="disk full"):
        store.save(RULES)
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob("rules-*.tmp"))
