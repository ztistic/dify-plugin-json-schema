"""Unit tests for the pure validation helpers."""

import json

import pytest

from utils.schema_utils import (
    apply_strict_mode,
    format_path,
    format_summary,
    resolve_draft,
    validate_json_input,
)

PERSON_SCHEMA = json.dumps(
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["name", "age"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer", "minimum": 0},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }
)

PERSON_JSON = json.dumps({"name": "Alice", "age": 30, "tags": ["admin"]})


def run(json_input, schema_input, strict_mode=False):
    return validate_json_input(json_input, schema_input, strict_mode=strict_mode)


class TestValidationSuccess:
    def test_simple_object(self):
        assert run(PERSON_JSON, PERSON_SCHEMA) == {
            "is_valid": True,
            "message": "Validation passed.",
        }

    def test_nested_object_and_array(self):
        schema = json.dumps(
            {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "object",
                        "required": ["id"],
                        "properties": {"id": {"type": "integer"}},
                    },
                    "scores": {"type": "array", "items": {"type": "number"}},
                },
            }
        )
        data = json.dumps({"user": {"id": 7}, "scores": [1.5, 2.5]})
        assert run(data, schema)["is_valid"] is True

    def test_root_array_instance(self):
        schema = json.dumps({"type": "array", "items": {"type": "string"}})
        assert run(json.dumps(["a", "b"]), schema)["is_valid"] is True

    def test_non_string_input_is_stringified(self):
        result = run({"name": "Alice", "age": 30}, PERSON_SCHEMA)
        assert result["is_valid"] is True

    def test_boolean_true_schema_passes(self):
        assert run('{"a": 1}', "true")["is_valid"] is True


class TestValidationFailure:
    def test_type_mismatch_reports_paths(self):
        result = run(json.dumps({"name": "Alice", "age": "thirty"}), PERSON_SCHEMA)
        assert result["is_valid"] is False
        assert result["error_type"] == "validation_failed"
        assert "is not of type" in result["error"]
        assert result["path"] == ["age"]
        assert result["schema_path"] == ["properties", "age", "type"]

    def test_missing_required_property(self):
        result = run(json.dumps({"name": "Alice"}), PERSON_SCHEMA)
        assert result["error_type"] == "validation_failed"
        assert result["error"] == "'age' is a required property"
        assert result["schema_path"] == ["required"]

    def test_value_below_minimum(self):
        result = run(json.dumps({"name": "Alice", "age": -1}), PERSON_SCHEMA)
        assert result["error_type"] == "validation_failed"
        assert result["path"] == ["age"]
        assert result["schema_path"] == ["properties", "age", "minimum"]

    def test_nested_path_is_reported_as_list(self):
        schema = json.dumps(
            {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {"name": {"type": "string"}},
                    }
                },
            }
        )
        result = run(json.dumps({"user": {}}), schema)
        assert result["path"] == ["user"]
        assert result["schema_path"] == ["properties", "user", "required"]

    def test_array_index_appears_in_path(self):
        schema = json.dumps(
            {
                "type": "object",
                "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
            }
        )
        result = run(json.dumps({"tags": ["ok", 3]}), schema)
        assert result["path"] == ["tags", 1]

    def test_boolean_false_schema_fails(self):
        result = run('{"a": 1}', "false")
        assert result["error_type"] == "validation_failed"


class TestInputErrors:
    def test_empty_json_input(self):
        result = run("", PERSON_SCHEMA)
        assert result["error_type"] == "invalid_input"
        assert result["error"] == "json_input is empty"

    def test_blank_json_input(self):
        assert run("   ", PERSON_SCHEMA)["error_type"] == "invalid_input"

    def test_empty_schema_input(self):
        result = run(PERSON_JSON, "")
        assert result["error_type"] == "invalid_input"
        assert result["error"] == "schema_input is empty"

    def test_missing_parameters(self):
        assert run(None, None)["error_type"] == "invalid_input"

    def test_json_input_takes_precedence_over_schema(self):
        assert run("", "")["error"] == "json_input is empty"


