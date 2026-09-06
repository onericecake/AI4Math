import json
import math

import pytest

from journal_matcher.cli import main
from journal_matcher.evaluation import evaluate_rankings


def test_multilabel_ranking_and_abstention_metrics():
    result = evaluate_rankings([
        {"paper_id": "a", "relevant_journal_ids": ["j1", "j2"], "candidate_journal_ids": ["j1", "j2", "j3"], "ranked_journal_ids": ["j3", "j1", "j2"]},
        {"paper_id": "b", "relevant_journal_ids": ["j4"], "candidate_journal_ids": [], "ranked_journal_ids": []},
    ], k=2)
    metrics = result["metrics"]
    assert metrics["hit_rate_at_k"] == 0.5
    assert metrics["recall_at_k"] == 0.25
    assert metrics["mrr_at_k"] == 0.25
    assert metrics["ndcg_at_k"] == pytest.approx((1 / math.log2(3)) / (1 + 1 / math.log2(3)) / 2)
    assert metrics["candidate_recall"] == 0.5
    assert metrics["recommendation_coverage"] == 0.5


def test_absent_candidate_pool_is_unknown_not_zero():
    result = evaluate_rankings([{"paper_id": "a", "relevant_journal_ids": ["j"], "ranked_journal_ids": ["j"]}])
    assert result["metrics"]["candidate_recall"] is None
    assert result["candidate_recall_case_count"] == 0


@pytest.mark.parametrize("cases", [
    [],
    [{"paper_id": "a", "relevant_journal_ids": [], "ranked_journal_ids": []}],
    [{"paper_id": "a", "relevant_journal_ids": ["j"], "ranked_journal_ids": ["j", "j"]}],
    [{"paper_id": "a", "relevant_journal_ids": ["j"], "ranked_journal_ids": ["j"], "candidate_journal_ids": []}],
])
def test_invalid_evaluations_are_rejected(cases):
    with pytest.raises(ValueError):
        evaluate_rankings(cases)


def test_evaluation_cli_writes_metrics(tmp_path):
    output = tmp_path / "metrics.json"
    assert main(["evaluate", "examples/evaluation.example.json", "--k", "3", "--output", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["case_count"] == 2
    assert result["metrics"]["recall_at_k"] == 0.5
    assert main(["evaluate", "examples/evaluation.example.json", "--k", "0"]) == 2
