"""Strict JSON decoding shared by the extractor and the validator.

Python's json module accepts the non-standard constants ``NaN``,
``Infinity`` and ``-Infinity`` by default. The plugin's contract is that
every accepted candidate is valid JSON -- the same text downstream nodes
will parse with a strict parser -- so both tools decode through the
helpers here instead of calling ``json.loads`` directly.
"""

from __future__ import annotations

import json
from typing import Any


def _reject_constant(value: str) -> None:
    raise json.JSONDecodeError(f"Invalid JSON constant: {value}", value, 0)


def loads_strict(text: str) -> Any:
    """``json.loads`` that rejects the non-standard NaN/Infinity constants."""
    return json.loads(text, parse_constant=_reject_constant)


def strict_decoder() -> json.JSONDecoder:
    """A ``JSONDecoder`` that rejects the non-standard NaN/Infinity constants."""
    return json.JSONDecoder(parse_constant=_reject_constant)