class TestJsonSyntaxErrors:
    def test_invalid_json_reports_position(self):
        result = run('{"name": "Alice",}', PERSON_SCHEMA)
        assert result["is_valid"] is False
        assert result["error_type"] == "invalid_json"
        assert result["error"].startswith("Invalid JSON input:")
        assert "at line" in result["error"] and "column" in result["error"]

    def test_truncated_json(self):
        assert run('{"a": ', PERSON_SCHEMA)["error_type"] == "invalid_json"

    def test_plain_text_input(self):
        assert run("not json at all", PERSON_SCHEMA)["error_type"] == "invalid_json"


class TestSchemaSyntaxErrors:
    def test_invalid_schema_json_reports_position(self):
        result = run(PERSON_JSON, '{"type": "object",}')
        assert result["error_type"] == "invalid_schema_json"
        assert result["error"].startswith("Invalid JSON Schema:")

    def test_schema_json_error_takes_precedence_over_data_error(self):
        # Both strings are broken: the data stays valid enough to parse first,
        # so the schema failure wins.
        result = run('{"a": 1}', '{"type":')
        assert result["error_type"] == "invalid_schema_json"


class TestSchemaStructureErrors:
    def test_non_numeric_type(self):
        result = run('{"a": 1}', '{"type": "nope"}')
        assert result["error_type"] == "schema_error"
        assert result["error"].startswith("Schema itself is invalid:")
        assert result["schema_path"]

    def test_wrong_keyword_type(self):
        result = run('{"a": 1}', '{"required": "name"}')
        assert result["error_type"] == "schema_error"

    def test_schema_is_not_an_object(self):
        result = run('{"a": 1}', '"just-a-string"')
        assert result["error_type"] == "schema_error"
        assert "object or a boolean" in result["error"]

    def test_non_string_dollar_schema(self):
        result = run('{"a": 1}', '{"$schema": 42, "type": "object"}')
        assert result["error_type"] == "schema_error"


class TestRefResolution:
    def test_valid_internal_ref(self):
        schema = json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {"pet": {"$ref": "#/$defs/Pet"}},
                "$defs": {
                    "Pet": {"type": "object", "required": ["kind"]},
                },
            }
        )
        assert run(json.dumps({"pet": {"kind": "cat"}}), schema)["is_valid"] is True

    def test_missing_internal_pointer(self):
        schema = json.dumps({"$ref": "#/$defs/Missing"})
        result = run('{"a": 1}', schema)
        assert result["error_type"] == "ref_resolution_error"
        assert result["error"].startswith("Schema $ref resolution failed:")

    def test_external_ref_is_not_fetched(self):
        schema = json.dumps({"$ref": "http://example.com/schemas/foo.json"})
        result = run('{"a": 1}', schema)
        assert result["error_type"] == "ref_resolution_error"

    @pytest.mark.parametrize(
        "ref",
        [
            "#/$defs/Missing",
            "#/definitions/Missing",
            "#/$defs/",
            "#/type",
            "other.json",
            "urn:example:foo",
        ],
    )
    def test_every_unresolvable_ref_shape_is_classified(self, ref):
        # All of these surface as referencing's Unresolvable, whatever the draft.
        result = run('{"a": 1}', json.dumps({"$ref": ref}))
        assert result["error_type"] == "ref_resolution_error"

    def test_self_referential_root_ref_is_reported_not_hung(self):
        # {"$ref": "#"} is a schema that validates itself forever; it must be
        # reported, not loop.
        result = run('{"a": 1}', '{"$ref": "#"}')
        assert result["is_valid"] is False
        assert result["error_type"] == "internal_error"
        assert "circular $ref" in result["error"]


