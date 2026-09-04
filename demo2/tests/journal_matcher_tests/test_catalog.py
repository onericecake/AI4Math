import json

from journal_matcher.catalog import JournalCatalog


def test_import_rebuilds_msc_statistics_and_finds_candidates(tmp_path):
    source = tmp_path / "catalog.json"
    source.write_text(
        json.dumps(
            {
                "journals": [
                    {"journal_id": "j1", "name": "Journal One", "official_url": "https://example.org"},
                    {"journal_id": "j2", "name": "Journal Two"},
                ],
                "articles": [
                    {"article_id": "a1", "journal_id": "j1", "title": "Graph bounds", "year": 2025, "msc_codes": ["05C35"]},
                    {"article_id": "a2", "journal_id": "j2", "title": "Number theory", "year": 2025, "msc_codes": ["11A05"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    with JournalCatalog(tmp_path / "catalog.sqlite") as catalog:
        assert catalog.import_json(source) == 2
        candidates = catalog.find_candidates(["05C35"])
        assert [item.journal_id for item in candidates] == ["j1"]
        assert candidates[0].representative_articles[0].article_id == "a1"
        assert catalog.counts()["journals"] == 2


def test_import_merges_sources_by_issn_and_doi(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps({
        "journals": [{"journal_id": "j1", "name": "Journal One", "issn_l": "1234-5678"}],
        "articles": [{"article_id": "a1", "journal_id": "j1", "doi": "10.1000/example", "title": "Graph bounds", "msc_codes": ["05C35"]}],
    }), encoding="utf-8")
    second.write_text(json.dumps({
        "journals": [{"journal_id": "other-id", "name": "Journal One", "issn_l": "1234-5678"}],
        "articles": [{"article_id": "other-article-id", "journal_id": "other-id", "doi": "10.1000/example", "title": "Graph bounds (version)", "msc_codes": ["05C35"]}],
    }), encoding="utf-8")
    with JournalCatalog(tmp_path / "catalog.sqlite") as catalog:
        catalog.import_json(first)
        catalog.import_json(second)
        assert catalog.counts()["journals"] == 1
        assert catalog.counts()["articles"] == 1
