from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.schema_utils import format_summary, validate_json_input

_TRUTHY_VALUES = frozenset({"true", "1", "yes", "on"})


class JsonSchemaValidatorTool(Tool):
    """Deterministic JSON Schema gate that sits right after an LLM node."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        result = validate_json_input(
            tool_parameters.get("json_input"),
            tool_parameters.get("schema_input"),
            strict_mode=_as_bool(tool_parameters.get("strict_mode")),
        )

        # Message order matters: the text summary is what a human (or the LLM)
        # reads first, the JSON payload is what downstream nodes parse.
        yield self.create_text_message(format_summary(result))
        yield self.create_json_message(result)


def _as_bool(value: Any) -> bool:
    """Normalize the select parameter into a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY_VALUES
    return False
