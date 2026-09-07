import json

import pytest

from journal_matcher.experiments import benchmark_retrieval
from journal_matcher.msc import MSCTaxonomy


def inputs():
    data = {"journals": [{"journal_id": "j", "name": "Graph Journal"}], "articles": [
        {"article_id": "held-out", "journal_id": "j", "title": "Target graph theorem", "doi": "10.1000/target", "msc_codes": ["05C35"]},
        {"article_id": "reference", "journal_id": "j", "title": "Extremal graph structures", "abstract": "Extremal graph bounds", "msc_codes": ["05C35"], "year": 2020}]}
    cases = [{"paper_id": "p1", "title": "Target graph theorem", "abstract": "Extremal graph bounds"}]
    labels = [{"paper_id": "p1", "actual_journal_id": "j", "doi": "10.1000/target"}]
    msc = [{"paper_id": "p1", "msc_codes": ["05C35"]}]
    return data, cases, labels, msc


def test_benchmark_excludes_target_and_exports_unjudged_labels(tmp_path):
    result = benchmark_retrieval(*inputs(), MSCTaxonomy.from_json("data/msc2020.json"), tmp_path / "run")
    assert result["metrics"]["hit_rate_at_k"] == 1
    audit = json.loads((tmp_path / "run/corpus-audit.json").read_text())
    assert audit[0]["excluded"]["target_duplicate"] == 1
    template = json.loads((tmp_path / "run/annotation-template.json").read_text())
    assert template["rows"][0]["work_id"]
    assert all(not c["judged"] and c["relevance"] is None for c in template["rows"][0]["candidates"])
    assert "10.1000/target" not in json.dumps(template)


def test_benchmark_refuses_silently_ignored_cutoff(tmp_path):
    with pytest.raises(ValueError, match="requires --strict-temporal"):
        benchmark_retrieval(*inputs(), MSCTaxonomy.from_json("data/msc2020.json"), tmp_path / "run", cutoff="2020-01-01")


def test_focused_benchmark_exports_its_own_training_schema(tmp_path):
    result = benchmark_retrieval(*inputs(), MSCTaxonomy.from_json("data/msc2020.json"), tmp_path / "run", retrieval="focused")
    assert result["metrics"]["hit_rate_at_k"] == 1
    template = json.loads((tmp_path / "run/annotation-template.json").read_text())
    assert template["feature_schema_version"] == 2
    assert all("primary_focus" in c["features"] and "secondary_focus" in c["features"] for c in template["rows"][0]["candidates"])


def test_strict_temporal_does_not_use_current_undated_registry(tmp_path):
    result = benchmark_retrieval(*inputs(), MSCTaxonomy.from_json("data/msc2020.json"), tmp_path / "run", strict_temporal=True, cutoff="2021-01-01")
    assert result["metrics"]["recommendation_coverage"] == 0


def test_model_benchmark_does_not_expose_publication_fields(tmp_path):
    class Model:
        model = "test-fixture"
        def complete_json(self, prompt):
            assert "10.1000/target" not in prompt
            assert "actual_journal_id" not in prompt
            if "Choose the most appropriate broad MSC" in prompt:
                return {"broad_fields": [{"code": "05"}]}
            if "classifying an unpublished" in prompt:
                return {"primary_msc": {"code": "05C35"}}
            return {}
    result = benchmark_retrieval(*inputs(), MSCTaxonomy.from_json("data/msc2020.json"), tmp_path / "run", model_factory=Model)
    assert result["mode"] == "test-fixture"
    assert result["supported_recommendations"]["metrics"]["recommendation_coverage"] == 0
    assert list((tmp_path / "run/p1").glob("call-*.json"))
