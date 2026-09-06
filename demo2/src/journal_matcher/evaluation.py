"""Offline metrics for independently labeled, possibly multi-journal cases.

This scores saved rankings; it does not create ground truth or run a model.
Keep benchmark papers and their later versions out of the retrieval corpus.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Sequence


def _ids(case: Mapping[str, Any], key: str, allow_empty: bool = True) -> list[str]:
    value = case.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError("%s must be a list of nonempty journal IDs" % key)
    if len(value) != len(set(value)):
        raise ValueError("%s contains duplicate journal IDs" % key)
    if not value and not allow_empty:
        raise ValueError("%s must contain at least one independently labeled journal" % key)
    return value


def evaluate_rankings(cases: Sequence[Mapping[str, Any]], k: int = 3) -> Dict[str, Any]:
    """Compute binary relevance metrics, including abstentions as misses.

    Recall measures the fraction of all suitable labeled venues retrieved;
    hit rate measures whether at least one is found. MRR and nDCG are cut at k.
    Labels should represent multiple expert-approved submission options where
    possible; a historical publication venue is only a weak single label.
    """
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    if not isinstance(cases, list) or not cases:
        raise ValueError("evaluation requires a nonempty cases list")
    rows = []
    seen = set()
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValueError("each evaluation case must be an object")
        paper_id = case.get("paper_id")
        if not isinstance(paper_id, str) or not paper_id.strip() or paper_id in seen:
            raise ValueError("paper_id must be a unique nonempty string")
        seen.add(paper_id)
        relevant = set(_ids(case, "relevant_journal_ids", allow_empty=False))
        ranking = _ids(case, "ranked_journal_ids")
        hits = [index for index, journal_id in enumerate(ranking[:k], 1) if journal_id in relevant]
        ideal = sum(1 / math.log2(index + 1) for index in range(1, min(k, len(relevant)) + 1))
        candidate_recall = None
        if "candidate_journal_ids" in case:
            pool = set(_ids(case, "candidate_journal_ids"))
            if not set(ranking) <= pool:
                raise ValueError("ranked journals must belong to candidate_journal_ids")
            candidate_recall = len(relevant & pool) / len(relevant)
        rows.append({
            "paper_id": paper_id,
            "hit_rate_at_k": float(bool(hits)),
            "recall_at_k": len(hits) / len(relevant),
            "mrr_at_k": 1 / hits[0] if hits else 0.0,
            "ndcg_at_k": sum(1 / math.log2(index + 1) for index in hits) / ideal,
            "returned_recommendations": bool(ranking),
            "candidate_recall": candidate_recall,
        })
    metrics = {key: sum(row[key] for row in rows) / len(rows)
               for key in ("hit_rate_at_k", "recall_at_k", "mrr_at_k", "ndcg_at_k")}
    candidate_rows = [row for row in rows if row["candidate_recall"] is not None]
    metrics["candidate_recall"] = (sum(row["candidate_recall"] for row in candidate_rows) / len(candidate_rows)
                                   if candidate_rows else None)
    metrics["recommendation_coverage"] = sum(row["returned_recommendations"] for row in rows) / len(rows)
    return {
        "k": k,
        "case_count": len(rows),
        "candidate_recall_case_count": len(candidate_rows),
        "metrics": metrics,
        "cases": rows,
        "limitations": [
            "Metrics describe the supplied labels and rankings, not acceptance probability.",
            "The evaluator cannot verify temporal splits, duplicate exclusion, or label independence.",
        ],
    }
