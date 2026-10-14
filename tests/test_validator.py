"""Tests for the Dify tool wrapper: message shape and parameter handling."""

import json

import pytest

from dify_plugin.entities.invoke_message import InvokeMessage
from dify_plugin.entities.tool import ToolInvokeMessage
from tools.json_schema_validator import JsonSchemaValidatorTool

PERSON_SCHEMA = json.dumps(
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["age"],
        "properties": {"age": {"type": "integer", "minimum": 0}},
    }
)


def make_tool():
    """Build a tool instance without booting the plugin SDK runtime."""
    tool = JsonSchemaValidatorTool.__new__(JsonSchemaValidatorTool)
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
        messages = invoke(json_input='{"age": 30}', schema_input=PERSON_SCHEMA)
        assert messages[0].type == InvokeMessage.MessageType.TEXT
        assert messages[1].type == InvokeMessage.MessageType.JSON
        assert text_of(messages) == "Validation passed."
        assert json_of(messages) == {"is_valid": True}

    def test_text_and_json_come_first(self):
        # Downstream helpers rely on message order: summary, payload, then
        # one variable message per declared output.
        messages = invoke(json_input='{"age": 30}', schema_input=PERSON_SCHEMA)
        assert [m.type for m in messages][:2] == [
            InvokeMessage.MessageType.TEXT,
            InvokeMessage.MessageType.JSON,
        ]
        assert all(
            m.type == InvokeMessage.MessageType.VARIABLE for m in messages[2:]
        )

    def test_failure_payload_has_all_fields(self):
        messages = invoke(json_input='{"name": "Alice"}', schema_input=PERSON_SCHEMA)
        payload = json_of(messages)
        assert payload["is_valid"] is False
        assert payload["error_type"] == "validation_failed"
        assert payload["error_detail"] == "'age' is a required property"
        assert payload["json_path"] == "$"
        assert payload["schema_json_path"] == "$.required"
        assert set(payload) == {"is_valid", "error_type", "error_detail", "json_path", "schema_json_path"}

    def test_failure_text_includes_error_type(self):
        messages = invoke(json_input='{"age": -1}', schema_input=PERSON_SCHEMA)
        assert text_of(messages).startswith("Validation failed [validation_failed]:")

    def test_empty_input_text(self):
        messages = invoke(json_input="", schema_input=PERSON_SCHEMA)
        assert json_of(messages)["error_type"] == "invalid_input"
        assert "invalid_input" in text_of(messages)


class TestSyntaxErrorMessages:
    def test_invalid_json(self):
        messages = invoke(json_input='{"a": }', schema_input=PERSON_SCHEMA)
        payload = json_of(messages)
        assert payload["error_type"] == "invalid_json"
        assert "line" in payload["error_detail"]

    def test_invalid_schema_json(self):
        messages = invoke(json_input='{"age": 1}', schema_input='{"a": }')
        assert json_of(messages)["error_type"] == "invalid_schema_json"


class TestOutputVariables:
    """Declared output_schema variables must be returned as VARIABLE messages,
    otherwise Dify fills them with None at runtime."""

    def test_success_variables(self):
        messages = invoke(json_input='{"age": 30}', schema_input=PERSON_SCHEMA)
        assert variables_of(messages) == {"is_valid": True}

    def test_failure_variables(self):
        messages = invoke(json_input='{"name": "Alice"}', schema_input=PERSON_SCHEMA)
        assert variables_of(messages) == {
            "is_valid": False,
            "error_type": "validation_failed",
            "error_detail": "'age' is a required property",
            "json_path": "$",
            "schema_json_path": "$.required",
        }

    def test_variables_match_json_payload(self):
        messages = invoke(json_input='{"age": -1}', schema_input=PERSON_SCHEMA)
        assert variables_of(messages) == json_of(messages)
