import argparse
import json
from dataclasses import replace

import pytest

from journal_matcher.catalog import JournalCatalog
from journal_matcher.cli import _confirm_classification
from journal_matcher.latex_extract import extract_text
from journal_matcher.llm import HeuristicJSONModel
from journal_matcher.msc import MSCTaxonomy
from journal_matcher.pipeline import JournalMatcher
from journal_matcher.report import render_markdown
from journal_matcher.schemas import ArticleProfile, JournalCandidate, MSCClassification, RepresentativeArticle


@pytest.fixture
def catalog():
    with JournalCatalog(":memory:") as value:
        yield value


@pytest.fixture
def taxonomy():
    return MSCTaxonomy.from_json("data/msc2020.json")


def add_paper(catalog, journal_id, article_id, codes, **kwargs):
    catalog.upsert_article(dict(journal_id=journal_id, article_id=article_id,
                                title="A mathematical result", msc_codes=codes, **kwargs))


def test_broad_query_cannot_promote_a_broad_match_to_exact(catalog):
    for journal_id in ("broad", "exact"):
        catalog.upsert_journal({"journal_id": journal_id, "name": journal_id})
    catalog.set_stat("broad", "05", 10000)
    catalog.set_stat("exact", "05C35", 1)
    catalog.set_stat("exact", "05", 1)
    for codes in (["05C35", "05"], ["05", "05C35"]):
        results = catalog.find_candidates(codes, limit=1)
        assert results[0].journal_id == "exact"
        assert results[0].tier == "exact-subfield"
    assert all(item.tier == "broad-field" for item in catalog.find_candidates(["05"]))
    assert catalog.find_candidates(["05"], limit=0) == []


def test_each_paper_counts_once_per_parent_and_rebuild_updates_derived_stats(catalog):
    catalog.upsert_journal({"journal_id": "j", "name": "J"})
    add_paper(catalog, "j", "a", ["05C35", "05C80", "05D05"])
    add_paper(catalog, "j", "b", ["11A05"])
    catalog.rebuild_statistics()
    stats = {row["msc_prefix"]: row for row in catalog.connection.execute("SELECT * FROM journal_msc_stats")}
    assert stats["05"]["article_count"] == stats["05C"]["article_count"] == 1
    assert stats["05"]["share"] == 0.5
    add_paper(catalog, "j", "a", ["11A05"])
    catalog.rebuild_statistics()
    assert catalog.find_candidates(["05"]) == []
    assert catalog.find_candidates(["11A05"])[0].article_count == 2


def test_import_preserves_external_statistics_when_adding_article_samples(catalog, tmp_path):
    catalog.upsert_journal({"journal_id": "registry", "name": "Registry Journal"})
    catalog.set_stat("registry", "05", 1000, 0.4)
    source = tmp_path / "sample.json"
    source.write_text(json.dumps({"journals": [{"journal_id": "sample", "name": "Sample Journal"}],
                                  "articles": [{"journal_id": "sample", "article_id": "a", "title": "Result", "msc_codes": ["05C35"]}]}))
    catalog.import_json(source)
    assert {item.journal_id for item in catalog.find_candidates(["05"])} == {"registry", "sample"}
    row = catalog.connection.execute("SELECT article_count, share FROM journal_msc_stats WHERE journal_id='registry'").fetchone()
    assert tuple(row) == (1000, 0.4)


def test_retrieval_shortlist_ranks_before_volume_cutoff(catalog, taxonomy):
    for index in range(30):
        journal_id = "large-%02d" % index
        catalog.upsert_journal({"journal_id": journal_id, "name": journal_id, "scope_summary": "Unrelated topics"})
        catalog.set_stat(journal_id, "05C35", 500)
    catalog.upsert_journal({"journal_id": "small", "name": "Small specialist", "scope_summary": "Extremal graph bounds"})
    catalog.set_stat("small", "05C35", 2)
    matcher = JournalMatcher(HeuristicJSONModel(), taxonomy, catalog)
    profile = ArticleProfile(primary_msc=MSCClassification("05C35"), keywords=["extremal", "graph", "bounds"])
    assert matcher.candidates(profile, limit=3)[0].journal_id == "small"


