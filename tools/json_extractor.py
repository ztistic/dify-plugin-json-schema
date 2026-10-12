from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.extraction import extract_json
from utils.failures import ValidationFailure, error_fields
from utils.strings import get_string


class JsonExtractorTool(Tool):
    """Deterministic extractor that sits between an LLM node and the validator."""

    def _invoke(
            self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        # Same boundary contract as the validator: adapt raw parameters, and
        # never let an exception escape -- every failure is a payload.
        try:
            text = get_string(tool_parameters, "llm_output")
            result = {"found": True, "json": extract_json(text)}
        except ValidationFailure as failure:
            result = {
                "found": False,
                **error_fields(failure.error_type, failure.error),
            }
        except Exception as escaped:  # noqa: BLE001 - the tool must never raise
            result = {
                "found": False,
                **error_fields(
                    "internal_error",
                    f"Unexpected error while extracting: "
                    f"{type(escaped).__name__}: {escaped}",
                ),
            }

        # Message order matters: the text summary is what a human (or the LLM)
        # reads first, the JSON payload is what downstream nodes parse.
        yield self.create_text_message(_summary(result))
        yield self.create_json_message(result)


def _summary(result: dict[str, Any]) -> str:
    """Render an extraction result as the tool's human-readable text output."""
    if result.get("found"):
        return "Extracted JSON."
    return f"Extraction failed [{result.get('error_type')}]: {result.get('error')}"
