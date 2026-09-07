"""Bounded, resumable Crossref collection, balanced by journal and year."""
from __future__ import annotations

import json
import random
import time
from datetime import date
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
import re

from .corpus import eligible_research, fingerprint, normalize_date, normalize_doi


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def plain_text(value) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


def crossref_date(value) -> str:
    parts = value.get("date-parts", [[]])[0] if isinstance(value, dict) else []
    return normalize_date("-".join(str(p) if i == 0 else "%02d" % p for i, p in enumerate(parts))) if parts else ""


def normalize_crossref(item, journal, retrieved_on):
    doi = normalize_doi(item.get("DOI"))
    titles = item.get("title", [])
    if not doi or not titles or item.get("type") != "journal-article":
        return None
    published = crossref_date(item.get("published", {})) or crossref_date(item.get("issued", {}))
    record = {"article_id": "doi:" + doi, "journal_id": journal["journal_id"], "doi": doi,
              "title": plain_text(titles[0]), "abstract": plain_text(item.get("abstract")),
              "year": int(published[:4]) if published else None, "published_date": published,
              "available_date": published, "metadata_available_date": retrieved_on,
              "article_type": "journal-article", "source_url": "https://doi.org/" + doi,
              "msc_codes": [], "source": "crossref", "retrieved_on": retrieved_on,
              "license": item.get("license", []), "language": item.get("language", "unknown"),
              "provenance": {"url": "https://api.crossref.org/works/" + quote(doi, safe=""),
                             "availability_basis": "publication date; metadata observation is harvest date",
                             "article_type_basis": "Crossref journal-article; research subtype not independently verified"}}
    return record if eligible_research(record) else None


class CrossrefClient:
    def __init__(self, mailto="", timeout=20, retries=3, interval=1.0):
        self.mailto, self.timeout, self.retries, self.interval = mailto, timeout, retries, interval
        self.last_request = 0.0

    def get(self, url):
        headers = {"User-Agent": "AI4Math-journal-matcher/0.2" + (" (mailto:%s)" % self.mailto if self.mailto else ""), "Accept": "application/json"}
        for attempt in range(self.retries + 1):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                with urlopen(Request(url, headers=headers), timeout=self.timeout) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code not in (408, 429, 500, 502, 503, 504) or attempt == self.retries:
                    raise RuntimeError("Crossref request failed with HTTP %s; progress is saved" % error.code) from error
                delay = error.headers.get("Retry-After", "")
                time.sleep(min(60, max(2 ** attempt, float(delay) if delay.isdigit() else 0)))
            except (URLError, TimeoutError) as error:
                if attempt == self.retries:
                    raise RuntimeError("Crossref network request failed; progress is saved") from error
                time.sleep(2 ** attempt)
        raise RuntimeError("Crossref retries exhausted")


def collection_plan(data, journal_limit=100, per_journal=200, start_year=2020, end_year=2024, seed=0):
    if journal_limit <= 0 or per_journal <= 0 or not 1900 <= start_year <= end_year <= date.today().year:
        raise ValueError("Invalid journal quota or year interval")
    broad = {}
    for stat in data.get("journal_msc_stats", []):
        code = stat["msc_prefix"]
        if len(code) == 2 and stat.get("article_count", 0) > broad.get(stat["journal_id"], ("", -1))[1]:
            broad[stat["journal_id"]] = (code, stat["article_count"])
    buckets = {}
    for journal in sorted(data.get("journals", []), key=lambda j: j["journal_id"]):
        if journal.get("active", True) and re.fullmatch(r"\d{4}-[\dXx]{4}", str(journal.get("issn_l", ""))):
            buckets.setdefault(broad.get(journal["journal_id"], ("unknown", 0))[0], []).append(journal)
    rng = random.Random(seed)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    selected = []
    while any(buckets.values()) and len(selected) < journal_limit:
        for field in sorted(buckets):
            if buckets[field] and len(selected) < journal_limit:
                selected.append(buckets[field].pop())
    return {"version": 1, "selection": "seeded round-robin across dominant broad MSC fields, then equal journal/year quotas",
            "seed": seed, "journals": selected, "per_journal": per_journal,
            "start_year": start_year, "end_year": end_year, "maximum_articles": len(selected) * per_journal}


