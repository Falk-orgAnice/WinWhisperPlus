"""Literal, single-pass word corrections and lossless name protection."""
from __future__ import annotations

import re
import uuid


def validate_rules(rules: list[dict]) -> list[dict]:
    result, seen = [], set()
    for rule in rules:
        source = str(rule.get("source", "")).strip()
        target = str(rule.get("target", "")).strip()
        key = source.casefold()
        if not source:
            raise ValueError("correction_empty")
        if key in seen:
            raise ValueError("correction_duplicate")
        seen.add(key)
        result.append({"source": source, "target": target, "enabled": bool(rule.get("enabled", True))})
    return result


def apply_corrections(text: str, rules: list[dict]) -> str:
    active = sorted((r for r in rules if r.get("enabled", True)), key=lambda r: len(r["source"]), reverse=True)
    if not active:
        return text
    pattern = re.compile("|".join(f"(?P<r{i}>(?<!\\w){re.escape(r['source'])}(?!\\w))" for i, r in enumerate(active)), re.IGNORECASE)
    return pattern.sub(lambda m: active[int(m.lastgroup[1:])]["target"], text)


def protect_names(text: str, rules: list[dict]) -> tuple[str, dict[str, str]]:
    targets = sorted({r["target"] for r in rules if r.get("enabled", True) and r["target"]}, key=len, reverse=True)
    mapping = {}
    if not targets:
        return text, mapping
    prefix = "WWPNAME" + uuid.uuid4().hex[:12].upper()
    pattern = re.compile("|".join(f"(?<!\\w){re.escape(t)}(?!\\w)" for t in targets))

    def replace(match):
        token = f"{prefix}X{len(mapping)}X"
        mapping[token] = match.group()
        return token

    return pattern.sub(replace, text), mapping


def restore_names(text: str, mapping: dict[str, str]) -> str:
    for token, name in mapping.items():
        if text.count(token) != 1:
            raise ValueError("correction_placeholder_lost")
        text = text.replace(token, name)
    if re.search(r"WWPNAME[A-Z0-9]+", text):
        raise ValueError("correction_placeholder_lost")
    return text
