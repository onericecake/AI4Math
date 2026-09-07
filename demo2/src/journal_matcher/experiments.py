"""Leakage-aware retrieval benchmarks and blinded expert-label exports."""
from __future__ import annotations

import json
import hashlib
import math
import random
import re
from pathlib import Path

from .catalog import JournalCatalog
from .corpus import fingerprint, select_reference_corpus, identifiers, duplicate_groups
from .evaluation import evaluate_rankings
from .harvest import atomic_json
from .pipeline import JournalMatcher
from .retrieval import profile_text
from .schemas import ArticleProfile, ExtractedManuscript, MSCClassification


class RecordedModel:
    def __init__(self, backend, directory):
        self.backend, self.directory = backend, directory
        self.model = getattr(backend, "model", type(backend).__name__)
        self.calls = 0

    def complete_json(self, prompt):
        self.calls += 1
        path = self.directory / ("call-%03d.json" % self.calls)
        record = {"model": self.model, "prompt": prompt, "prompt_sha256": fingerprint(prompt)}
        atomic_json(path, record)
        try:
            value = self.backend.complete_json(prompt)
        except Exception as error:
            atomic_json(path, {**record, "error_type": type(error).__name__})
            raise
        atomic_json(path, {**record, "response": value})
        return value


def supplied_profile(case, codes, taxonomy, without_title=False):
    def classification(code, role):
        entry = taxonomy.get(code)
        if not entry:
            raise ValueError("Unknown supplied MSC: " + code)
        return MSCClassification(code, entry.name, role, "supplied")
    return ArticleProfile(
        retrieval_text=("" if without_title else case["title"]) + "\n" + case["abstract"],
        primary_msc=classification(codes[0], "primary") if codes else None,
        secondary_msc=[classification(c, "secondary") for c in codes[1:]],
        broad_fields=[classification(c, "secondary") for c in dict.fromkeys(c[:2] for c in codes)])


def bootstrap_hit_interval(cases, k=3, seed=0, samples=1000):
    """Descriptive manuscript bootstrap; convenience samples stay nonrandom."""
    hits = [int(bool(set(c["ranked_journal_ids"][:k]) & set(c["relevant_journal_ids"]))) for c in cases]
    rng = random.Random(seed)
    values = sorted(sum(rng.choices(hits, k=len(hits))) / len(hits) for _ in range(samples))
    return {"low": values[int(.025 * samples)], "high": values[min(samples - 1, int(.975 * samples))],
            "unit": "manuscript", "method": "percentile bootstrap", "seed": seed,
            "warning": "Descriptive only; small/all-zero samples can give degenerate intervals. Not a population guarantee."}