class TestDraftSupport:
    @pytest.mark.parametrize(
        "declared",
        [
            "https://json-schema.org/draft/2020-12/schema",
            "https://json-schema.org/draft/2019-09/schema",
            "http://json-schema.org/draft-07/schema#",
            "http://json-schema.org/draft-06/schema#",
            "http://json-schema.org/draft-04/schema#",
        ],
    )
    def test_supported_drafts_are_honoured(self, declared):
        schema = json.dumps(
            {"$schema": declared, "type": "object", "properties": {"a": {"type": "string"}}}
        )
        assert run('{"a": "x"}', schema)["is_valid"] is True
        failed = run('{"a": 1}', schema)
        assert failed["error_type"] == "validation_failed"

    def test_missing_declaration_uses_default_draft(self):
        # exclusiveMinimum is numeric in draft 4/6, boolean from draft-07 on.
        schema = json.dumps({"type": "object", "exclusiveMinimum": 0})
        result = run('{}', schema)
        assert result["is_valid"] is True

    def test_draft_keywords_are_enforced_per_draft(self):
        # ``const`` was introduced with draft-06, so draft-04 ignores it while
        # draft-07 enforces it. Proves the declared draft is really selected.
        schema = json.dumps(
            {
                "type": "object",
                "properties": {"a": {"const": 5}},
            }
        )
        draft_four = json.dumps({**json.loads(schema), "$schema": "http://json-schema.org/draft-04/schema#"})
        draft_seven = json.dumps({**json.loads(schema), "$schema": "http://json-schema.org/draft-07/schema#"})

        assert run('{"a": 7}', draft_four)["is_valid"] is True
        failed = run('{"a": 7}', draft_seven)
        assert failed["error_type"] == "validation_failed"
        assert failed["path"] == ["a"]

    def test_generic_pointer_defaults_to_latest(self):
        schema = json.dumps({"$schema": "http://json-schema.org/schema#", "type": "object"})
        assert run('{"a": 1}', schema)["is_valid"] is True

    @pytest.mark.parametrize(
        "declared",
        [
            "http://json-schema.org/draft-03/schema#",
            "https://json-schema.org/draft/2030-01/schema",
            "http://example.com/draft-99/schema#",
        ],
    )
    def test_unsupported_draft(self, declared):
        schema = json.dumps({"$schema": declared, "type": "object"})
        result = run('{"a": 1}', schema)
        assert result["error_type"] == "unsupported_draft"
        assert declared in result["error"]
        assert "Supported drafts:" in result["error"]

    def test_resolve_draft_returns_class_for_known(self):
        validator_cls, error = resolve_draft({"$schema": "http://json-schema.org/draft-07/schema#"})
        assert validator_cls is not None
        assert error is None


class TestStrictMode:
    def test_extra_property_rejected(self):
        result = run(
            json.dumps({"name": "Alice", "age": 30, "extra": 1}),
            PERSON_SCHEMA,
            strict_mode=True,
        )
        assert result["error_type"] == "validation_failed"
        assert "Additional properties are not allowed" in result["error"]
        assert "'extra'" in result["error"]
        assert result["schema_path"] == ["additionalProperties"]

    def test_extra_property_allowed_when_disabled(self):
        result = run(
            json.dumps({"name": "Alice", "age": 30, "extra": 1}),
            PERSON_SCHEMA,
            strict_mode=False,
        )
        assert result["is_valid"] is True

    def test_original_schema_is_not_mutated(self):
        schema = {"type": "object", "properties": {"a": {"type": "object"}}}
        strict = apply_strict_mode(schema)
        assert strict["additionalProperties"] is False
        assert "additionalProperties" not in schema

    def test_nested_objects_are_closed_recursively(self):
        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }
            },
        }
        strict = apply_strict_mode(schema)
        assert strict["properties"]["user"]["additionalProperties"] is False

    def test_defs_are_closed_recursively(self):
        schema = {
            "type": "object",
            "properties": {"pet": {"$ref": "#/$defs/Pet"}},
            "$defs": {"Pet": {"type": "object", "properties": {"kind": {"type": "string"}}}},
        }
        strict = apply_strict_mode(schema)
        assert strict["$defs"]["Pet"]["additionalProperties"] is False

    def test_items_and_composition_keywords_are_closed(self):
        schema = {
            "type": "array",
            "items": {"type": "object", "properties": {"a": {"type": "string"}}},
        }
        assert apply_strict_mode(schema)["items"]["additionalProperties"] is False

        composed = {"allOf": [{"type": "object", "properties": {"a": {}}}]}
        assert apply_strict_mode(composed)["allOf"][0]["additionalProperties"] is False

    def test_nullable_object_type_is_closed(self):
        schema = {"type": ["object", "null"], "properties": {"a": {"type": "string"}}}
        assert apply_strict_mode(schema)["additionalProperties"] is False

    def test_nullable_non_object_type_is_not_closed(self):
        schema = {"type": ["string", "null"]}
        assert "additionalProperties" not in apply_strict_mode(schema)

    def test_nullable_object_validates_in_strict_mode(self):
        schema = json.dumps(
            {"type": ["object", "null"], "properties": {"a": {"type": "string"}}}
        )
        assert run("null", schema, strict_mode=True)["is_valid"] is True
        result = run('{"a": "x", "b": 1}', schema, strict_mode=True)
        assert result["error_type"] == "validation_failed"

    def test_object_without_type_but_with_properties_is_closed(self):
        schema = {"properties": {"a": {"type": "string"}}}
        assert apply_strict_mode(schema)["additionalProperties"] is False

    def test_existing_additional_properties_is_preserved(self):
        schema = {"type": "object", "additionalProperties": {"type": "string"}}
        assert apply_strict_mode(schema)["additionalProperties"] == {"type": "string"}

    def test_boolean_subschema_is_preserved(self):
        assert apply_strict_mode(True) is True
        assert apply_strict_mode({"additionalProperties": True}) == {
            "additionalProperties": True
        }

    def test_draft7_dependencies_map_is_handled(self):
        schema = {"dependencies": {"a": ["b"], "c": {"type": "object"}}}
        strict = apply_strict_mode(schema)
        assert strict["dependencies"]["a"] == ["b"]
        assert strict["dependencies"]["c"]["additionalProperties"] is False


