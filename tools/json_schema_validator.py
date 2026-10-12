from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.schema_utils import format_summary, validate_json_input


class JsonSchemaValidatorTool(Tool):
    """Deterministic JSON Schema gate that sits right after an LLM node."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        result = validate_json_input(
            tool_parameters.get("json_input"),
            tool_parameters.get("schema_input"),
        )

        # Message order matters: the text summary is what a human (or the LLM)
        # reads first, the JSON payload is what downstream nodes parse.
        yield self.create_text_message(format_summary(result))
        yield self.create_json_message(result)
