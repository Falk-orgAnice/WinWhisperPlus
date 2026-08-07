"""Tests for the local llama.cpp text-optimization client."""

from __future__ import annotations

import hashlib

import pytest

from core.text_optimizer import (
    TextOptimizationError,
    TextOptimizationOptions,
    TextOptimizer,
    _format_short_message,
    _validate_optimized_text,
    build_system_prompt,
)


def _response(text: object) -> dict:
    return {"choices": [{"message": {"content": {"text": text}}}]}


@pytest.mark.parametrize(
    "options",
    [
        TextOptimizationOptions(formatting=True),
        TextOptimizationOptions(formatting=True, cleanup=True),
        TextOptimizationOptions(formatting=True, cleanup=True, redact=True),
    ],
)
def test_combined_options_have_conservative_plain_text_instruction(options: TextOptimizationOptions) -> None:
    prompt = build_system_prompt(options, "de")
    assert "Never invent" in prompt
    assert "plain text only" in prompt
    assert "Formatting is required" in prompt
    assert "GREETING," in prompt
    assert "SIGNATURE." in prompt
    assert "de" in prompt


def test_optimizer_sends_schema_and_non_thinking_request() -> None:
    requests: list[dict] = []
    optimizer = TextOptimizer(request_callable=lambda payload: requests.append(payload) or _response("Guter Text."))

    assert optimizer.optimize(
        "guter text",
        options=TextOptimizationOptions(formatting=True, cleanup=True),
        language="de",
    ) == "Guter Text."

    request = requests[0]
    assert request["temperature"] == 0
    assert request["chat_template_kwargs"] == {"enable_thinking": False}
    assert request["response_format"]["schema"]["required"] == ["text"]
    assert '"text"' in request["messages"][0]["content"]


def test_optimizer_accepts_legacy_message_field_from_local_template() -> None:
    optimizer = TextOptimizer(
        request_callable=lambda _payload: {
            "choices": [{"message": {"content": '{"message": "Bereinigter Text."}'}}]
        }
    )

    assert optimizer.optimize(
        "roher text", options=TextOptimizationOptions(formatting=True, cleanup=True)
    ) == "Bereinigter Text."


@pytest.mark.parametrize(("target", "language_name"), [("pl", "Polish"), ("fr", "French"), ("nl", "Dutch")])
def test_translation_target_is_added_to_the_local_prompt(target: str, language_name: str) -> None:
    prompt = build_system_prompt(
        TextOptimizationOptions(formatting=True, cleanup=True, translation_target=target), "de"
    )

    assert "CRITICAL FINAL REQUIREMENT" in prompt
    assert f"into {language_name}" in prompt
    assert "Remove only unmistakable" in prompt
    assert prompt.endswith("translated output.")


@pytest.mark.parametrize("invalid", ["", "# Heading", "**bold**", "<b>bold</b>", 42])
def test_invalid_or_rich_model_text_is_rejected(invalid: object) -> None:
    with pytest.raises(TextOptimizationError):
        _validate_optimized_text(invalid)


def test_short_message_body_sentences_are_put_on_individual_lines() -> None:
    text = (
        "Hallo Björn,\n\n"
        "ich hoffe es geht dir gut und du kommst gut nach Deutschland. Ich freue mich auf heute Abend.\n\n"
        "Bis später,\n\nDein Bro Falk."
    )

    assert _format_short_message(text) == (
        "Hallo Björn,\n\n"
        "ich hoffe es geht dir gut und du kommst gut nach Deutschland.\n"
        "Ich freue mich auf heute Abend.\n\n"
        "Bis später,\n\nDein Bro Falk."
    )


@pytest.mark.parametrize("greeting", ["Bonjour Marie", "Beste Jan"])
def test_short_messages_in_new_dictation_languages_are_formatted(greeting: str) -> None:
    assert _format_short_message(f"{greeting}, der erste Satz. Der zweite Satz.") == (
        f"{greeting},\n\nder erste Satz.\nDer zweite Satz."
    )


def test_non_message_text_is_not_mechanically_reformatted() -> None:
    text = "Dieser Bericht hat zwei Sätze. Der zweite bleibt im selben Absatz."
    assert _format_short_message(text) == text


def test_translated_english_message_is_still_structured() -> None:
    assert _format_short_message("Hello Björn, I hope you are well. See you later.") == (
        "Hello Björn,\n\nI hope you are well.\nSee you later."
    )


def test_optimizer_retries_once_before_failing() -> None:
    calls = 0

    def broken_response(_payload: dict) -> object:
        nonlocal calls
        calls += 1
        return {"unexpected": "response"}

    optimizer = TextOptimizer(request_callable=broken_response)

    with pytest.raises(TextOptimizationError):
        optimizer.optimize("Text", options=TextOptimizationOptions())
    assert calls == 2


def test_model_hash_is_verified(tmp_path) -> None:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"model-data")
    checksum = tmp_path / "text-model.sha256"
    checksum.write_text(f"{hashlib.sha256(b'model-data').hexdigest()}  model.gguf", encoding="ascii")
    optimizer = TextOptimizer(
        executable_path=tmp_path / "missing.exe",
        model_path=model,
        model_hash_path=checksum,
        request_callable=lambda _payload: _response("ok"),
    )

    optimizer._verify_model_hash()
    assert optimizer._hash_verified is True
