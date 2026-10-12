"""Unit tests for the deterministic JSON extractor."""

import pytest

from utils.extraction import extract_json
from utils.failures import ValidationFailure


class TestWholeInput:
    def test_object(self):
        assert extract_json('{"a": 1}') == '{"a": 1}'

    def test_surrounding_whitespace(self):
        assert extract_json('  {"a": 1}\n') == '{"a": 1}'

    def test_array(self):
        assert extract_json("[1, 2]") == "[1, 2]"

    def test_primitive(self):
        assert extract_json("42") == "42"


class TestFence:
    def test_json_fence_with_surrounding_prose(self):
        text = 'Here you go:\n```json\n{"a": 1}\n```\nHope this helps.'
        assert extract_json(text) == '{"a": 1}'

    def test_untagged_fence(self):
        assert extract_json('```\n{"a": 1}\n```') == '{"a": 1}'

    def test_uppercase_language_tag(self):
        assert extract_json('```JSON\n{"a": 1}\n```') == '{"a": 1}'

    def test_first_parseable_fence_wins(self):
        text = '```json\nnot json\n```\nthen\n```json\n{"a": 1}\n```'
        assert extract_json(text) == '{"a": 1}'

    def test_verbatim_content_is_preserved(self):
        text = '```json\n{\n  "n": 1e3,\n  "s": "x } y"\n}\n```'
        extracted = extract_json(text)
        assert "1e3" in extracted
        assert '"x } y"' in extracted


class TestNoJsonFound:
    def test_prose_only(self):
        with pytest.raises(ValidationFailure) as excinfo:
            extract_json("The answer is 42, no JSON here.")
        assert excinfo.value.error_type == "no_json_found"

    def test_bare_json_in_prose_is_not_extracted(self):
        with pytest.raises(ValidationFailure) as excinfo:
            extract_json('The result is {"a": 1} as shown.')
        assert excinfo.value.error_type == "no_json_found"

    def test_other_language_fence_is_skipped(self):
        with pytest.raises(ValidationFailure) as excinfo:
            extract_json('```python\n{"a": 1}\n```')
        assert excinfo.value.error_type == "no_json_found"

    def test_unclosed_fence(self):
        with pytest.raises(ValidationFailure) as excinfo:
            extract_json('```json\n{"a": 1}')
        assert excinfo.value.error_type == "no_json_found"

    def test_unparseable_fence(self):
        with pytest.raises(ValidationFailure) as excinfo:
            extract_json('```json\n{"a": }\n```')
        assert excinfo.value.error_type == "no_json_found"


class TestInputErrors:
    def test_blank_input(self):
        with pytest.raises(ValidationFailure) as excinfo:
            extract_json("   \n  ")
        assert excinfo.value.error_type == "invalid_input"

    def test_deeply_nested_input_is_an_honest_error(self):
        with pytest.raises(ValidationFailure) as excinfo:
            extract_json("[" * 5000 + "]" * 5000)
        assert excinfo.value.error_type == "internal_error"
