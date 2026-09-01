import json

from journal_matcher.catalog import JournalCatalog, _msc_prefixes


def test_msc_prefixes_are_specific_first_and_deterministic():
    assert _msc_prefixes("05C35") == ("05C35", "05C", "05")
    assert _msc_prefixes("05") == ("05",)


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
        assert candidates[0].tier == "exact-subfield"
        assert candidates[0].representative_articles[0].article_id == "a1"
        assert catalog.find_candidates(["05"])[0].tier == "broad-field"
        assert catalog.counts()["journals"] == 2
