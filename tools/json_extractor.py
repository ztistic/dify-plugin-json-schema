from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.extraction import extract_json
from utils.failures import ValidationFailure
from utils.strings import get_string


class JsonExtractorTool(Tool):
    """Deterministic extractor that sits between an LLM node and the validator."""

    def _invoke(
            self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        # Same boundary contract as the validator: adapt raw parameters, and
        # never let an exception escape -- every failure is a payload.
        try:
            text = get_string(tool_parameters, "text")
            # Shape 3 reads through surrounding prose, so it stays off unless
            # the parameter asks for it -- only a real boolean True enables it.
            scan_embedded = tool_parameters.get("scan_embedded") is True
            result = {
                "found": True,
                "json_text": extract_json(text, scan_embedded=scan_embedded),
            }
        except ValidationFailure as failure:
            result = {
                "found": False,
                "error_type": failure.error_type,
                "error_detail": failure.error,
            }
        except Exception as escaped:  # noqa: BLE001 - the tool must never raise
            result = {
                "found": False,
                "error_type": "internal_error",
                "error_detail": (
                    f"Unexpected error while extracting: "
                    f"{type(escaped).__name__}: {escaped}"
                ),
            }

        # Message order matters: the text summary is what a human (or the LLM)
        # reads first, the JSON payload is what downstream nodes parse.
        yield self.create_text_message(_summary(result))
        yield self.create_json_message(result)
        # Declaring output_schema is not enough: Dify only populates the named
        # output variables (found, json_text, error_type, error_detail) if the tool returns
        # them via create_variable_message. Without this loop, referencing
        # {{node.found}} in a downstream branch fails with "Variable not found".
        for name, value in result.items():
            yield self.create_variable_message(name, value)


def _summary(result: dict[str, Any]) -> str:
    """Render an extraction result as the tool's text output.

    On success the extracted JSON string itself is the text output, so a
    downstream node can consume it directly; on failure the text is empty and
    the failure detail lives in the JSON payload only.
    """
    if result.get("found"):
        return result["json_text"]
    return ""