def harvest_crossref(plan, output_dir: Path, client=None, require_abstract=False):
    """Persist pages before checkpoints; replaying an interrupted page is safe."""
    client = client or CrossrefClient()
    output_dir.mkdir(parents=True, exist_ok=True)
    identity = fingerprint({"plan": plan, "require_abstract": require_abstract})
    state_path = output_dir / "checkpoint.json"
    corpus_path = output_dir / "catalog.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"plan_sha256": identity, "jobs": {}}
    if state["plan_sha256"] != identity:
        raise ValueError("Checkpoint belongs to a different plan; choose a new output directory")
    corpus = json.loads(corpus_path.read_text()) if corpus_path.exists() else {"journals": [{**j, "registry_available_date": j.get("registry_available_date") or date.today().isoformat()} for j in plan["journals"]], "articles": [], "journal_msc_stats": []}
    articles = {a["doi"]: a for a in corpus["articles"]}
    years = list(range(plan["start_year"], plan["end_year"] + 1))
    base, remainder = divmod(plan["per_journal"], len(years))
    for journal in plan["journals"]:
        for position, year in enumerate(years):
            quota = base + int(position < remainder)
            key = "%s:%s" % (journal["journal_id"], year)
            job = state["jobs"].setdefault(key, {"cursor": "*", "accepted_dois": [], "pages": 0, "quota": quota, "complete": quota == 0})
            while not job["complete"]:
                rows = min(100, max(quota - len(job["accepted_dois"]), 1))
                params = {"filter": "type:journal-article,from-pub-date:%s-01-01,until-pub-date:%s-12-31" % (year, year),
                          "rows": rows, "cursor": job["cursor"], "sort": "published", "order": "asc"}
                if client.mailto:
                    params["mailto"] = client.mailto
                url = "https://api.crossref.org/journals/%s/works?%s" % (quote(journal["issn_l"], safe=""), urlencode(params))
                cache = output_dir / "pages" / (fingerprint({"url": url, "page": job["pages"]}) + ".json")
                try:
                    response = json.loads(cache.read_text()) if cache.exists() else client.get(url)
                    if not cache.exists():
                        atomic_json(cache, {**response, "_retrieved_on": date.today().isoformat()})
                    items = response["message"]["items"]
                except Exception:
                    atomic_json(state_path, state)
                    raise
                observed = response.get("_retrieved_on", date.today().isoformat())
                page_hash = fingerprint(items)
                if items and page_hash in job.get("seen_pages", []):
                    raise RuntimeError("Crossref repeated a page without progress; resume with a fresh cursor or plan directory")
                job.setdefault("seen_pages", []).append(page_hash)
                for item in items:
                    article = normalize_crossref(item, journal, observed)
                    if article and (not require_abstract or article["abstract"]) and article["doi"] not in job["accepted_dois"]:
                        articles[article["doi"]] = article
                        job["accepted_dois"].append(article["doi"])
                        if len(job["accepted_dois"]) >= quota:
                            break
                next_cursor = response["message"].get("next-cursor")
                job["pages"] += 1
                job["complete"] = len(job["accepted_dois"]) >= quota or len(items) < rows or not next_cursor
                job["cursor"] = next_cursor
                corpus["articles"] = list(articles.values())
                corpus["metadata"] = {"source": "Crossref", "plan_sha256": identity, "require_abstract": require_abstract,
                                      "complete": all(j.get("complete") for j in state["jobs"].values()) and len(state["jobs"]) == len(years) * len(plan["journals"])}
                atomic_json(corpus_path, corpus)
                atomic_json(state_path, state)
    corpus["articles"] = list(articles.values())
    corpus["metadata"] = {"source": "Crossref", "plan_sha256": identity, "require_abstract": require_abstract, "complete": True}
    atomic_json(corpus_path, corpus)
    atomic_json(state_path, state)
    return {"articles": len(articles), "jobs": len(state["jobs"]), "complete": all(j["complete"] for j in state["jobs"].values()),
            "quota_shortfalls": {key: job["quota"] - len(job["accepted_dois"]) for key, job in state["jobs"].items() if len(job["accepted_dois"]) < job["quota"]}, "catalog": str(corpus_path)}
