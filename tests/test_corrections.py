import pytest
from core.corrections import apply_corrections, protect_names, restore_names, validate_rules
from config.settings import Settings


def test_whole_words_longest_single_pass():
    rules = validate_rules([{"source": "Organize", "target": "orgAnice"},
                            {"source": "Organize CRM", "target": "orgAniceCRM"},
                            {"source": "orgAnice", "target": "other"}])
    assert apply_corrections("ORGANIZE, organize CRM; reorganize!", rules) == "orgAnice, orgAniceCRM; reorganize!"


def test_protection_detects_missing_and_duplicate_names():
    protected, mapping = protect_names("orgAnice and orgAnice.", [{"target": "orgAnice"}])
    assert restore_names(protected, mapping) == "orgAnice and orgAnice."
    with pytest.raises(ValueError):
        restore_names("lost", mapping)
    with pytest.raises(ValueError):
        restore_names(protected + protected, mapping)


def test_rules_persist_and_defaults_are_independent():
    settings = Settings()
    settings.correction_rules = [{"source": "Organize", "target": "orgAnice"}]
    settings.save_rules()
    settings.save()
    assert Settings().correction_rules == settings.correction_rules
    snapshot = settings.snapshot()
    snapshot.correction_rules = []
    assert settings.correction_rules


@pytest.mark.parametrize("rules", [[{"source": "", "target": "x"}],
                                  [{"source": "a", "target": "x"}, {"source": "A", "target": "y"}]])
def test_invalid_rules_rejected(rules):
    with pytest.raises(ValueError):
        validate_rules(rules)
