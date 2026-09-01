from pathlib import Path

from journal_matcher.catalog import JournalCatalog
from journal_matcher.latex_extract import extract_text
from journal_matcher.llm import HeuristicJSONModel
from journal_matcher.msc import MSCTaxonomy
from journal_matcher.pipeline import JournalMatcher


class FakeModel:
    def __init__(self):
        self.prompts = []

    def complete_json(self, prompt):
        self.prompts.append(prompt)
        if "Identify the central theorem" in prompt:
            return {"candidates": [{"result_id": "thm:main", "role": "primary result", "confidence": "high"}]}
        if "Choose the most appropriate broad MSC" in prompt:
            return {"broad_fields": [{"code": "05", "name": "Combinatorics", "role": "primary"}]}
        if "classifying an unpublished mathematics article" in prompt:
            return {"primary_msc": {"code": "05C35", "name": "Extremal graph theory"}, "broad_fields": [{"code": "05", "name": "Combinatorics", "role": "primary"}], "methods": ["probabilistic method"], "contribution_type": "improvement of a bound", "technical_depth": "advanced", "audience_breadth": "subfield"}
        if "Create a field-local profile" in prompt:
            return {"typical_contributions": ["specialized theorems"], "technical_depth_range": ["advanced"], "typical_audience": "specialists", "breadth": "subfield", "representative_article_ids": ["a1"]}
        return {"recommendations": [{"role": "closest field-and-level match", "journal_id": "j1", "journal_name": "ignored", "fit": "strong match", "level_fit": "closely aligned", "reasons": ["same MSC area"], "representative_article_ids": ["a1"]}]}


class EmptyDetailedProfileModel:
    def complete_json(self, prompt):
        if "Choose the most appropriate broad MSC" in prompt:
            return {"broad_fields": [{"code": "05", "name": "Combinatorics", "role": "primary"}]}
        return {"broad_fields": [], "primary_msc": None, "secondary_msc": []}


def test_pipeline_confirms_results_and_matches_field_local_journal(tmp_path):
    with JournalCatalog(tmp_path / "catalog.sqlite") as catalog:
        catalog.upsert_journal({"journal_id": "j1", "name": "Journal One", "scope_summary": "Combinatorics"})
        catalog.upsert_article({"article_id": "a1", "journal_id": "j1", "title": "Graph theorem", "abstract": "Extremal graph theory", "year": 2025, "msc_codes": ["05C35"]})
        catalog.rebuild_statistics()
        taxonomy = MSCTaxonomy.from_json("data/msc2020.sample.json")
        matcher = JournalMatcher(FakeModel(), taxonomy, catalog)
        manuscript = extract_text(Path("examples/manuscript.tex").read_text(encoding="utf-8"))
        central = matcher.propose_central_results(manuscript)
        ids = [central["candidates"][0]["result_id"]]
        broad = matcher.classify_broad(manuscript, ids)
        profile = matcher.build_profile(manuscript, ids, broad)
        candidates = matcher.candidates(profile)
        field_profiles = matcher.profile_journals(profile, candidates)
        report = matcher.match(profile, candidates, field_profiles, manuscript.theorems[0].statement)
        assert report.recommendations[0].journal_id == "j1"
        assert profile.primary_msc.code == "05C35"


def test_pipeline_preserves_valid_broad_classification_when_detail_is_empty(tmp_path):
    with JournalCatalog(tmp_path / "catalog.sqlite") as catalog:
        taxonomy = MSCTaxonomy.from_json("data/msc2020.sample.json")
        matcher = JournalMatcher(EmptyDetailedProfileModel(), taxonomy, catalog)
        manuscript = extract_text(Path("examples/manuscript.tex").read_text(encoding="utf-8"))
        broad = matcher.classify_broad(manuscript, ["thm:main"])
        profile = matcher.build_profile(manuscript, ["thm:main"], broad)

        assert [item.code for item in profile.broad_fields] == ["05"]


def test_offline_graph_example_produces_field_neutral_recommendations(tmp_path):
    with JournalCatalog(tmp_path / "catalog.sqlite") as catalog:
        catalog.upsert_journal({"journal_id": "j1", "name": "Journal of Combinatorics", "scope_summary": "Combinatorics"})
        catalog.upsert_article({"article_id": "a1", "journal_id": "j1", "title": "Graph bounds", "abstract": "Extremal graph theory", "year": 2025, "msc_codes": ["05C35"]})
        catalog.rebuild_statistics()
        taxonomy = MSCTaxonomy.from_json("data/msc2020.sample.json")
        matcher = JournalMatcher(HeuristicJSONModel(), taxonomy, catalog)
        manuscript = extract_text(Path("examples/manuscript.tex").read_text(encoding="utf-8"))
        central = matcher.propose_central_results(manuscript)
        central_ids = [item["result_id"] for item in central["candidates"]]
        central_text = manuscript.theorems[0].statement
        broad = matcher.classify_broad(manuscript, central_ids, central_text)
        profile = matcher.build_profile(manuscript, central_ids, broad, central_text)
        candidates = matcher.candidates(profile)
        field_profiles = matcher.profile_journals(profile, candidates)
        report = matcher.match(profile, candidates, field_profiles, central_text)

        assert [item.code for item in profile.broad_fields] == ["05"]
        assert profile.primary_msc.code == "05C35"
        assert [item.journal_id for item in candidates] == ["j1"]
        assert [item.journal_id for item in report.recommendations] == ["j1"]
        report_text = str(report.to_dict()).lower()
        assert "topology" not in report_text
        assert "legendrian" not in report_text
