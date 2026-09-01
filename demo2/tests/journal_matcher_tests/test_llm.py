import pytest

from journal_matcher.llm import HeuristicJSONModel, parse_json_response
from journal_matcher.prompts import journal_match_prompt
from journal_matcher.schemas import ArticleProfile, MSCClassification


def test_parse_json_response_accepts_fences_and_prefix_text():
    assert parse_json_response("```json\n{\"ok\": true}\n```") == {"ok": True}
    assert parse_json_response("Here is the result: [1, 2]") == [1, 2]


def test_parse_json_response_rejects_non_json():
    with pytest.raises(ValueError):
        parse_json_response("not JSON")


def test_offline_recommender_uses_article_and_journal_metadata():
    profile = ArticleProfile(
        broad_fields=[MSCClassification("05", "Combinatorics")],
        primary_msc=MSCClassification("05C35", "Extremal problems in graph theory"),
        methods=["extremal graph theory"],
        contribution_type="improvement of a bound",
    )
    candidates = [
        {"journal_id": "geometry", "name": "Journal of Geometry", "tier": "subfield", "matching_codes": ["05C"], "representative_articles": []},
        {"journal_id": "graphs", "name": "Graphs and Combinatorics", "tier": "broad-field", "matching_codes": ["05"], "representative_articles": []},
    ]

    value = HeuristicJSONModel().complete_json(journal_match_prompt(profile, candidates, []))

    assert value["recommendations"][0]["journal_id"] == "graphs"
    assert "topology/symplectic" not in str(value).lower()
