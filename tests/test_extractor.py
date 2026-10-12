"""Tests for the extractor tool wrapper: message shape and parameter handling."""

import pytest

from dify_plugin.entities.invoke_message import InvokeMessage
from dify_plugin.entities.tool import ToolInvokeMessage
from tools.json_extractor import JsonExtractorTool


def make_tool():
    """Build a tool instance without booting the plugin SDK runtime."""
    tool = JsonExtractorTool.__new__(JsonExtractorTool)
    tool.response_type = ToolInvokeMessage
    return tool


def invoke(**params):
    return list(make_tool()._invoke(params))


def text_of(messages):
    return messages[0].message.text


def json_of(messages):
    return messages[1].message.json_object


class TestToolMessages:
    def test_success_emits_text_then_json(self):
        messages = invoke(llm_output='Sure!\n```json\n{"a": 1}\n```')
        assert len(messages) == 2
        assert messages[0].type == InvokeMessage.MessageType.TEXT
        assert messages[1].type == InvokeMessage.MessageType.JSON
        assert text_of(messages) == "Extracted JSON."
        assert json_of(messages) == {"found": True, "json": '{"a": 1}'}

    def test_whole_input(self):
        assert json_of(invoke(llm_output='{"a": 1}')) == {
            "found": True,
            "json": '{"a": 1}',
        }

    def test_miss_payload_has_all_fields(self):
        payload = json_of(invoke(llm_output="no json here"))
        assert payload["found"] is False
        assert payload["error_type"] == "no_json_found"
        assert set(payload) == {"found", "error_type", "error"}

    def test_miss_text_includes_error_type(self):
        assert text_of(invoke(llm_output="no json here")).startswith(
            "Extraction failed [no_json_found]:"
        )

    def test_missing_parameter_is_invalid_input(self):
        payload = json_of(invoke())
        assert payload["found"] is False
        assert payload["error_type"] == "invalid_input"
        assert payload["error"] == "llm_output is empty"