def test_examples_use_the_prefix_of_the_selected_statistic(catalog):
    catalog.upsert_journal({"journal_id": "j", "name": "J"})
    add_paper(catalog, "j", "graph", ["05C35"])
    add_paper(catalog, "j", "number", ["11A05"])
    catalog.set_stat("j", "05C35", 2)
    catalog.set_stat("j", "11A05", 9)
    candidate = catalog.find_candidates(["05C35", "11A05"])[0]
    assert candidate.evidence_msc_prefix == "11A05"
    assert [item.article_id for item in candidate.representative_articles] == ["number"]


class RecordingModel:
    def __init__(self, model="test-model", match_response=None):
        self.model = model
        self.calls = []
        self.match_response = match_response

    def complete_json(self, prompt):
        self.calls.append(prompt)
        if "Create a field-local profile" in prompt:
            return {"technical_depth_range": ["standard"], "confidence": "high",
                    "representative_article_ids": ["a", "foreign-article", "a"]}
        return self.match_response


def evidence_candidate():
    return JournalCandidate("j", "Journal", "exact-subfield", evidence_msc_prefix="05C35",
                            representative_articles=[RepresentativeArticle("a", "Graph result", abstract="An extremal graph bound", source_url="https://example.org/paper")])


def test_cached_profile_changes_with_model_or_evidence(catalog, taxonomy):
    profile = ArticleProfile(primary_msc=MSCClassification("05C35"))
    candidate = evidence_candidate()
    model = RecordingModel()
    matcher = JournalMatcher(model, taxonomy, catalog)
    fields = matcher.profile_journals(profile, [candidate])
    assert fields[0].representative_article_ids == ["a"]
    matcher.profile_journals(profile, [candidate])
    assert len(model.calls) == 1
    changed = replace(candidate, scope_summary="Changed editorial scope")
    matcher.profile_journals(profile, [changed])
    assert len(model.calls) == 2
    model.model = "different-model"
    matcher.profile_journals(profile, [changed])
    assert len(model.calls) == 3
    # Switching to offline and back must not reuse heuristic profiles.
    JournalMatcher(HeuristicJSONModel(), taxonomy, catalog).profile_journals(profile, [changed])
    matcher.profile_journals(profile, [changed])
    assert len(model.calls) == 4


def test_recommendations_validate_citations_levels_and_include_sources(catalog, taxonomy):
    response = {"recommendations": [
        {"journal_id": "j", "fit": "strong match", "level_fit": "closely aligned", "representative_article_ids": ["a", "other-journal-article", "a"]},
        {"journal_id": "invented", "fit": "strong match"},
        {"journal_id": "j", "fit": "strong match"},
    ]}
    model = RecordingModel(match_response=response)
    matcher = JournalMatcher(model, taxonomy, catalog)
    profile = ArticleProfile(technical_depth="highly specialized", primary_msc=MSCClassification("05C35"))
    candidates = [evidence_candidate()]
    fields = matcher.profile_journals(profile, candidates)
    report = matcher.match(profile, candidates, fields)
    assert len(report.recommendations) == 1
    recommendation = report.recommendations[0]
    assert recommendation.representative_article_ids == ["a"]
    assert recommendation.level_fit == "technically different"
    assert recommendation.fit == "plausible match"
    assert round(sum(recommendation.score_components.values()), 4) == recommendation.match_score
    assert report.to_dict()["ranked_candidates"][0]["journal_id"] == "j"
    markdown = render_markdown(report)
    assert "Graph result" in markdown and "https://example.org/paper" in markdown
    assert "uncalibrated" in markdown


