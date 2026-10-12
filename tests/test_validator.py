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


class TestToolMessages:
    def test_success_emits_text_then_json(self):
        messages = invoke(json_input='{"age": 30}', schema_input=PERSON_SCHEMA)
        assert len(messages) == 2
        assert messages[0].type == InvokeMessage.MessageType.TEXT
        assert messages[1].type == InvokeMessage.MessageType.JSON
        assert text_of(messages) == "Validation passed."
        assert json_of(messages) == {
            "is_valid": True,
            "message": "Validation passed.",
        }

    def test_failure_payload_has_all_fields(self):
        messages = invoke(json_input='{"name": "Alice"}', schema_input=PERSON_SCHEMA)
        payload = json_of(messages)
        assert payload["is_valid"] is False
        assert payload["error_type"] == "validation_failed"
        assert payload["error"] == "'age' is a required property"
        assert payload["path"] == []
        assert payload["schema_path"] == ["required"]
        assert set(payload) == {"is_valid", "error_type", "error", "path", "schema_path"}

    def test_failure_text_includes_error_type(self):
        messages = invoke(json_input='{"age": -1}', schema_input=PERSON_SCHEMA)
        assert text_of(messages).startswith("Validation failed [validation_failed]:")

    def test_empty_input_text(self):
        messages = invoke(json_input="", schema_input=PERSON_SCHEMA)
        assert json_of(messages)["error_type"] == "invalid_input"
        assert "invalid_input" in text_of(messages)


class TestStrictModeParameter:
    @pytest.mark.parametrize(
        "value",
        ["true", "TRUE", " True ", True, 1, 1.0],
    )
    def test_truthy_values_enable_strict_mode(self, value):
        schema = json.dumps({"type": "object", "properties": {"a": {"type": "string"}}})
        messages = invoke(
            json_input='{"a": "x", "b": 1}', schema_input=schema, strict_mode=value
        )
        assert json_of(messages)["error_type"] == "validation_failed"

    @pytest.mark.parametrize("value", ["false", "off", False, 0, None, "nope"])
    def test_other_values_keep_strict_mode_off(self, value):
        schema = json.dumps({"type": "object", "properties": {"a": {"type": "string"}}})
        messages = invoke(
            json_input='{"a": "x", "b": 1}', schema_input=schema, strict_mode=value
        )
        assert json_of(messages)["is_valid"] is True

    def test_strict_mode_parameter_absent(self):
        schema = json.dumps({"type": "object", "properties": {"a": {"type": "string"}}})
        messages = invoke(json_input='{"a": "x", "b": 1}', schema_input=schema)
        assert json_of(messages)["is_valid"] is True


class TestSyntaxErrorMessages:
    def test_invalid_json(self):
        messages = invoke(json_input='{"a": }', schema_input=PERSON_SCHEMA)
        payload = json_of(messages)
        assert payload["error_type"] == "invalid_json"
        assert "line" in payload["error"]

    def test_invalid_schema_json(self):
        messages = invoke(json_input='{"age": 1}', schema_input='{"a": }')
        assert json_of(messages)["error_type"] == "invalid_schema_json"
