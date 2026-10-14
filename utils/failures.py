"""The failure contract shared by the validator and its callers.

Every classified failure is raised as :class:`ValidationFailure`; the
``*_result`` helpers build the structured payloads a Dify tool emits.
This module sits at the bottom of the dependency graph and imports nothing
from the other utils modules.
"""

from __future__ import annotations

import json
from typing import Any


class ValidationFailure(Exception):
    """A known, classified validation failure.

    Raised at the point of detection. Carries everything the failure payload
    needs: the error type, the human-readable message, and the failure
    locations -- the JSONPath string ``jsonschema`` renders for the offending
    instance value, plus the raw path segments of the instance and of the
    violated schema keyword.
    """

    def __init__(
            self,
            error_type: str,
            error: str,
            json_path: str = "",
            absolute_path: Any = (),
            absolute_schema_path: Any = (),
    ) -> None:
        super().__init__(error)
        self.error_type = error_type
        self.error = error
        self.json_path = json_path
        self.absolute_path = list(absolute_path)
        self.absolute_schema_path = list(absolute_schema_path)

    def to_result(self) -> dict[str, Any]:
        """Convert the failure into the structured failure payload."""
        return {
            "is_valid": False,
            "error_type": self.error_type,
            "error_detail": self.error,
            "json_path": self.json_path,
            "absolute_path": list(self.absolute_path),
            "absolute_schema_path": list(self.absolute_schema_path),
        }


def ok_result() -> dict[str, Any]:
    """Build the payload for a successful validation."""
    return {"is_valid": True}


def unexpected_failure_result(escaped: BaseException) -> dict[str, Any]:
    """Map an unclassified escape to the ``internal_error`` payload.

    The validator raises :class:`ValidationFailure` for every classified
    failure; anything else that escapes lands here at the call site, which
    must still answer with a structured payload rather than let an exception
    out of a Dify tool.
    """
    if isinstance(escaped, RecursionError):
        return _fail(
            "internal_error",
            "The JSON or the schema is nested too deeply to be validated",
        )
    return _fail(
        "internal_error",
        f"Unexpected error while validating: "
        f"{type(escaped).__name__}: {escaped}",
    )


def error_fields(error_type: str, error: str) -> dict[str, Any]:
    """The two fields every failure payload carries."""
    return {"error_type": error_type, "error_detail": error}


def _fail(
        error_type: str,
        error: str,
        json_path: str = "",
        absolute_path: Any = None,
        absolute_schema_path: Any = None,
) -> dict[str, Any]:
    """Build the payload for a failed validation.

    The three path fields are always present so downstream nodes can branch
    on them without defensive checks.
    """
    return {
        "is_valid": False,
        **error_fields(error_type, error),
        "json_path": json_path,
        "absolute_path": list(absolute_path or []),
        "absolute_schema_path": list(absolute_schema_path or []),
    }


def format_summary(result: dict[str, Any]) -> str:
    """Render a validation result as the tool's human-readable text output."""
    if result.get("is_valid"):
        return "Validation passed."
    return (
        f"Validation failed [{result.get('error_type')}]: {result.get('error_detail')}\n"
        f"JSON path: {result.get('json_path')}\n"
        f"Schema path: {json.dumps(result.get('absolute_schema_path'))}"
    )
