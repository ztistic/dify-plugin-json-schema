from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.schema_utils import (
    ValidationFailure,
    format_summary,
    ok_result,
    stringify_parameter,
    unexpected_failure_result,
    validate_json_input,
)


class JsonSchemaValidatorTool(Tool):
    """Deterministic JSON Schema gate that sits right after an LLM node."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        # Parameter values arrive from Dify as arbitrary decoded JSON; turning
        # them into the two strings the validator expects is the boundary's
        # job, not the validator's. Likewise, the tool is the boundary that
        # must never raise: every escape becomes a structured payload.
        try:
            instance_text = stringify_parameter(
                tool_parameters.get("json_input"), "json_input"
            )
            schema_text = stringify_parameter(
                tool_parameters.get("schema_input"), "schema_input"
            )
            validate_json_input(instance_text, schema_text)
            result = ok_result()
        except ValidationFailure as failure:
            result = failure.to_result()
        except Exception as escaped:  # noqa: BLE001 - the tool must never raise
            result = unexpected_failure_result(escaped)

        # Message order matters: the text summary is what a human (or the LLM)
        # reads first, the JSON payload is what downstream nodes parse.
        yield self.create_text_message(format_summary(result))
        yield self.create_json_message(result)
