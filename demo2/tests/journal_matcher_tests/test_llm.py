import pytest

from journal_matcher.llm import parse_json_response


def test_parse_json_response_accepts_fences_and_prefix_text():
    assert parse_json_response("```json\n{\"ok\": true}\n```") == {"ok": True}
    assert parse_json_response("Here is the result: [1, 2]") == [1, 2]


def test_parse_json_response_rejects_non_json():
    with pytest.raises(ValueError):
        parse_json_response("not JSON")
