"""Pure-Python JSON Schema validation.

This module intentionally contains no Dify runtime imports so that every
branch can be unit tested directly, without booting the plugin SDK.

Control flow is exception-driven: every classified failure is raised as a
:class:`~utils.failures.ValidationFailure` at the point where it is detected.
Converting exceptions into the structured result dictionaries a Dify tool
needs is the caller's job -- see :mod:`utils.failures`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import (
    Draft201909Validator,
    Draft202012Validator,
    Draft4Validator,
    Draft6Validator,
    Draft7Validator,
)
from jsonschema.exceptions import SchemaError, ValidationError, best_match
from referencing.exceptions import Unresolvable

from utils.failures import ValidationFailure
from utils.strings import trim_to_empty

# The draft that is used when a schema does not declare ``$schema``.
DEFAULT_DRAFT_VERSION = "2020-12"

_DRAFT_VALIDATORS: dict[str, Any] = {
    "2020-12": Draft202012Validator,
    "2019-09": Draft201909Validator,
    "07": Draft7Validator,
    "06": Draft6Validator,
    "04": Draft4Validator,
}

SUPPORTED_DRAFTS: tuple[str, ...] = (
    "https://json-schema.org/draft/2020-12/schema",
    "https://json-schema.org/draft/2019-09/schema",
    "http://json-schema.org/draft-07/schema#",
    "http://json-schema.org/draft-06/schema#",
    "http://json-schema.org/draft-04/schema#",
)

# ``json-schema.org/schema`` without a draft segment historically means
# "whatever the implementation supports"; we map it onto the default draft.
_GENERIC_POINTER_PATTERN = re.compile(r"json-schema\.org/schema/?#?$", re.IGNORECASE)

# A ``$schema`` is only honoured when it really points at json-schema.org (or
# is a bare shorthand such as ``draft-07``). Without this guard, any unrelated
# URI that merely contains "draft-07" would silently select that validator.
_JSON_SCHEMA_ORG_PATTERN = re.compile(r"^https?://(?:www\.)?json-schema\.org/", re.IGNORECASE)
_BARE_DRAFT_PATTERN = re.compile(r"^draft[-/](\d{4}-\d{2}|0?\d)$", re.IGNORECASE)

# ``draft-07`` / ``draft/2020-12`` / ``draft3`` -- the numeric part is enough
# to pick a validator class.
_DRAFT_VERSION_PATTERN = re.compile(r"draft[-/](\d{4}-\d{2}|0?\d)", re.IGNORECASE)

# Every unresolvable ``$ref`` surfaces as jsonschema's ``_WrappedReferencingError``,
# which derives from ``referencing.exceptions.Unresolvable`` -- as do the wrapped
# causes themselves (``Unresolvable``, ``PointerToNowhere``). That public base is
# what jsonschema's own deprecation notice for ``RefResolutionError`` tells you to
# catch, so use it directly rather than the private jsonschema name.


def _loads(raw: str, error_type: str, label: str) -> Any:
    """Parse JSON text.

    Strictly ``json.loads`` and nothing else. The plugin validates, it does not
    prepare input: anything that is not already valid JSON -- including a
    Markdown code fence around it -- is raised as :class:`ValidationFailure`
    with ``error_type`` so the caller fixes the value the downstream nodes
    will actually receive.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValidationFailure(error_type, f"{label}: {_describe_decode_error(error)}")
    except RecursionError:
        # json.loads recurses for every nesting level, so a pathologically
        # nested document exhausts the interpreter stack instead of raising a
        # JSONDecodeError. That must never escape as an uncaught exception.
        raise ValidationFailure(
            error_type, f"{label}: the document is nested too deeply to be parsed"
        )


def _describe_decode_error(error: json.JSONDecodeError) -> str:
    return f"{error.msg} at line {error.lineno} column {error.colno}"


def resolve_draft(schema: dict[str, Any]) -> Any:
    """Pick the validator class for a schema.

    Returns the validator class, or raises :class:`ValidationFailure`
    (``unsupported_draft``) when the declared ``$schema`` points at an
    unsupported draft.
    """
    declared = schema.get("$schema")
    if not isinstance(declared, str):
        return _DRAFT_VALIDATORS[DEFAULT_DRAFT_VERSION]

    stripped = trim_to_empty(declared)
    if not stripped:
        # Not a usable identifier at all; fall through to the default draft so
        # that check_schema() reports the precise structural problem.
        return _DRAFT_VALIDATORS[DEFAULT_DRAFT_VERSION]

    version = _draft_version(stripped)
    if version is None:
        if _GENERIC_POINTER_PATTERN.search(stripped):
            return _DRAFT_VALIDATORS[DEFAULT_DRAFT_VERSION]
        raise ValidationFailure("unsupported_draft", _unsupported_draft_message(declared))

    validator_cls = _DRAFT_VALIDATORS.get(version)
    if validator_cls is None:
        raise ValidationFailure("unsupported_draft", _unsupported_draft_message(declared))

    if not (
            _JSON_SCHEMA_ORG_PATTERN.match(stripped)
            or _BARE_DRAFT_PATTERN.match(stripped)
    ):
        # An unrelated URI that merely mentions a draft number (for example a
        # third-party mirror) is not a draft declaration we can trust.
        raise ValidationFailure("unsupported_draft", _unsupported_draft_message(declared))
    return validator_cls


