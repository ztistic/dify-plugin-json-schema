"""Deterministic JSON extraction from raw LLM output.

The extractor answers exactly one question: where is the JSON in this text?
It recognizes two unambiguous shapes and nothing else:

1. the whole input already is JSON;
2. a ```json / ``` fenced code block.

Bare JSON embedded in prose is deliberately NOT extracted: scanning free text
for balanced brackets cannot be done without guessing, and this plugin
reports honestly instead of guessing. Whether the extracted text has the
right structure is the JSON Schema Validator's business, not this module's.
"""

from __future__ import annotations

import json
import re

from utils.failures import ValidationFailure
from utils.strings import trim_to_empty

# Matches a fenced code block (```lang, newline, content, ```). The regex only
# locates fence boundaries -- no bracket pairing is involved, so it is safe.
_FENCE_PATTERN = re.compile(r"```([^\n`]*)[ \t]*\n(.*?)```", re.DOTALL)

# Only these fence language tags are trusted to hold JSON. A fence tagged
# ``python`` or ``bash`` is skipped rather than gambled on.
_JSON_FENCE_LANGUAGES = frozenset({"", "json"})


def extract_json(text: str) -> str:
    """Return the first parseable JSON string in ``text``.

    The returned string is a verbatim slice of the input -- never
    re-serialized -- so number spellings, key order, and whitespace are
    exactly what the model emitted. Raises :class:`ValidationFailure` with
    ``no_json_found`` when neither shape yields parseable JSON.
    """
    candidate = trim_to_empty(text)
    if not candidate:
        raise ValidationFailure("invalid_input", "The input is empty")
    if _is_parseable(candidate):
        return candidate
    for match in _FENCE_PATTERN.finditer(text):
        if match.group(1).strip().lower() not in _JSON_FENCE_LANGUAGES:
            continue
        fenced = trim_to_empty(match.group(2))
        if fenced and _is_parseable(fenced):
            return fenced
    raise ValidationFailure(
        "no_json_found",
        "No parseable JSON found: the input is not JSON, and it contains no "
        "parseable ```json code block",
    )


def _is_parseable(candidate: str) -> bool:
    """True when ``candidate`` parses as JSON.

    A candidate too deeply nested to parse is reported as an
    ``internal_error`` rather than silently skipped -- the text may well be
    genuine JSON, just beyond what the interpreter stack admits.
    """
    try:
        json.loads(candidate)
    except json.JSONDecodeError:
        return False
    except RecursionError:
        raise ValidationFailure(
            "internal_error",
            "The input is nested too deeply to be parsed",
        )
    return True
