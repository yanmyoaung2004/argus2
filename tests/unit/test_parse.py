from __future__ import annotations

import json

import pytest

from argus.services.agents._parse import (
    _balanced_bracket_match,
    _strip_code_fences,
    extract_json_array,
    extract_json_object,
)


class TestStripCodeFences:
    def test_removes_triple_backtick_fences(self) -> None:
        text = "```\nhello\n```"
        assert _strip_code_fences(text) == "hello"

    def test_removes_json_fences(self) -> None:
        text = "```json\n{\"key\": \"value\"}\n```"
        assert _strip_code_fences(text) == "{\"key\": \"value\"}"

    def test_no_fences_unchanged(self) -> None:
        text = "plain text"
        assert _strip_code_fences(text) == text

    def test_whitespace_only_fences(self) -> None:
        text = "  ```\ncontent\n  ```  "
        result = _strip_code_fences(text)
        assert "content" in result
        assert "```" not in result

    def test_empty_string(self) -> None:
        assert _strip_code_fences("") == ""


class TestBalancedBracketMatch:
    def test_simple_brackets(self) -> None:
        result = _balanced_bracket_match("[hello]", "[", "]")
        assert result == (0, 7)

    def test_nested_brackets(self) -> None:
        result = _balanced_bracket_match("[outer [inner]]", "[", "]")
        assert result == (0, 15)

    def test_no_opening_bracket(self) -> None:
        result = _balanced_bracket_match("no brackets", "[", "]")
        assert result is None

    def test_unclosed_bracket(self) -> None:
        result = _balanced_bracket_match("[unclosed", "[", "]")
        assert result is None

    def test_curly_braces(self) -> None:
        text = '{"a": 1, "b": [1, 2]}'
        result = _balanced_bracket_match(text, "{", "}")
        assert result is not None
        assert result[0] == 0
        assert result[1] == len(text)

    def test_empty_brackets(self) -> None:
        result = _balanced_bracket_match("[]", "[", "]")
        assert result == (0, 2)


class TestExtractJsonArray:
    def test_plain_array(self) -> None:
        result = extract_json_array('[{"name": "test"}]')
        assert result == [{"name": "test"}]

    def test_array_with_code_fences(self) -> None:
        text = "```json\n[{\"name\": \"test\"}]\n```"
        result = extract_json_array(text)
        assert result == [{"name": "test"}]

    def test_array_with_extra_text(self) -> None:
        text = 'Here is the result:\n```\n[{"key": "value"}]\n```\nEnd.'
        result = extract_json_array(text)
        assert result == [{"key": "value"}]

    def test_multiple_items(self) -> None:
        data = [{"a": 1}, {"b": 2}, {"c": 3}]
        result = extract_json_array(json.dumps(data))
        assert result == data

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            extract_json_array("[not valid")

    def test_raises_on_empty_string(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            extract_json_array("")


class TestExtractJsonObject:
    def test_plain_object(self) -> None:
        result = extract_json_object('{"name": "test"}')
        assert result == {"name": "test"}

    def test_object_with_code_fences(self) -> None:
        text = "```json\n{\"key\": \"value\"}\n```"
        result = extract_json_object(text)
        assert result == {"key": "value"}

    def test_object_with_extra_text(self) -> None:
        text = 'Result:\n```\n{"a": 1, "b": 2}\n```\nDone.'
        result = extract_json_object(text)
        assert result == {"a": 1, "b": 2}

    def test_nested_object(self) -> None:
        data = {"outer": {"inner": [1, 2, 3]}}
        result = extract_json_object(json.dumps(data))
        assert result == data

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            extract_json_object("{bad json}")
