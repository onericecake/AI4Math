import json

import pytest

from journal_matcher.harvest import collection_plan, harvest_crossref, normalize_crossref


JOURNAL = {"journal_id": "j", "name": "Journal", "issn_l": "1234-567X"}


def item(doi, abstract="<jats:p>An abstract.</jats:p>"):
    return {"DOI": doi, "title": ["A theorem about " + doi], "abstract": abstract, "type": "journal-article",
            "published": {"date-parts": [[2022, 2]]}, "license": [{"URL": "https://example.org/license"}]}


def test_normalization_keeps_provenance_and_conservative_dates():
    record = normalize_crossref(item("10.1234/A"), JOURNAL, "2026-09-06")
    assert record["doi"] == "10.1234/a"
    assert record["abstract"] == "An abstract."
    assert record["available_date"] == "2022-02-28"
    assert record["metadata_available_date"] == "2026-09-06"
    assert record["msc_codes"] == []
    assert record["license"][0]["URL"]


def test_collection_resumes_and_never_exceeds_quota(tmp_path):
    class Client:
        mailto = ""
        def __init__(self): self.calls = 0
        def get(self, url):
            self.calls += 1
            if self.calls == 1:
                return {"message": {"items": [item("10.1234/a"), item("10.1234/skip", "")], "next-cursor": "next"}}
            return {"message": {"items": [item("10.1234/b")], "next-cursor": "done"}}
    plan = {"journals": [JOURNAL], "start_year": 2022, "end_year": 2022, "per_journal": 2}
    client = Client()
    first = harvest_crossref(plan, tmp_path, client, require_abstract=True)
    assert first["articles"] == 2 and client.calls == 2
    second = harvest_crossref(plan, tmp_path, client, require_abstract=True)
    assert second == first and client.calls == 2
    assert json.loads((tmp_path / "catalog.json").read_text())["metadata"]["complete"]
    with pytest.raises(ValueError, match="different plan"):
        harvest_crossref({**plan, "per_journal": 3}, tmp_path, client, require_abstract=True)


def test_failed_page_keeps_progress_and_can_resume(tmp_path):
    class Client:
        mailto = ""
        def __init__(self): self.fail = True
        def get(self, url):
            if "cursor=%2A" in url:
                return {"message": {"items": [item("10.1234/a"), item("10.1234/skip", "")], "next-cursor": "second"}}
            if self.fail:
                raise RuntimeError("network down")
            return {"message": {"items": [item("10.1234/b")], "next-cursor": "done"}}
    client = Client()
    plan = {"journals": [JOURNAL], "start_year": 2022, "end_year": 2022, "per_journal": 2}
    with pytest.raises(RuntimeError, match="network"):
        harvest_crossref(plan, tmp_path, client, True)
    assert len(json.loads((tmp_path / "catalog.json").read_text())["articles"]) == 1
    client.fail = False
    assert harvest_crossref(plan, tmp_path, client, True)["articles"] == 2


def test_field_balanced_plan_is_reproducible_and_bounded():
    journals = [{**JOURNAL, "journal_id": str(i)} for i in range(6)]
    stats = [{"journal_id": str(i), "msc_prefix": "05" if i < 4 else "62", "article_count": 10} for i in range(6)]
    data = {"journals": journals, "journal_msc_stats": stats}
    plan = collection_plan(data, journal_limit=2, per_journal=200, start_year=2020, end_year=2024)
    assert plan == collection_plan(data, journal_limit=2, per_journal=200, start_year=2020, end_year=2024)
    assert plan["maximum_articles"] == 400
    assert int(plan["journals"][0]["journal_id"]) < 4 <= int(plan["journals"][1]["journal_id"])