def benchmark_retrieval(data, cases, labels, classifications, taxonomy, output: Path,
                        retrieval="hybrid", cutoff=None, strict_temporal=False, without_title=False,
                        encoder=None, reranker=None, candidate_limit=50, model_factory=None, full_text=False):
    """Benchmark supplied-code retrieval; no classification accuracy claim."""
    case_ids = [c["paper_id"] for c in cases]
    label_ids = [c["paper_id"] for c in labels]
    if not cases or len(set(case_ids)) != len(cases) or len(set(label_ids)) != len(labels) or set(case_ids) != set(label_ids):
        raise ValueError("Cases and labels must have identical unique IDs")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in case_ids):
        raise ValueError("paper_id must contain only letters, digits, underscores or hyphens")
    if cutoff and not strict_temporal:
        raise ValueError("--cutoff requires --strict-temporal; refusing to silently ignore it")
    if full_text and any(not c.get("blinded") or not c.get("manuscript_path") for c in cases):
        raise ValueError("Full-text cases require manuscript_path and an explicit blinded=true declaration")
    by_id = {c["paper_id"]: c for c in classifications}
    if not model_factory and set(by_id) != set(case_ids):
        raise ValueError("Each input requires a supplied-MSC record (possibly with no codes)")
    if strict_temporal and not cutoff and any(not c.get("submission_date") for c in cases):
        raise ValueError("Strict temporal evaluation needs --cutoff or submission_date for every paper")
    if output.exists():
        raise ValueError("Use a new benchmark output directory")
    output.mkdir(parents=True)
    truth = {l["paper_id"]: l for l in labels}
    targets = [{**case, "doi": truth[case["paper_id"]].get("doi")} for case in cases]
    work_groups = {}
    for group in duplicate_groups(targets):
        work_id = fingerprint(sorted(set().union(*(identifiers(targets[i]) for i in group))))
        for i in group:
            work_groups[cases[i]["paper_id"]] = work_id
    predictions, audit, annotation_rows = [], [], []
    class NoModel:
        def complete_json(self, prompt):
            raise AssertionError("Retrieval diagnostic must not invoke a language model")
    for position, case in enumerate(cases):
        profile = ArticleProfile() if model_factory else supplied_profile(case, by_id[case["paper_id"]]["msc_codes"], taxonomy, without_title)
        folder = output / case["paper_id"]
        folder.mkdir()
        if full_text:
            from .latex_extract import extract_manuscript
            manuscript = extract_manuscript(case["manuscript_path"])
            if without_title:
                manuscript.title = ""
            profile.retrieval_text = "\n".join([manuscript.title, manuscript.abstract, manuscript.introduction] + [t.statement for t in manuscript.theorems])
        else:
            manuscript = ExtractedManuscript(source_path="blinded-input", title="" if without_title else case["title"], abstract=case["abstract"])
        atomic_json(folder / "input.json", manuscript.to_dict())
        case_cutoff = cutoff or case.get("submission_date") if strict_temporal else None
        reference, exclusions = select_reference_corpus(data, targets, case_cutoff)
        # Never replay locally-derived aggregate counts after removing targets.
        reference["journal_msc_stats"] = [s for s in reference.get("journal_msc_stats", []) if s.get("source", "imported") == "imported"]
        with JournalCatalog(":memory:") as catalog:
            for journal in reference["journals"]:
                catalog.upsert_journal(journal)
            for article in reference["articles"]:
                catalog.upsert_article(article)
            catalog.rebuild_statistics()
            for stat in reference.get("journal_msc_stats", []):
                catalog.set_stat(stat["journal_id"], stat["msc_prefix"], stat["article_count"], stat.get("share", 0))
            backend = RecordedModel(model_factory(), folder) if model_factory else NoModel()
            matcher = JournalMatcher(backend, taxonomy, catalog, retrieval=retrieval, encoder=encoder, reranker=reranker, candidate_limit=candidate_limit)
            if model_factory:
                central = matcher.propose_central_results(manuscript)
                selected = case.get("central_result_ids", [c["result_id"] for c in central["candidates"]])
                if not set(selected) <= {t.result_id for t in manuscript.theorems}:
                    raise ValueError("Unknown central result ID for " + case["paper_id"])
                broad = matcher.classify_broad(manuscript, selected)
                profile = matcher.build_profile(manuscript, selected, broad)
                atomic_json(folder / "profile.json", profile.to_dict())
                atomic_json(folder / "central-results.json", {"proposal": central, "selected": selected, "author_supplied": "central_result_ids" in case})
            # Preserve lexical inputs for the legacy comparison as well.
            from .pipeline import _tokens
            if not model_factory:
                profile.keywords = sorted(_tokens(profile.retrieval_text))
            ranking = matcher.candidates(profile, limit=max(100, candidate_limit))
            shortlist = ranking[:candidate_limit]
            recommendations = [{"journal_id": c.journal_id, "name": c.name, "score": c.match_score,
                                "status": "subject-only lead; editorial fit unverified"} for c in shortlist[:3]]
            if model_factory:
                fields = matcher.profile_journals(profile, shortlist)
                report = matcher.match(profile, shortlist, fields)
                atomic_json(folder / "report.json", report.to_dict())
                # Preserve raw outputs and evaluate supported advice separately.
                recommendations = [{"journal_id": r.journal_id, "name": r.journal_name, "score": r.match_score, "status": r.fit} for r in report.recommendations]
            predictions.append({"paper_id": case["paper_id"], "ranked_journal_ids": [c["journal_id"] for c in recommendations],
                                "candidate_journal_ids": [c.journal_id for c in shortlist],
                                "ranking_100": [c.journal_id for c in ranking],
                                "recommendations": recommendations})
            atomic_json(output / (case["paper_id"] + "-candidates.json"), [c.to_dict() for c in ranking])
            audit.append({"paper_id": case["paper_id"], **exclusions})
            # Deliberately unjudged and with no historical publication label.
            annotation_rows.append({"paper_id": case["paper_id"], "work_id": work_groups[case["paper_id"]], "title": case["title"], "abstract": case["abstract"],
                                    "available_date": case.get("submission_date"),
                                    "split": "assign-before-training", "candidates": [
                                        {"journal_id": c.journal_id, "name": c.name, "features": {**c.retrieval_scores, "technical_depth": .5, "audience_breadth": .5},
                                         "judged": False, "relevance": None, "reason": ""} for c in shortlist]})
    atomic_json(output / "predictions.json", predictions)
    evaluation_cases = []
    for prediction in predictions:
        label = truth[prediction["paper_id"]]
        relevant = label.get("relevant_journal_ids") or [label["actual_journal_id"]]
        evaluation_cases.append({"paper_id": prediction["paper_id"], "relevant_journal_ids": relevant,
                                 "ranked_journal_ids": prediction["ranked_journal_ids"], "candidate_journal_ids": prediction["candidate_journal_ids"]})
    evaluation = evaluate_rankings(evaluation_cases, 3)
    evaluation["retrieval_recall"] = {str(k): sum(len(set(p["ranking_100"][:k]) & set(c["relevant_journal_ids"])) / len(c["relevant_journal_ids"])
                                               for p, c in zip(predictions, evaluation_cases)) / len(cases) for k in (24, 50, 100)}
    evaluation["bootstrap_hit_at_3"] = bootstrap_hit_interval(evaluation_cases)
    if model_factory:
        supported = [{**c, "ranked_journal_ids": [r["journal_id"] for r in p["recommendations"] if r["status"] in {"strong match", "plausible match"}]} for p, c in zip(predictions, evaluation_cases)]
        evaluation["supported_recommendations"] = evaluate_rankings(supported, 3)
    evaluation["mode"] = backend.model if model_factory else "supplied-MSC retrieval diagnostic; not live-LLM or editorial accuracy"
    atomic_json(output / "evaluation.json", evaluation)
    atomic_json(output / "evaluation-cases.json", evaluation_cases)
    atomic_json(output / "corpus-audit.json", audit)
    atomic_json(output / "annotation-template.json", {"feature_schema_version": 2 if retrieval == "focused" else 1,
                "label_provenance": "unjudged export; requires independent expert annotation", "rows": annotation_rows})
    atomic_json(output / "manifest.json", {"retrieval": retrieval, "strict_temporal": strict_temporal, "cutoff": cutoff,
                "without_title": without_title, "candidate_limit": candidate_limit,
                "input_kind": "blinded-full-text" if full_text else "title-and-abstract",
                "model": backend.model if model_factory else None,
                "embedding_model": encoder.identity if encoder else None, "reranker": fingerprint(reranker.weights) if reranker else None,
                "corpus_sha256": fingerprint(data), "cases_sha256": fingerprint(cases), "labels_sha256": fingerprint(labels),
                "classifications_sha256": fingerprint(classifications)})
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["framework_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in Path(__file__).parent.glob("*.py")}
    manifest["input_sha256"] = {case["paper_id"]: hashlib.sha256((output / case["paper_id"] / "input.json").read_bytes()).hexdigest() for case in cases}
    atomic_json(manifest_path, manifest)
    return evaluation