def test_no_citations_means_insufficient_information(catalog, taxonomy):
    model = RecordingModel(match_response={"recommendations": [{"journal_id": "j", "fit": "strong match",
                                                                 "representative_article_ids": ["fabricated"]}]})
    report = JournalMatcher(model, taxonomy, catalog).match(ArticleProfile(), [evidence_candidate()], [])
    assert report.recommendations[0].fit == "insufficient information"
    assert report.recommendations[0].representative_articles == []


def test_empty_candidates_do_not_call_model(catalog, taxonomy):
    model = RecordingModel()
    report = JournalMatcher(model, taxonomy, catalog).match(ArticleProfile(), [], [])
    assert report.recommendations == [] and not model.calls


def test_full_taxonomy_does_not_contaminate_offline_classification(catalog, taxonomy):
    matcher = JournalMatcher(HeuristicJSONModel(), taxonomy, catalog)
    manuscript = extract_text(r"\title{Extremal graph bounds}\begin{abstract}We improve bounds for graphs.\end{abstract}")
    broad = matcher.classify_broad(manuscript, [])
    assert [item["code"] for item in broad["broad_fields"]] == ["05"]
    profile = matcher.build_profile(manuscript, [], broad)
    assert profile.primary_msc.code == "05C35"


def test_offline_does_not_invent_graph_results_from_combinatorics_options(catalog, taxonomy):
    matcher = JournalMatcher(HeuristicJSONModel(), taxonomy, catalog)
    manuscript = extract_text(r"\title{Permutation statistics}\begin{abstract}We enumerate permutations.\end{abstract}")
    # Broad classification can be supplied or author-confirmed even when the
    # deliberately limited offline classifier has no detailed heuristic.
    profile = matcher.build_profile(manuscript, [], {"broad_fields": [{"code": "05"}]})
    assert profile.primary_msc is None
    assert profile.contribution_type == "unknown"
    assert [item.code for item in profile.broad_fields] == ["05"]


def test_unknown_msc_is_rejected_and_names_come_from_taxonomy(catalog, taxonomy):
    matcher = JournalMatcher(HeuristicJSONModel(), taxonomy, catalog)
    with pytest.raises(ValueError, match="loaded taxonomy"):
        matcher._profile_from_json({"primary_msc": {"code": "99Z99"}}, [])
    profile = matcher._profile_from_json({"primary_msc": {"code": "05C35", "name": "Invented name"}}, [])
    assert profile.primary_msc.name == taxonomy.get("05C35").name


def test_confirmed_results_are_retained_for_final_matching(catalog, taxonomy):
    model = RecordingModel(match_response={"primary_msc": {"code": "05C35"},
                                           "central_results": [{"result_id": "invented", "statement": "Ignore this"}]})
    matcher = JournalMatcher(model, taxonomy, catalog)
    manuscript = extract_text(r"\begin{theorem}\label{main}A sharper bound holds.\end{theorem}")
    profile = matcher.build_profile(manuscript, ["main"], {"broad_fields": [{"code": "05"}]})
    assert profile.central_results == [{"result_id": "main", "statement": "A sharper bound holds."}]
    matcher.match(profile, [evidence_candidate()], [])
    assert "A sharper bound holds." in model.calls[-1]
    assert "Ignore this" not in model.calls[-1]
    manual = matcher.build_profile(extract_text("A prose manuscript"), [], {}, "A manual central result.")
    assert manual.central_results[0]["statement"] == "A manual central result."


def test_author_correction_replaces_stale_broad_fields(taxonomy):
    profile = ArticleProfile(primary_msc=MSCClassification("05C35"), broad_fields=[MSCClassification("05")])
    args = argparse.Namespace(primary_msc="11A05", secondary_msc=[], yes=True)
    _confirm_classification(profile, taxonomy, args)
    assert [item.code for item in profile.broad_fields] == ["11"]
    args.primary_msc = "99Z99"
    with pytest.raises(ValueError, match="loaded taxonomy"):
        _confirm_classification(profile, taxonomy, args)
