import math

import pytest

from journal_matcher.catalog import JournalCatalog
from journal_matcher.llm import HeuristicJSONModel
from journal_matcher.msc import MSCTaxonomy
from journal_matcher.pipeline import JournalMatcher
from journal_matcher.retrieval import BM25, CachedEncoder, HybridRetriever
from journal_matcher.schemas import ArticleProfile, MSCClassification, JournalCandidate, JournalFieldProfile, RepresentativeArticle


def add(catalog, journal, title, abstract="", codes=(), year=2022, article_id=None):
    catalog.upsert_article({"journal_id": journal, "article_id": article_id or title, "title": title, "abstract": abstract,
                            "msc_codes": list(codes), "year": year})


def test_text_retrieval_can_find_a_journal_without_msc_tags():
    with JournalCatalog(":memory:") as catalog:
        catalog.upsert_journal({"journal_id": "right", "name": "Journal R"})
        catalog.upsert_journal({"journal_id": "wrong", "name": "Journal W"})
        add(catalog, "right", "Density estimation", "Nonparametric density estimation using neural networks")
        add(catalog, "wrong", "Chromatic polynomials", "Colorings of planar graphs", ["05C15"])
        catalog.rebuild_statistics()
        profile = ArticleProfile(primary_msc=MSCClassification("62G07"), retrieval_text="Nonparametric density estimation")
        assert not catalog.find_candidates(["62G07"])
        result = HybridRetriever(catalog).retrieve(profile)
        assert result[0].journal_id == "right"
        assert "lexical" in result[0].retrieval_sources
        assert result[0].representative_articles[0].title == "Density estimation"


def test_primary_topic_has_more_weight_than_secondary_tag():
    with JournalCatalog(":memory:") as catalog:
        for journal in ["primary", "secondary"]:
            catalog.upsert_journal({"journal_id": journal, "name": journal})
        catalog.set_stat("primary", "62", 10)
        catalog.set_stat("secondary", "68T07", 100)
        profile = ArticleProfile(primary_msc=MSCClassification("62G07"), secondary_msc=[MSCClassification("68T07")])
        result = HybridRetriever(catalog).retrieve(profile)
        assert result[0].journal_id == "primary"


def test_relevant_older_examples_survive_latest_eight_cutoff():
    with JournalCatalog(":memory:") as catalog:
        catalog.upsert_journal({"journal_id": "j", "name": "J"})
        add(catalog, "j", "Optimal transport on manifolds", "Wasserstein metric transport", ["49Q22"], year=2019)
        for i in range(10):
            add(catalog, "j", "Unrelated %s" % i, "Convex compactness", ["49J45"], year=2025)
        catalog.rebuild_statistics()
        profile = ArticleProfile(primary_msc=MSCClassification("49Q22"), retrieval_text="Wasserstein optimal transport")
        result = HybridRetriever(catalog).retrieve(profile)
        assert result[0].representative_articles[0].title == "Optimal transport on manifolds"


class FakeEncoder:
    identity = "fixture-encoder-v1"
    def __init__(self):
        self.calls = 0
    def encode(self, texts):
        self.calls += 1
        return [[1., 0.] if ("automorphism" in t or "symmetry" in t) else [0., 1.] for t in texts]


def test_semantic_route_and_content_model_cache():
    with JournalCatalog(":memory:") as catalog:
        catalog.upsert_journal({"journal_id": "j", "name": "J"})
        add(catalog, "j", "automorphism", "")
        encoder = FakeEncoder()
        result = HybridRetriever(catalog, encoder).retrieve(ArticleProfile(retrieval_text="symmetry"))
        assert result[0].journal_id == "j"
        assert "semantic" in result[0].retrieval_sources
        cached = CachedEncoder(catalog, encoder)
        count = encoder.calls
        cached.encode(["symmetry", "symmetry"])
        assert encoder.calls == count
        encoder.identity = "fixture-encoder-v2"
        CachedEncoder(catalog, encoder).encode(["symmetry"])
        assert encoder.calls > count


def test_index_refreshes_when_catalog_changes():
    with JournalCatalog(":memory:") as catalog:
        retriever = HybridRetriever(catalog)
        profile = ArticleProfile(retrieval_text="analytic number theory")
        assert not retriever.retrieve(profile)
        catalog.upsert_journal({"journal_id": "j", "name": "Analytic Number Theory"})
        assert retriever.retrieve(profile)[0].journal_id == "j"


def test_invalid_embedding_dimensions_fail_explicitly():
    class Broken(FakeEncoder):
        def encode(self, texts):
            return [[float("nan")]] * len(texts)
    with JournalCatalog(":memory:") as catalog:
        with pytest.raises(ValueError, match="finite"):
            CachedEncoder(catalog, Broken()).encode(["text"])


def test_one_abstract_cannot_support_a_hybrid_strong_fit_claim():
    class Model:
        def complete_json(self, prompt):
            return {"recommendations": [{"journal_id": "j", "fit": "strong match", "representative_article_ids": ["a"]}]}
    candidate = JournalCandidate("j", "J", "exact-subfield", retrieval_scores={"primary_msc": 1},
        representative_articles=[RepresentativeArticle("a", "A theorem", year=2020, abstract="An abstract")])
    field = JournalFieldProfile("j", "05C35", technical_depth_range=["advanced"], confidence="high", representative_article_ids=["a"])
    with JournalCatalog(":memory:") as catalog:
        matcher = JournalMatcher(Model(), MSCTaxonomy.from_json("data/msc2020.json"), catalog)
        report = matcher.match(ArticleProfile(technical_depth="advanced"), [candidate], [field])
        assert report.recommendations[0].fit == "plausible match"
