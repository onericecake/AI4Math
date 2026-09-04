from pathlib import Path

from journal_matcher.catalog import JournalCatalog
from journal_matcher.latex_extract import extract_text
from journal_matcher.msc import MSCTaxonomy
from journal_matcher.pipeline import JournalMatcher
from journal_matcher.llm import HeuristicJSONModel
from journal_matcher.schemas import ArticleProfile, JournalFieldProfile


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


def test_rank_candidates_prefers_matching_technical_level(tmp_path):
    with JournalCatalog(tmp_path / "catalog.sqlite") as catalog:
        for journal_id, name in (("standard", "General Mathematics"), ("advanced", "Advanced Graph Theory"), ("specialized", "Specialized Graph Notes")):
            catalog.upsert_journal({"journal_id": journal_id, "name": name})
            catalog.upsert_article({"article_id": journal_id + "-a", "journal_id": journal_id, "title": name, "abstract": "Extremal graph theory", "year": 2025, "msc_codes": ["05C35"]})
        catalog.rebuild_statistics()
        matcher = JournalMatcher(HeuristicJSONModel(), MSCTaxonomy.from_json("data/msc2020.sample.json"), catalog)
        profile = ArticleProfile(technical_depth="advanced", audience_breadth="subfield", keywords=["extremal", "graph"])
        candidates = catalog.find_candidates(["05C35"])
        fields = [
            JournalFieldProfile(journal_id="standard", msc_prefix="05C35", technical_depth_range=["standard"], breadth="field", confidence="high"),
            JournalFieldProfile(journal_id="advanced", msc_prefix="05C35", technical_depth_range=["advanced"], breadth="subfield", confidence="high"),
            JournalFieldProfile(journal_id="specialized", msc_prefix="05C35", technical_depth_range=["highly specialized"], breadth="narrow", confidence="high"),
        ]
        ranked = matcher.rank_candidates(profile, candidates, fields)
        assert ranked[0].journal_id == "advanced"
        assert ranked[0].level_distance == 0


def test_whole_paper_path_does_not_require_a_theorem():
    manuscript = extract_text(r"\title{A Prose Article}\section{Introduction}We study graph bounds.")
    matcher = JournalMatcher(HeuristicJSONModel(), MSCTaxonomy.from_json("data/msc2020.sample.json"), JournalCatalog(":memory:"))
    try:
        assert matcher.propose_central_results(manuscript)["candidates"] == []
    finally:
        matcher.catalog.close()