def _draft_version(uri: str) -> str | None:
    match = _DRAFT_VERSION_PATTERN.search(uri)
    if match is None:
        return None
    version = match.group(1)
    return f"0{version}" if len(version) == 1 else version


def _unsupported_draft_message(declared: str) -> str:
    return (
        f"Unsupported JSON Schema draft: {declared}. "
        f"Supported drafts: {', '.join(SUPPORTED_DRAFTS)}."
    )


# Deliberately NOT raising CPython's recursion limit. ``jsonschema`` validates a
# schema against its metaschema in pure Python and burns roughly ten interpreter
# frames per nesting level, so the default limit of 1000 admits schemas up to
# ~95 levels deep, and validates data up to ~100-200 levels deep against a
# recursive schema. That is far beyond anything an LLM emits or a human writes
# (realistic schemas sit at 3-30 levels), and every input past the boundary is
# still answered with a structured error rather than an exception.
#
# Raising it would buy capability nobody needs while mutating process-global
# state -- ``sys.setrecursionlimit`` affects every task sharing this process,
# which is a poor trade for a plugin that runs inside a shared daemon.


def validate_json_input(
        json_input: str,
        schema_input: str,
) -> None:
    """Validate the JSON text ``json_input`` against the schema text ``schema_input``.

    Both arguments must already be strings. Converting arbitrary parameter
    values into JSON text -- and rejecting missing or blank ones -- is the
    caller's job, see :mod:`utils.strings`.

    Returns ``None`` when the input satisfies the schema. Raises
    :class:`ValidationFailure` for every classified failure: invalid JSON, an
    invalid schema, an unsupported draft, an unresolvable ``$ref``, or a
    validation mismatch. Unexpected interpreter-level errors propagate to the
    caller unchanged.

    The schema is used exactly as given: the plugin validates, it does not
    rewrite the caller's intent. Anything beyond what the schema itself says --
    including rejecting undeclared properties -- is the schema author's call,
    expressed with ``additionalProperties: false`` where they want it.
    """
    instance = _loads(json_input, "invalid_json", "Invalid JSON input")
    schema = _loads(schema_input, "invalid_schema_json", "Invalid JSON Schema")

    if not isinstance(schema, (dict, bool)):
        raise ValidationFailure(
            "schema_error",
            "Schema itself is invalid: a JSON Schema must be an object or a boolean.",
        )

    validator_cls = _DRAFT_VALIDATORS[DEFAULT_DRAFT_VERSION]
    if isinstance(schema, dict):
        validator_cls = resolve_draft(schema)

    try:
        validator_cls.check_schema(schema)
    except SchemaError as error:
        raise ValidationFailure(
            "schema_error",
            f"Schema itself is invalid: {error.message}",
            schema_path=error.absolute_schema_path,
        )
    except RecursionError:
        # Metaschema validation burns ~10 frames per nesting level, so a schema
        # deeper than ~95 levels exhausts the default stack here. Such a schema
        # cannot be confirmed, and the schema is what has to change.
        raise ValidationFailure(
            "schema_error",
            "Schema itself is invalid: the schema is nested too deeply to be checked",
        )

    validator = validator_cls(schema)
    try:
        error = best_match(validator.iter_errors(instance))
    except ValidationError as validation_error:
        error = validation_error
    except Unresolvable as ref_error:
        raise ValidationFailure(
            "ref_resolution_error",
            f"Schema $ref resolution failed: {ref_error}",
        )
    except SchemaError as structural_error:
        raise ValidationFailure(
            "schema_error",
            f"Schema itself is invalid: {structural_error.message}",
            schema_path=structural_error.absolute_schema_path,
        )
    except RecursionError:
        # Either the data is genuinely too deep, or the schema loops on itself
        # (``{"$ref": "#"}``) and never terminates. Both are input problems, and
        # the message has to be honest about not knowing which one it was.
        raise ValidationFailure(
            "internal_error",
            "Validation exceeded the interpreter recursion depth; the JSON may "
            "be nested too deeply, or the schema may contain a circular $ref",
        )

    if error is None:
        return

    raise ValidationFailure(
        "validation_failed",
        error.message,
        path=error.absolute_path,
        schema_path=error.absolute_schema_path,
    )
