import json

import pytest

from journal_matcher.catalog import JournalCatalog
from journal_matcher.corpus import duplicate_groups, normalize_date, select_reference_corpus, temporal_split
from journal_matcher.rerank import FEATURES, LinearReranker, train_ranker


def test_doi_preprint_bridges_join_versions_and_temporal_split():
    records = [
        {"title": "Old title", "arxiv_id": "2101.12345v1", "available_date": "2021-01"},
        {"title": "New title", "arxiv_id": "2101.12345v2", "doi": "https://doi.org/10.1234/ABC", "available_date": "2022-06"},
        {"title": "Final title", "doi": "10.1234/abc", "available_date": "2024"},
        {"title": "Unknown date"},
    ]
    assert sorted(duplicate_groups(records)[0]) == [0, 1, 2]
    splits = temporal_split(records, "2022-12-31", "2023-12-31")
    assert not splits["train"] and not splits["validation"]
    assert len(splits["test"]) == 3 and len(splits["quarantine"]) == 1
    assert normalize_date("2024-02") == "2024-02-29"


def test_cutoff_filters_metadata_and_scopes_as_well_as_publication():
    data = {"journals": [{"journal_id": "j", "scope_summary": "Current scope", "registry_available_date": "2020-01-01"}], "journal_msc_stats": [{"msc_prefix": "05"}], "articles": [
        {"title": "Old content, new metadata", "available_date": "2020", "metadata_available_date": "2026"},
        {"title": "Eligible", "journal_id": "j", "available_date": "2020", "metadata_available_date": "2021"},
        {"title": "Unknown metadata", "available_date": "2020"},
    ]}
    result, audit = select_reference_corpus(data, cutoff="2022-12-31")
    assert [a["title"] for a in result["articles"]] == ["Eligible"]
    assert not result["journal_msc_stats"] and not result["journals"][0]["scope_summary"]
    assert audit["excluded"]["unknown_or_future_date"] == 2


def test_targets_exclude_all_connected_versions():
    data = {"journals": [], "articles": [{"title": "Early", "arxiv_id": "2101.12345"},
        {"title": "Later", "doi": "10.1000/a", "arxiv_id": "2101.12345v2"}]}
    result, audit = select_reference_corpus(data, [{"doi": "10.1000/A"}])
    assert not result["articles"] and audit["excluded"]["target_duplicate"] == 2


def test_catalog_merges_explicit_id_bridges_and_preserves_provenance():
    with JournalCatalog(":memory:") as c:
        c.upsert_journal({"journal_id": "j", "name": "J", "scope_summary": "Real scope"})
        c.upsert_journal({"journal_id": "j", "name": "J", "publisher": "P"})
        c.upsert_article({"article_id": "a", "journal_id": "j", "title": "Early", "arxiv_id": "2101.12345", "msc_codes": ["05C35"], "available_date": "2021-01-01"})
        c.upsert_article({"article_id": "b", "journal_id": "j", "title": "Final", "doi": "10.1000/a", "abstract": "A readable abstract"})
        c.upsert_article({"article_id": "bridge", "journal_id": "j", "title": "Final", "doi": "https://doi.org/10.1000/A", "arxiv_id": "2101.12345v2", "msc_codes": [], "metadata_available_date": "2026-01-01"})
        export = c.export_data()
        assert len(export["articles"]) == 1
        assert export["articles"][0]["msc_codes"] == ["05C35"]
        assert export["articles"][0]["abstract"] == "A readable abstract"
        assert export["articles"][0]["metadata_available_date"] == "2026-01-01"
        assert export["journals"][0]["scope_summary"] == "Real scope"


def test_catalog_cannot_backdate_merged_metadata_and_allows_type_correction():
    with JournalCatalog(":memory:") as c:
        c.upsert_journal({"journal_id": "j", "name": "J"})
        c.upsert_article({"article_id": "a", "journal_id": "j", "title": "A", "article_type": "journal-article", "metadata_available_date": "2026-09-06"})
        c.upsert_article({"article_id": "a", "journal_id": "j", "title": "A", "article_type": "research article", "metadata_available_date": "2021-01-01"})
        article = c.export_data()["articles"][0]
        assert article["metadata_available_date"] == "2026-09-06"
        assert article["article_type"] == "research article"


def dataset():
    def row(paper_id, split):
        return {"paper_id": paper_id, "split": split, "candidates": [
            {"journal_id": "good", "judged": True, "relevance": 2, "features": {"semantic": 1}},
            {"journal_id": "bad", "judged": True, "relevance": 0, "features": {"primary_msc": 1}},
            {"journal_id": "unknown", "judged": False, "features": {"lexical": 1}}]}
    return {"label_provenance": "synthetic test fixture", "train": [row("train", "train")], "validation": [row("valid", "validation")]}


def test_ranker_learns_preferences_and_roundtrips(tmp_path):
    data = dataset()
    ranker = train_ranker(data)
    assert ranker.metadata["training_pairs"] == 1
    assert ranker.metadata["validation_pairwise_accuracy"] == 1
    assert ranker.metadata["baseline_validation_pairwise_accuracy"] == 0
    path = tmp_path / "ranker.json"
    ranker.save(path)
    assert LinearReranker.load(path).weights == ranker.weights


def test_ranker_rejects_leakage_and_does_not_make_unlabeled_negatives():
    data = dataset()
    data["train"][0]["doi"] = "10.1000/a"
    data["validation"][0]["doi"] = "https://doi.org/10.1000/A"
    with pytest.raises(ValueError, match="both training and validation"):
        train_ranker(data)
    data = dataset()
    data["train"][0]["candidates"][1]["judged"] = False
    with pytest.raises(ValueError, match="explicit unequal"):
        train_ranker(data)
