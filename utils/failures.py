"""The failure contract shared by the validator and its callers.

Every classified failure is raised as :class:`ValidationFailure`; the
``*_result`` helpers build the structured payloads a Dify tool emits.
This module sits at the bottom of the dependency graph and imports nothing
from the other utils modules.
"""

from __future__ import annotations

from typing import Any


class ValidationFailure(Exception):
    """A known, classified validation failure.

    Raised at the point of detection. Carries everything the failure payload
    needs: the error type, the human-readable message, and the failure
    locations (the instance path, its JSONPath rendering, and the schema
    path).
    """

    def __init__(
            self,
            error_type: str,
            error: str,
            absolute_path: Any = (),
            schema_path: Any = (),
            json_path: str = "",
    ) -> None:
        super().__init__(error)
        self.error_type = error_type
        self.error = error
        self.absolute_path = list(absolute_path)
        self.schema_path = list(schema_path)
        self.json_path = json_path

    def to_result(self) -> dict[str, Any]:
        """Convert the failure into the structured failure payload."""
        return {
            "is_valid": False,
            "error_type": self.error_type,
            "error_detail": self.error,
            "absolute_path": list(self.absolute_path),
            "json_path": self.json_path,
            "schema_path": list(self.schema_path),
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
        absolute_path: Any = None,
        schema_path: Any = None,
        json_path: str = "",
) -> dict[str, Any]:
    """Build the payload for a failed validation.

    ``absolute_path``, ``json_path`` and ``schema_path`` are always present
    so downstream nodes can branch on them without defensive checks.
    """
    return {
        "is_valid": False,
        **error_fields(error_type, error),
        "absolute_path": list(absolute_path or []),
        "json_path": json_path,
        "schema_path": list(schema_path or []),
    }


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
        return "Validation passed."
    return (
        f"Validation failed [{result.get('error_type')}]: {result.get('error_detail')}\n"
        f"JSON path: {format_path(result.get('absolute_path'))}\n"
        f"Schema path: {format_path(result.get('schema_path'))}"
    )
