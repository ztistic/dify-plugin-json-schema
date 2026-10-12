"""Pure-Python JSON Schema validation helpers.

This module intentionally contains no Dify runtime imports so that every
branch can be unit tested directly, without booting the plugin SDK.

The single entry point is :func:`validate_json_input`, which never raises:
every failure mode is converted into a structured result dictionary.
"""

from __future__ import annotations

import copy
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

# Keywords whose value is always a (sub)schema.
_STRICT_SCHEMA_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "additionalItems",
        "contains",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)

# Keywords whose value is a list of (sub)schemas.
_STRICT_SCHEMA_LIST_KEYWORDS = frozenset(
    {"allOf", "anyOf", "items", "oneOf", "prefixItems"}
)

# Keywords whose value maps a name onto a (sub)schema.
_STRICT_SCHEMA_MAP_KEYWORDS = frozenset(
    {
        "$defs",
        "definitions",
        "dependentSchemas",
        "patternProperties",
        "properties",
    }
)


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


def _stringify(value: Any) -> tuple[str | None, str | None]:
    """Return ``(text, problem)`` where ``problem`` is None when usable.

    ``problem`` is ``"empty"`` for missing/blank input and
    ``"unrepresentable"`` for a value that cannot be turned into JSON text.
    """
    if value is None:
        return None, "empty"
    if isinstance(value, str):
        return (value, None) if value.strip() else (None, "empty")
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError, RecursionError):
        return None, "unrepresentable"
    return (text, None) if text.strip() else (None, "empty")


def _input_problem_message(parameter: str, problem: str) -> str:
    if problem == "empty":
        return f"{parameter} is empty"
    return f"{parameter} cannot be converted to a JSON string"


def _extract_json_text(raw: str) -> str | None:
    """Recover JSON text from a Markdown code fence, if present.

    LLMs frequently wrap their structured output in ```json fences, often with
    a sentence in front of it. The strict parse stays authoritative: only when
    it fails do we try to unwrap the first fence, so genuinely broken JSON is
    still reported as ``invalid_json``.
    """
    lines = raw.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            start = index + 1
            break
    if start is None:
        return None

    body: list[str] = []
    for line in lines[start:]:
        if line.strip().startswith("```"):
            break
        body.append(line)
    candidate = "\n".join(body).strip()
    return candidate or None


def _loads(raw: str) -> tuple[Any, str | None]:
    """Parse JSON text, returning ``(value, None)`` or ``(None, message)``."""
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as first_error:
        recovered = _extract_json_text(raw)
        if recovered is None:
            return None, _describe_decode_error(first_error)
        try:
            return json.loads(recovered), None
        except json.JSONDecodeError as second_error:
            return None, _describe_decode_error(second_error)
    except RecursionError:
        # json.loads recurses for every nesting level, so a pathologically
        # nested document exhausts the interpreter stack instead of raising a
        # JSONDecodeError. That must never escape as an uncaught exception.
        return None, "the document is nested too deeply to be parsed"


def _describe_decode_error(error: json.JSONDecodeError) -> str:
    return f"{error.msg} at line {error.lineno} column {error.colno}"


def resolve_draft(schema: dict[str, Any]) -> tuple[Any, str | None]:
    """Pick the validator class for a schema.

    Returns ``(validator_cls, None)`` when usable, or ``(None, message)`` when
    the declared ``$schema`` points at an unsupported draft.
    """
    declared = schema.get("$schema")
    if declared is None:
        return _DRAFT_VALIDATORS[DEFAULT_DRAFT_VERSION], None

    if not isinstance(declared, str) or not declared.strip():
        # Not a usable identifier at all; fall through to the default draft so
        # that check_schema() reports the precise structural problem.
        return _DRAFT_VALIDATORS[DEFAULT_DRAFT_VERSION], None

    version = _draft_version(declared)
    if version is None:
        if _GENERIC_POINTER_PATTERN.search(declared.strip()):
            return _DRAFT_VALIDATORS[DEFAULT_DRAFT_VERSION], None
        return None, _unsupported_draft_message(declared)

    validator_cls = _DRAFT_VALIDATORS.get(version)
    if validator_cls is None:
        return None, _unsupported_draft_message(declared)

    stripped = declared.strip()
    if not (
            _JSON_SCHEMA_ORG_PATTERN.match(stripped)
            or _BARE_DRAFT_PATTERN.match(stripped)
    ):
        # An unrelated URI that merely mentions a draft number (for example a
        # third-party mirror) is not a draft declaration we can trust.
        return None, _unsupported_draft_message(declared)
    return validator_cls, None


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


