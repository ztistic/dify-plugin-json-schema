"""String helpers: blank handling and parameter-to-JSON-text conversion."""

from __future__ import annotations

import json
from typing import Any

from utils.failures import ValidationFailure


def trim_to_empty(value: str | None) -> str:
    """Return ``value`` stripped, or ``""`` when it is None."""
    return value.strip() if value else ""


def is_blank(value: str | None) -> bool:
    """True when ``value`` is None, empty, or nothing but whitespace."""
    return not trim_to_empty(value)


def _stringify(value: Any) -> str:
    """Return ``value`` as JSON text.

    Raises :class:`ValidationFailure` (``invalid_input``) carrying only the
    reason (for example ``"is empty"``) -- which parameter was being converted
    is the caller's knowledge, see :func:`stringify_parameter`.
    """
    if value is None:
        raise ValidationFailure("invalid_input", "is empty")
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError, RecursionError):
            raise ValidationFailure(
                "invalid_input", "cannot be converted to a JSON string"
            )
    if is_blank(text):
        raise ValidationFailure("invalid_input", "is empty")
    return text


def stringify_parameter(value: Any, parameter: str) -> str:
    """Like :func:`_stringify`, but attributes a failure to ``parameter``.

    Turns the bare reason into a message that names the offending input, for
    example ``"json_input is empty"``.
    """
    try:
        return _stringify(value)
    except ValidationFailure as failure:
        raise ValidationFailure(
            failure.error_type, f"{parameter} {failure.error}"
        )
