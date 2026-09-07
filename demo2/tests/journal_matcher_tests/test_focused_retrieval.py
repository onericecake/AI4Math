import pytest

from journal_matcher.catalog import JournalCatalog
from journal_matcher.cli import build_parser
from journal_matcher.llm import HeuristicJSONModel
from journal_matcher.msc import MSCTaxonomy
from journal_matcher.pipeline import JournalMatcher
from journal_matcher.rerank import LinearReranker, train_ranker
from journal_matcher.retrieval import FieldDistributions, HybridRetriever
from journal_matcher.schemas import ArticleProfile, MSCClassification


def test_focus_prefers_sustained_field_activity_over_incidental_or_tiny_samples():
    with JournalCatalog(":memory:") as catalog:
        for name in ("specialist", "incidental", "sample"):
            catalog.upsert_journal({"journal_id": name, "name": name})
        catalog.set_stat("specialist", "05", 800, .8)
        catalog.set_stat("incidental", "05", 10, .01)
        catalog.set_stat("sample", "05", 1, 1, source="derived")
        catalog.set_stat("sample", "05C35", 1, 1, source="derived")
        result = HybridRetriever(catalog, strategy="focused").retrieve(ArticleProfile(primary_msc=MSCClassification("05C35")))
        assert result[0].journal_id == "specialist"
        focus = {c.journal_id: c.retrieval_scores["primary_focus"] for c in result}
        assert focus["specialist"] > focus["sample"] > focus["incidental"]


def test_detailed_tags_do_not_double_count_the_field_population():
    stats = [{"journal_id": "j", "msc_prefix": "05", "article_count": 500, "share": .5}]
    extra = {"journal_id": "j", "msc_prefix": "05C35", "article_count": 400, "share": .4}
    assert FieldDistributions(stats).focus("j", "05C35") == FieldDistributions(stats + [extra]).focus("j", "05C35")


def test_population_and_local_sample_denominators_stay_separate():
    stats = [
        {"journal_id": "j", "msc_prefix": "05", "article_count": 500, "share": .5, "source": "imported"},
        {"journal_id": "j", "msc_prefix": "11", "article_count": 1, "share": 1., "source": "derived"},
    ]
    model = FieldDistributions(stats)
    assert model.totals["j", "imported"] == 1000
    assert model.totals["j", "derived"] == 1
    assert model.focus("j", "05C35") == FieldDistributions(stats[:1]).focus("j", "05C35")


def test_a_matching_journal_name_does_not_outweigh_article_text():
    with JournalCatalog(":memory:") as catalog:
        catalog.upsert_journal({"journal_id": "name", "name": "Density estimation"})
        catalog.upsert_journal({"journal_id": "evidence", "name": "Journal E"})
        catalog.upsert_article({"article_id": "a", "journal_id": "evidence", "title": "Density estimation", "abstract": "Density estimation"})
        query = ArticleProfile(retrieval_text="Density estimation")
        result = HybridRetriever(catalog, strategy="focused").retrieve(query)
        assert result[0].journal_id == "evidence"
        named = next(c for c in result if c.journal_id == "name")
        assert named.retrieval_scores["lexical"] <= .25


def test_new_strategy_is_explicit_and_original_features_remain_available():
    args = build_parser().parse_args(["benchmark", "--dataset", "data", "--output-dir", "out"])
    assert args.retrieval == "hybrid"
    with JournalCatalog(":memory:") as catalog:
        catalog.upsert_journal({"journal_id": "j", "name": "Graph theory"})
        query = ArticleProfile(retrieval_text="Graph theory")
        original = HybridRetriever(catalog).retrieve(query)[0]
        experiment = HybridRetriever(catalog, strategy="focused").retrieve(query)[0]
        assert "primary_focus" not in original.retrieval_scores
        assert experiment.retrieval_scores["focus_available"] == 1


def judged_data():
    def row(name, split):
        return {"paper_id": name, "split": split, "candidates": [
            {"journal_id": "a", "judged": True, "relevance": 2,
             "features": {"primary_focus": .1, "secondary_focus": 0, "lexical": 1}},
            {"journal_id": "b", "judged": True, "relevance": 0,
             "features": {"primary_focus": 1, "secondary_focus": 0, "lexical": 0}},
        ]}
    return {"feature_schema_version": 2, "label_provenance": "synthetic regression fixture",
            "train": [row("train", "train")], "validation": [row("valid", "validation")]}


def test_focused_training_roundtrip_and_hybrid_schema_compatibility(tmp_path):
    model = train_ranker(judged_data())
    assert model.feature_schema_version == 2
    assert model.metadata["validation_pairwise_accuracy"] == 1
    path = tmp_path / "focused.json"
    model.save(path)
    loaded = LinearReranker.load(path)
    assert loaded.weights == model.weights
    assert loaded.feature_schema_version == 2
    old = tmp_path / "old.json"
    LinearReranker().save(old)
    assert LinearReranker.load(old).feature_schema_version == 1
    with JournalCatalog(":memory:") as catalog:
        taxonomy = MSCTaxonomy.from_json("data/msc2020.json")
        with pytest.raises(ValueError, match="schema does not match"):
            JournalMatcher(HeuristicJSONModel(), taxonomy, catalog, reranker=loaded)
        JournalMatcher(HeuristicJSONModel(), taxonomy, catalog, retrieval="focused", reranker=loaded)


def test_focused_features_cannot_silently_train_as_the_old_schema():
    data = judged_data()
    data.pop("feature_schema_version")
    with pytest.raises(ValueError, match="require feature_schema_version 2"):
        train_ranker(data)
    data = judged_data()
    data["train"][0]["candidates"][0]["features"].pop("primary_focus")
    with pytest.raises(ValueError, match="requires both focus features"):
        train_ranker(data)