def apply_strict_mode(schema: Any) -> Any:
    """Return a copy of ``schema`` with every object closed for extra keys.

    For each object-typed subschema that does not already declare
    ``additionalProperties``, a single ``additionalProperties: false`` is added.
    A subschema that declares ``properties`` or ``required`` but omits ``type``
    is treated as an object too, because that is how such schemas behave.
    """
    if isinstance(schema, bool) or not isinstance(schema, dict):
        return copy.deepcopy(schema)

    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _STRICT_SCHEMA_LIST_KEYWORDS and isinstance(value, list):
            result[key] = [apply_strict_mode(item) for item in value]
        elif key in _STRICT_SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            result[key] = {
                name: apply_strict_mode(sub) for name, sub in value.items()
            }
        elif key == "dependencies" and isinstance(value, dict):
            # Draft-07: values are either arrays of names or subschemas.
            result[key] = {
                name: apply_strict_mode(sub) if isinstance(sub, dict) else sub
                for name, sub in value.items()
            }
        elif key in _STRICT_SCHEMA_KEYWORDS:
            result[key] = apply_strict_mode(value)
        else:
            result[key] = copy.deepcopy(value)

    if "additionalProperties" not in result and _looks_like_object(result):
        result["additionalProperties"] = False
    return result


def _looks_like_object(subschema: dict[str, Any]) -> bool:
    declared = subschema.get("type")
    if isinstance(declared, list):
        # ``{"type": ["object", "null"]}`` is a very common way to express a
        # nullable object, and it must still be closed in strict mode.
        return "object" in declared
    if declared is not None:
        return declared == "object"
    return "properties" in subschema or "required" in subschema


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
        strict_mode: bool = False,
) -> dict[str, Any]:
    """Validate ``json_input`` against ``schema_input``.

    Returns either ``{"is_valid": True, "message": ...}`` or a failure payload
    carrying ``error_type``, ``error``, ``path`` and ``schema_path``. This
    function never raises.
    """
    instance_text, instance_problem = _stringify(json_input)
    if instance_problem is not None:
        return _fail(
            "invalid_input",
            _input_problem_message("json_input", instance_problem),
        )

    schema_text, schema_problem = _stringify(schema_input)
    if schema_problem is not None:
        return _fail(
            "invalid_input",
            _input_problem_message("schema_input", schema_problem),
        )

    try:
        return _validate(instance_text, schema_text, strict_mode)
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
        strict_mode: bool,
) -> dict[str, Any]:
    instance, instance_error = _loads(instance_text)
    if instance_error is not None:
        return _fail("invalid_json", f"Invalid JSON input: {instance_error}")

    schema, schema_error = _loads(schema_text)
    if schema_error is not None:
        return _fail("invalid_schema_json", f"Invalid JSON Schema: {schema_error}")

    if not isinstance(schema, (dict, bool)):
        return _fail(
            "schema_error",
            "Schema itself is invalid: a JSON Schema must be an object or a boolean.",
        )

    validator_cls = _DRAFT_VALIDATORS[DEFAULT_DRAFT_VERSION]
    if isinstance(schema, dict):
        validator_cls, draft_error = resolve_draft(schema)
        if draft_error is not None:
            return _fail("unsupported_draft", draft_error)

    effective_schema = apply_strict_mode(schema) if strict_mode else schema

    try:
        validator_cls.check_schema(effective_schema)
    except SchemaError as error:
        return _fail(
            "schema_error",
            f"Schema itself is invalid: {error.message}",
            schema_path=list(error.absolute_schema_path),
        )
    except RecursionError:
        # Metaschema validation burns ~10 frames per nesting level, so a schema
        # deeper than ~95 levels exhausts the default stack here. Such a schema
        # cannot be confirmed, and the schema is what has to change.
        return _fail(
            "schema_error",
            "Schema itself is invalid: the schema is nested too deeply to be checked",
        )

    validator = validator_cls(effective_schema)
    try:
        error = best_match(validator.iter_errors(instance))
    except ValidationError as validation_error:
        error = validation_error
    except Unresolvable as ref_error:
        return _fail(
            "ref_resolution_error",
            f"Schema $ref resolution failed: {ref_error}",
        )
    except SchemaError as structural_error:
        return _fail(
            "schema_error",
            f"Schema itself is invalid: {structural_error.message}",
            schema_path=list(structural_error.absolute_schema_path),
        )
    except RecursionError:
        # Either the data is genuinely too deep, or the schema loops on itself
        # (``{"$ref": "#"}``) and never terminates. Both are input problems, and
        # the message has to be honest about not knowing which one it was.
        return _fail(
            "internal_error",
            "Validation exceeded the interpreter recursion depth; the JSON may "
            "be nested too deeply, or the schema may contain a circular $ref",
        )
    except Exception as unexpected:  # noqa: BLE001 - never raise
        return _fail(
            "internal_error",
            f"Unexpected error while validating: "
            f"{type(unexpected).__name__}: {unexpected}",
        )

    if error is None:
        return _ok()

    return _fail(
        "validation_failed",
        error.message,
        path=list(error.absolute_path),
        schema_path=list(error.absolute_schema_path),
    )
