"""Deterministic JSON extraction from raw LLM output.

The extractor answers exactly one question: where is the JSON in this text?
It tries three shapes in order and returns the first hit:

1. the whole input already is JSON;
2. a ```json / ``` fenced code block whose content is JSON;
3. the first JSON object or array embedded anywhere in the text, only when
   ``scan_embedded`` is on.

Every candidate is decoded before it is accepted, so the returned string is
always valid JSON; decoding is strict, so the non-standard ``NaN`` and
``Infinity`` constants are rejected. Shape 3 seeds its scan at ``{`` and
``[``, which keeps bare numbers, strings and literals in prose from being
mistaken for a result.
Whether the extracted JSON has the right structure is the JSON Schema
Validator's business, not this module's.
"""

from __future__ import annotations

import json
import re

from utils.failures import ValidationFailure
from utils.strict_json import loads_strict, strict_decoder
from utils.strings import trim_to_empty

# Matches a fenced code block (```lang, newline, content, ```). The regex only
# locates fence boundaries -- no bracket pairing is involved, so it is safe.
_FENCE_PATTERN = re.compile(r"```([^\n`]*)[ \t]*\n(.*?)```", re.DOTALL)

# Only these fence language tags are trusted to hold JSON. A fence tagged
# ``python`` or ``bash`` is not preferred over step 3, but its content is still
# reachable there once it decodes as JSON.
_JSON_FENCE_LANGUAGES = frozenset({"", "json"})

# Step 3 seeds its scan at object and array openers only.
_CONTAINER_OPENERS = re.compile(r"[{\[]")

# Shared detail for a candidate nested beyond what the interpreter admits.
_TOO_DEEP_DETAIL = "The input is nested too deeply to be parsed"


def extract_json(text: str, *, scan_embedded: bool = False) -> str:
    """Return the first parseable JSON string in ``text``.

    ``scan_embedded`` enables shape 3, which reads through surrounding prose to
    find a JSON object or array. It is off by default, so only the whole input
    and trusted code fences are examined unless the caller asks for more.

    The returned string is a verbatim slice of the input -- never
    re-serialized -- so number spellings, key order, and whitespace are
    exactly what the model emitted. Raises :class:`ValidationFailure` with
    ``no_json_found`` when none of the checked shapes yields parseable JSON.
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
    if scan_embedded:
        embedded = _scan_containers(text)
        if embedded is not None:
            return embedded
        detail = (
            "No parseable JSON found: the input is not JSON, it contains no "
            "parseable ```json code block, and it carries no JSON object or array"
        )
    else:
        detail = (
            "No parseable JSON found: the input is not JSON, and it contains no "
            "parseable ```json code block; scan_embedded is off, so JSON "
            "embedded in surrounding text was not searched for"
        )
    raise ValidationFailure("no_json_found", detail)


def _scan_containers(text: str) -> str | None:
    """Return the first JSON object or array embedded in ``text``.

    Seeding the scan at ``{`` and ``[`` is what restricts it to objects and
    arrays: a bare number, string or literal in prose never becomes a
    candidate. Each candidate must decode before it is accepted, and one that
    fails to decode moves the scan to the next opener.
    """
    decoder = strict_decoder()
    cursor = 0
    while True:
        opener = _CONTAINER_OPENERS.search(text, cursor)
        if opener is None:
            return None
        start = opener.start()
        try:
            _, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        except RecursionError:
            raise ValidationFailure("internal_error", _TOO_DEEP_DETAIL)
        return text[start:end]


def _is_parseable(candidate: str) -> bool:
    """True when ``candidate`` parses as JSON.

    A candidate too deeply nested to parse is reported as an
    ``internal_error`` rather than silently skipped -- the text may well be
    genuine JSON, just beyond what the interpreter stack admits.
    """
    try:
        loads_strict(candidate)
    except json.JSONDecodeError:
        return False
    except RecursionError:
        raise ValidationFailure("internal_error", _TOO_DEEP_DETAIL)
    return True