class TestNeverRaises:
    @pytest.mark.parametrize(
        "json_input,schema_input",
        [
            ("", ""),
            (None, None),
            ("{", "}"),
            ("[1,2", "[1"),
            (12345, True),
            ("[1, 2, 3]", 42),
            ("null", '{"$schema": "http://json-schema.org/draft-03/schema#"}'),
            ('{"a": 1}', '{"type": {"nested": [1, 2]}}'),
            ('{"a": 1}', '{"$ref": "ftp://nope/x"}'),
            ([{"a": 1}], {"type": "array"}),
        ],
    )
    def test_no_uncaught_exception(self, json_input, schema_input):
        result = run(json_input, schema_input)
        assert isinstance(result, dict)
        assert "is_valid" in result

    def test_idempotent(self):
        first = run('{"name": "Alice"}', PERSON_SCHEMA)
        second = run('{"name": "Alice"}', PERSON_SCHEMA)
        assert first == second


class TestDeepNesting:
    """Nothing may raise, and realistic depths must never be rejected."""

    @staticmethod
    def _nested_schema_text(depth: int) -> str:
        return (
            '{"type":"object","properties":{"n":' * depth
            + '{"type":"object"}'
            + "}" * (2 * depth)
        )

    @staticmethod
    def _nested_data_text(depth: int) -> str:
        return '{"value":1,"children":[' * depth + '{"value":1}' + "]}" * depth

    RECURSIVE_SCHEMA = json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "node": {
                    "type": "object",
                    "required": ["value"],
                    "properties": {
                        "value": {"type": "integer"},
                        "children": {"type": "array", "items": {"$ref": "#/$defs/node"}},
                    },
                }
            },
            "$ref": "#/$defs/node",
        }
    )

    @pytest.mark.parametrize("depth", [1, 5, 20, 50, 80])
    def test_realistic_depths_validate_normally(self, depth):
        # Realistic schemas sit at 3-30 levels; the default recursion limit
        # covers ~95, so nothing in this range may be rejected.
        result = run('{"n": {"n": {}}}', self._nested_schema_text(depth))
        assert result["is_valid"] is True

    def test_recursive_schema_over_deep_data_validates(self):
        # Data follows a recursive schema; depth is bounded by both.
        assert run(self._nested_data_text(50), self.RECURSIVE_SCHEMA)["is_valid"] is True

    def test_recursive_schema_in_strict_mode(self):
        assert (
            run(self._nested_data_text(50), self.RECURSIVE_SCHEMA, strict_mode=True)[
                "is_valid"
            ]
            is True
        )

    def test_deeply_nested_json_is_reported_not_raised(self):
        result = run("[" * 20000 + "]" * 20000, '{"type": "array"}')
        assert result["error_type"] == "invalid_json"
        assert "nested too deeply" in result["error"]

    def test_deeply_nested_schema_text_is_reported_not_raised(self):
        result = run('{"n": {}}', self._nested_schema_text(2000))
        assert result["error_type"] == "invalid_schema_json"
        assert "nested too deeply" in result["error"]

    def test_schema_past_the_default_limit_is_reported_not_raised(self):
        # ~95 levels is where the default limit runs out; the schema is the
        # thing to change, so this is a schema_error rather than a crash.
        result = run('{"n": {}}', self._nested_schema_text(300))
        assert result["is_valid"] is False
        assert result["error_type"] == "schema_error"
        assert "nested too deeply" in result["error"]

    def test_data_past_the_default_limit_is_reported_not_raised(self):
        result = run(self._nested_data_text(400), self.RECURSIVE_SCHEMA)
        assert result["is_valid"] is False
        assert result["error_type"] == "internal_error"
        assert "nested too deeply" in result["error"]


