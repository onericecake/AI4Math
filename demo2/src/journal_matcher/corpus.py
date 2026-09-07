"""Identifiers, provenance, duplicate grouping and temporal corpus selection."""
from __future__ import annotations

import calendar
import hashlib
import json
import re
import unicodedata
from datetime import date
from typing import Any, Iterable, Mapping


def normalize_doi(value: Any) -> str:
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value or "").strip(), flags=re.I)
    return value.lower().rstrip(" .")


def normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def normalize_arxiv(value: Any) -> str:
    match = re.search(r"(?<![\d.])(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?(?!\d)", str(value or ""), re.I)
    return re.sub(r"v\d+$", "", match.group(0), flags=re.I).lower() if match else ""


def identifiers(record: Mapping[str, Any]) -> set[str]:
    keys = {str(k) for k in record.get("identity_keys", []) if str(k).startswith(("doi:", "arxiv:", "title:", "work:"))}
    for value in [record.get("doi"), *record.get("alternate_dois", [])]:
        if doi := normalize_doi(value):
            keys.add("doi:" + doi)
    source = record.get("source_url") if "arxiv.org/" in str(record.get("source_url", "")) else None
    for value in [record.get("arxiv_id"), source, *record.get("arxiv_ids", [])]:
        if arxiv := normalize_arxiv(value):
            keys.add("arxiv:" + arxiv)
    for value in [record.get("title"), *record.get("alternate_titles", [])]:
        if title := normalize_title(value):
            keys.add("title:" + title)
    if record.get("work_id"):
        keys.add("work:" + str(record["work_id"]))
    return keys


def duplicate_groups(records: list[Mapping[str, Any]]) -> list[list[int]]:
    """Connected components catch bridges between DOI and preprint versions."""
    parent = list(range(len(records)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owners = {}
    for index, record in enumerate(records):
        for key in identifiers(record):
            if key in owners:
                parent[find(index)] = find(owners[key])
            else:
                owners[key] = index
    groups = {}
    for index in range(len(records)):
        groups.setdefault(find(index), []).append(index)
    return list(groups.values())


def normalize_date(value: Any) -> str:
    """Partial dates use the end of their interval (conservative cutoffs)."""
    if not value:
        return ""
    value = str(value)
    if re.fullmatch(r"\d{4}", value):
        value += "-12-31"
    elif re.fullmatch(r"\d{4}-\d{2}", value):
        year, month = map(int, value.split("-"))
        value += "-%02d" % calendar.monthrange(year, month)[1]
    return date.fromisoformat(value).isoformat()


def eligible_research(record: Mapping[str, Any]) -> bool:
    title = str(record.get("title", "")).lower()
    kind = str(record.get("article_type", "research article")).lower()
    return kind in {"research article", "journal-article", "research-article", "article"} and not any(
        word in title for word in ("republication", "obituary", "in memoriam", "the life and work", "erratum", "corrigendum", "retraction"))


def select_reference_corpus(data: Mapping[str, Any], targets: Iterable[Mapping[str, Any]] = (), cutoff: str | None = None) -> tuple[dict, dict]:
    """Exclude whole target components and unknown/future evidence at a cutoff.

    Strict cutoffs require content AND metadata availability. Aggregate stats
    and undated scopes are not admitted as historical observations.
    """
    records = list(data.get("articles", []))
    targets = list(targets)
    combined = records + targets
    excluded = set()
    for group in duplicate_groups(combined):
        if any(i >= len(records) for i in group):
            excluded.update(i for i in group if i < len(records))
    cutoff = normalize_date(cutoff) if cutoff else None
    kept, reasons = [], {"target_duplicate": 0, "unknown_or_future_date": 0, "non_research": 0}
    for index, record in enumerate(records):
        if index in excluded:
            reasons["target_duplicate"] += 1
        elif not eligible_research(record):
            reasons["non_research"] += 1
        elif cutoff and (not record.get("available_date") or not record.get("metadata_available_date") or
                         normalize_date(record["available_date"]) > cutoff or
                         normalize_date(record["metadata_available_date"]) > cutoff):
            reasons["unknown_or_future_date"] += 1
        else:
            kept.append(record)
    journals = [dict(j) for j in data.get("journals", [])]
    if cutoff:
        # A current journal registry can leak later names, scopes and newly
        # launched journals even after filtering article dates.
        journals = [j for j in journals if j.get("registry_available_date") and normalize_date(j["registry_available_date"]) <= cutoff]
        journal_ids = {j["journal_id"] for j in journals}
        missing_registry = sum(a.get("journal_id") not in journal_ids for a in kept)
        kept = [a for a in kept if a.get("journal_id") in journal_ids]
        reasons["undated_or_future_registry"] = missing_registry
        for journal in journals:
            if not journal.get("scope_available_date") or normalize_date(journal["scope_available_date"]) > cutoff:
                journal.update(scope_summary="", technical_level="unknown", audience_breadth="unknown", scope_breadth="unknown")
            journal["editorial_evidence"] = [e for e in journal.get("editorial_evidence", [])
                if e.get("available_date") and normalize_date(e["available_date"]) <= cutoff]
    result = dict(data, journals=journals, articles=kept)
    # Always rebuild local counts after excluding papers. Imported aggregates
    # can be retained only for explicitly non-temporal exploratory runs.
    if cutoff:
        result["journal_msc_stats"] = []
    return result, {"retained": len(kept), "excluded": reasons, "cutoff": cutoff,
                    "imported_aggregates_retained": bool(result.get("journal_msc_stats"))}


def temporal_split(records: list[Mapping[str, Any]], train_end: str, validation_end: str) -> dict:
    train_end, validation_end = normalize_date(train_end), normalize_date(validation_end)
    if train_end >= validation_end:
        raise ValueError("train_end must precede validation_end")
    splits = {"train": [], "validation": [], "test": [], "quarantine": []}
    for group in duplicate_groups(records):
        # Put every version in the latest split needed by any version; this
        # prevents a revised/final article leaking into an earlier training set.
        dates = [normalize_date(records[i].get("available_date")) for i in group]
        if not all(dates):
            destination = "quarantine"
        else:
            latest = max(dates)
            destination = "train" if latest <= train_end else "validation" if latest <= validation_end else "test"
        splits[destination].extend(records[i] for i in group)
    return splits


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
