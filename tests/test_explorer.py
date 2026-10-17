import pytest
from utils.explorer import reveal_file


def test_reveal_selects_file_and_opens_existing_parent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("utils.explorer.subprocess.Popen", lambda args: calls.append(args))
    path = tmp_path / 'names & spaces.json'
    path.write_text("{}")
    reveal_file(path)
    assert calls[-1] == ["explorer.exe", "/select,", str(path)]
    missing = tmp_path / "missing.json"
    reveal_file(missing)
    assert calls[-1] == ["explorer.exe", str(tmp_path)]
    assert not missing.exists()


def test_reveal_does_not_create_missing_parent(tmp_path):
    path = tmp_path / "absent/rules.json"
    with pytest.raises(FileNotFoundError):
        reveal_file(path)
    assert not path.parent.exists()
