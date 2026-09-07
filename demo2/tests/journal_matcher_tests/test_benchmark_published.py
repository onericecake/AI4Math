"""Guard the benchmark's leakage controls, rather than its current scores."""
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location("benchmark_published", Path(__file__).resolve().parents[2] / "scripts/benchmark_published.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_targets_are_excluded_by_doi_title_or_arxiv_version():
    cases = [{"paper_id": "p1", "title": "Fröberg's Theorem", "arxiv_id": "2311.02430", "alternate_titles": ["An earlier title"]}]
    labels = [{"paper_id": "p1", "doi": "10.1216/jca.2024.16.391"}]
    articles = [
        {"article_id": "doi", "doi": "https://DOI.org/10.1216/JCA.2024.16.391", "title": "Changed title"},
        {"article_id": "title", "title": "Frobergs theorem"},
        {"article_id": "version", "title": "Versioned", "source_url": "https://arxiv.org/abs/2311.02430v2"},
        {"article_id": "alternate", "title": "An earlier title"},
        {"article_id": "keep", "title": "Different paper", "source_url": "https://arxiv.org/abs/2311.024301"},
    ]
    original = {"journals": [], "articles": articles, "journal_msc_stats": [{"msc_prefix": "13", "article_count": 10}]}
    result, excluded = benchmark.prepare_catalog(original, cases, labels)
    assert [a["article_id"] for a in result["articles"]] == ["keep"]
    assert len(excluded) == 4
    assert result["journal_msc_stats"] == original["journal_msc_stats"]
    assert len(original["articles"]) == 5


def test_sample_only_discards_untraceable_imported_aggregates():
    original = {"journals": [], "articles": [], "journal_msc_stats": [{"msc_prefix": "13", "article_count": 10}]}
    result, _ = benchmark.prepare_catalog(original, [], [], sample_only=True)
    assert result["journal_msc_stats"] == []
    assert original["journal_msc_stats"]