class TestDraftUriScoping:
    def test_bare_draft_shorthand_is_accepted(self):
        schema = json.dumps({"$schema": "draft-07", "type": "object"})
        assert run('{"a": 1}', schema)["is_valid"] is True

    def test_foreign_host_mentioning_a_draft_is_rejected(self):
        schema = json.dumps(
            {"$schema": "http://example.com/x/draft-07/y", "type": "object"}
        )
        result = run('{"a": 1}', schema)
        assert result["error_type"] == "unsupported_draft"

    def test_www_json_schema_org_is_accepted(self):
        schema = json.dumps(
            {"$schema": "https://www.json-schema.org/draft/2020-12/schema", "type": "object"}
        )
        assert run('{"a": 1}', schema)["is_valid"] is True


class TestInputRepresentability:
    def test_unrepresentable_input_is_reported_clearly(self):
        result = run(object(), '{"type": "object"}')
        assert result["error_type"] == "invalid_input"
        assert "cannot be converted to a JSON string" in result["error"]

    def test_unrepresentable_schema_is_reported_clearly(self):
        result = run('{"a": 1}', object())
        assert result["error_type"] == "invalid_input"
        assert "schema_input cannot be converted" in result["error"]


class TestNoInputPreprocessing:
    """The plugin validates; it does not prepare input.

    A Markdown-fenced string is not JSON, so it must be reported as
    ``invalid_json`` rather than silently unwrapped. Unwrapping would make
    ``is_valid`` describe a value the downstream nodes never receive, since the
    tool does not emit the parsed JSON -- the caller's variable still holds the
    fenced text.
    """

    @pytest.mark.parametrize(
        "fenced",
        [
            '```json\n{"name": "Alice", "age": 30}\n```',
            '```\n{"name": "Alice", "age": 30}\n```',
            'Here is the result:\n```json\n{"name": "Alice", "age": 30}\n```',
            '```json\n{"name": "Alice", "age": 30}',
            '```json\n{"name": "Alice", "age": 30}\n```\nHope this helps',
        ],
    )
    def test_fenced_json_is_rejected_as_invalid_json(self, fenced):
        result = run(fenced, PERSON_SCHEMA)
        assert result["is_valid"] is False
        assert result["error_type"] == "invalid_json"
        assert result["error"].startswith("Invalid JSON input:")

    def test_fenced_json_with_valid_body_still_rejected(self):
        # The body would pass validation if it were extracted; the point is
        # that we must not extract it.
        fenced = '```json\n{"name": "Alice", "age": 30}\n```'
        result = run(fenced, PERSON_SCHEMA)
        assert result["error_type"] == "invalid_json"

    def test_broken_json_inside_fence_is_invalid_json(self):
        fenced = '```json\n{"name": "Alice",}\n```'
        assert run(fenced, PERSON_SCHEMA)["error_type"] == "invalid_json"

    def test_clean_json_is_unaffected(self):
        assert run('{"name": "Alice", "age": 30}', PERSON_SCHEMA)["is_valid"] is True


class TestFormatting:
    def test_format_path_root(self):
        assert format_path([]) == "$ (root)"

    def test_format_path_mixed(self):
        assert format_path(["users", 0, "name"]) == "$.users[0].name"

    def test_success_summary(self):
        assert format_summary({"is_valid": True, "message": "Validation passed."}) == (
            "Validation passed."
        )

    def test_failure_summary_contains_type_and_paths(self):
        summary = format_summary(
            {
                "is_valid": False,
                "error_type": "validation_failed",
                "error": "'age' is a required property",
                "path": ["user"],
                "schema_path": ["properties", "user", "required"],
            }
        )
        assert "validation_failed" in summary
        assert "'age' is a required property" in summary
        assert "$.user" in summary
        assert "$.properties.user.required" in summary
