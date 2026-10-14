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


def variables_of(messages):
    return {
        m.message.variable_name: m.message.variable_value
        for m in messages
        if m.type == InvokeMessage.MessageType.VARIABLE
    }


class TestToolMessages:
    def test_success_emits_text_then_json(self):
        messages = invoke(text='Sure!\n```json\n{"a": 1}\n```')
        assert messages[0].type == InvokeMessage.MessageType.TEXT
        assert messages[1].type == InvokeMessage.MessageType.JSON
        assert text_of(messages) == '{"a": 1}'
        assert json_of(messages) == {"found": True, "json_text": '{"a": 1}'}

    def test_text_and_json_come_first(self):
        # Downstream helpers rely on message order: summary, payload, then
        # one variable message per declared output.
        messages = invoke(text='{"a": 1}')
        assert [m.type for m in messages][:2] == [
            InvokeMessage.MessageType.TEXT,
            InvokeMessage.MessageType.JSON,
        ]
        assert all(
            m.type == InvokeMessage.MessageType.VARIABLE for m in messages[2:]
        )

    def test_whole_input(self):
        assert json_of(invoke(text='{"a": 1}')) == {
            "found": True,
            "json_text": '{"a": 1}',
        }

    def test_miss_payload_has_all_fields(self):
        payload = json_of(invoke(text="no json here"))
        assert payload["found"] is False
        assert payload["error_type"] == "no_json_found"
        assert set(payload) == {"found", "error_type", "error_detail"}

    def test_miss_text_is_empty(self):
        assert text_of(invoke(text="no json here")) == ""

    def test_missing_parameter_is_invalid_input(self):
        payload = json_of(invoke())
        assert payload["found"] is False
        assert payload["error_type"] == "invalid_input"
        assert payload["error_detail"] == "text is empty"


class TestOutputVariables:
    """Declared output_schema variables must be returned as VARIABLE messages,
    otherwise Dify reports "Variable not found" for downstream references."""

    def test_success_variables(self):
        messages = invoke(text='```json\n{"a": 1}\n```')
        assert variables_of(messages) == {"found": True, "json_text": '{"a": 1}'}

    def test_failure_variables(self):
        messages = invoke(text="no json here")
        assert variables_of(messages) == {
            "found": False,
            "error_type": "no_json_found",
            "error_detail": (
                "No parseable JSON found: the input is not JSON, and it "
                "contains no parseable ```json code block"
            ),
        }

    def test_variables_match_json_payload(self):
        messages = invoke(text="no json here")
        assert variables_of(messages) == json_of(messages)
