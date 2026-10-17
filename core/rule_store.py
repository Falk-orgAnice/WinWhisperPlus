"""Human-editable correction files, strict validation and conflict detection."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from core.corrections import validate_rules

ANY_REVISION = object()


class RulesFileError(ValueError):
    def __init__(self, path, key, detail=""):
        self.path, self.key, self.detail = Path(path), key, str(detail)
        super().__init__(f"{self.path}: {key}" + (f" ({detail})" if detail else ""))


class RulesConflict(RulesFileError):
    def __init__(self, path):
        super().__init__(path, "rules_conflict")


def validate_file_rules(rules, path):
    if not isinstance(rules, list):
        raise RulesFileError(path, "rules_invalid_format")
    seen = set()
    for index, rule in enumerate(rules, 1):
        if (not isinstance(rule, dict) or not isinstance(rule.get("source"), str)
                or not isinstance(rule.get("target"), str)
                or type(rule.get("enabled", True)) is not bool):
            raise RulesFileError(path, "rules_invalid_fields", str(index))
        source = rule["source"].strip().casefold()
        if not source or source in seen:
            raise RulesFileError(path, "correction_empty" if not source else "correction_duplicate", str(index))
        seen.add(source)
    return validate_rules(rules)


class RuleStore:
    def __init__(self, path):
        self.path = Path(path)

    def revision(self):
        try:
            return hashlib.sha256(self.path.read_bytes()).hexdigest()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise RulesFileError(self.path, "rules_read_failed", exc) from exc

    def load(self):
        try:
            data = self.path.read_bytes()
            document = json.loads(data.decode("utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise RulesFileError(self.path, "rules_invalid_json", f"{exc.lineno}:{exc.colno} — {exc.msg}") from exc
        except UnicodeError as exc:
            raise RulesFileError(self.path, "rules_invalid_format", exc) from exc
        except OSError as exc:
            raise RulesFileError(self.path, "rules_read_failed", exc) from exc
        if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 1:
            raise RulesFileError(self.path, "rules_invalid_version")
        return validate_file_rules(document.get("rules"), self.path), hashlib.sha256(data).hexdigest()

    def save(self, rules, *, expected_revision=ANY_REVISION):
        rules = validate_file_rules(rules, self.path)
        data = (json.dumps({"schema_version": 1, "rules": rules}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix="rules-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if expected_revision is not ANY_REVISION and self.revision() != expected_revision:
                raise RulesConflict(self.path)
            os.replace(temporary, self.path)
            return rules, hashlib.sha256(data).hexdigest()
        except OSError as exc:
            raise RulesFileError(self.path, "rules_write_failed", exc) from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
