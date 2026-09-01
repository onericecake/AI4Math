import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_bundled_fixtures_cover_every_broad_msc_field():
    taxonomy = json.loads((ROOT / "data" / "msc2020.json").read_text(encoding="utf-8"))
    broad_codes = {item["code"] for item in taxonomy if len(item["code"]) == 2}
    assert len(taxonomy) >= 6600
    assert len(broad_codes) == 63

    catalog = json.loads((ROOT / "data" / "catalog.example.json").read_text(encoding="utf-8"))
    covered_codes = {
        item["msc_prefix"]
        for item in catalog["journal_msc_stats"]
        if len(item["msc_prefix"]) == 2
    }
    assert len(catalog["journals"]) >= 1500
    assert broad_codes <= covered_codes

