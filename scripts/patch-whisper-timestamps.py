"""Use whisper.cpp's VAD-aware token times in the 1.9.4 JSON exporters.

The library maps segment times already, but its CLI/server exporters still
read raw token_data times. Fail closed if a different source needs review.
"""
from pathlib import Path
import sys


def patch(root):
    changes = {
        "examples/server/server.cpp": [
            ("whisper_token_data token = whisper_full_get_token_data(ctx, i, j);",
             "whisper_token_data token = whisper_full_get_token_data(ctx, i, j);\n"
             "                    token.t0 = whisper_full_get_token_t0(ctx, i, j);\n"
             "                    token.t1 = whisper_full_get_token_t1(ctx, i, j);"),
            ("word_t1 = next_token.t1;", "word_t1 = whisper_full_get_token_t1(ctx, i, j);")],
        "examples/cli/cli.cpp": [
            ("auto tok = whisper_full_get_token_data(ctx, i, j);",
             "auto tok = whisper_full_get_token_data(ctx, i, j);\n"
             "                            tok.t0 = whisper_full_get_token_t0(ctx, i, j);\n"
             "                            tok.t1 = whisper_full_get_token_t1(ctx, i, j);"),
            ("m.t1 = tok_next.t1;", "m.t1 = whisper_full_get_token_t1(ctx, i, j);")],
    }
    for relative, replacements in changes.items():
        path = Path(root) / relative
        content = path.read_text(encoding="utf-8")
        for before, after in replacements:
            if after in content:
                continue
            if content.count(before) != 1:
                raise RuntimeError(f"Review timestamp patch for {relative}: {before}")
            content = content.replace(before, after)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    patch(sys.argv[1])
