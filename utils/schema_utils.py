"""Pure-Python JSON Schema validation helpers.

This module intentionally contains no Dify runtime imports so that every
branch can be unit tested directly, without booting the plugin SDK.

Internally, control flow is exception-driven: every classified failure is
raised as a :class:`ValidationFailure` at the point where it is detected.
The single entry point, :func:`validate_json_input`, is the boundary that
converts those exceptions into structured result dictionaries -- it never
raises.
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


class ValidationFailure(Exception):
    """A known, classified validation failure.

    Raised at the point of detection and caught once by
    :func:`validate_json_input`. Carries everything the failure payload
    needs: the error type, the human-readable message, and both paths.
    """

    def __init__(
            self,
            error_type: str,
            error: str,
            path: Any = (),
            schema_path: Any = (),
    ) -> None:
        super().__init__(error)
        self.error_type = error_type
        self.error = error
        self.path = list(path)
        self.schema_path = list(schema_path)


def _ok() -> dict[str, Any]:
    """Build the payload for a successful validation."""
    return {"is_valid": True, "message": "Validation passed."}


def _fail(
        error_type: str,
        error: str,
        path: Any = None,
        schema_path: Any = None,
) -> dict[str, Any]:
    """Build the payload for a failed validation.

    ``path`` and ``schema_path`` are always present so downstream nodes can
    branch on them without defensive checks.
    """
    return {
        "is_valid": False,
        "error_type": error_type,
        "error": error,
        "path": list(path or []),
        "schema_path": list(schema_path or []),
    }


def _stringify(value: Any, parameter: str) -> str:
    """Return ``value`` as JSON text.

    Raises :class:`ValidationFailure` (``invalid_input``) when the value is
    missing, blank, or cannot be turned into JSON text.
    """
    if value is None:
        raise ValidationFailure("invalid_input", f"{parameter} is empty")
    if isinstance(value, str):
        if value.strip():
            return value
        raise ValidationFailure("invalid_input", f"{parameter} is empty")
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError, RecursionError):
        raise ValidationFailure(
            "invalid_input", f"{parameter} cannot be converted to a JSON string"
        )
    if text.strip():
        return text
    raise ValidationFailure("invalid_input", f"{parameter} is empty")


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
    if declared is None:
        return _DRAFT_VALIDATORS[DEFAULT_DRAFT_VERSION]

    if not isinstance(declared, str) or not declared.strip():
        # Not a usable identifier at all; fall through to the default draft so
        # that check_schema() reports the precise structural problem.
        return _DRAFT_VALIDATORS[DEFAULT_DRAFT_VERSION]

    version = _draft_version(declared)
    if version is None:
        if _GENERIC_POINTER_PATTERN.search(declared.strip()):
            return _DRAFT_VALIDATORS[DEFAULT_DRAFT_VERSION]
        raise ValidationFailure("unsupported_draft", _unsupported_draft_message(declared))

    validator_cls = _DRAFT_VALIDATORS.get(version)
    if validator_cls is None:
        raise ValidationFailure("unsupported_draft", _unsupported_draft_message(declared))

    stripped = declared.strip()
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


def format_path(path: Any) -> str:
    """Render a JSON pointer path in a human-readable dotted form."""
    if not path:
        return "$ (root)"
    rendered = "$"
    for item in path:
        rendered += f"[{item}]" if isinstance(item, int) else f".{item}"
    return rendered


def format_summary(result: dict[str, Any]) -> str:
    """Render a validation result as the tool's human-readable text output."""
    if result.get("is_valid"):
        return str(result.get("message") or "Validation passed.")
    return (
        f"Validation failed [{result.get('error_type')}]: {result.get('error')}\n"
        f"JSON path: {format_path(result.get('path'))}\n"
        f"Schema path: {format_path(result.get('schema_path'))}"
    )


def validate_json_input(
        json_input: Any,
        schema_input: Any,
) -> dict[str, Any]:
    """Validate ``json_input`` against ``schema_input``.

    Returns either ``{"is_valid": True, "message": ...}`` or a failure payload
    carrying ``error_type``, ``error``, ``path`` and ``schema_path``. This is
    the boundary that converts :class:`ValidationFailure` into the structured
    result; it never raises.

    The schema is used exactly as given: the plugin validates, it does not
    rewrite the caller's intent. Anything beyond what the schema itself says --
    including rejecting undeclared properties -- is the schema author's call,
    expressed with ``additionalProperties: false`` where they want it.
    """
    try:
        instance_text = _stringify(json_input, "json_input")
        schema_text = _stringify(schema_input, "schema_input")
        return _validate(instance_text, schema_text)
    except ValidationFailure as failure:
        return _fail(
            failure.error_type,
            failure.error,
            failure.path,
            failure.schema_path,
        )
    except RecursionError:
        # A final safety net: no interpreter-level failure may ever escape as
        # an uncaught exception out of a Dify tool.
        return _fail(
            "internal_error",
            "The JSON or the schema is nested too deeply to be validated",
        )
    except Exception as unexpected:  # noqa: BLE001 - the tool must never raise
        return _fail(
            "internal_error",
            f"Unexpected error while validating: "
            f"{type(unexpected).__name__}: {unexpected}",
        )


def _validate(
        instance_text: str,
        schema_text: str,
) -> dict[str, Any]:
    instance = _loads(instance_text, "invalid_json", "Invalid JSON input")
    schema = _loads(schema_text, "invalid_schema_json", "Invalid JSON Schema")

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
        return _ok()

    raise ValidationFailure(
        "validation_failed",
        error.message,
        path=error.absolute_path,
        schema_path=error.absolute_schema_path,
    )
