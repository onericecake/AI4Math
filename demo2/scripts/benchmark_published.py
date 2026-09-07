"""Reproducible retrospective benchmark; publication labels never enter prompts.

Run --help for inputs. The supplied-MSC mode tests retrieval/ranking only and
must not be described as an end-to-end language-model evaluation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalized_title(value):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower())


def normalized_doi(value):
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value or "").strip().lower()).rstrip(" .")


def prepare_catalog(catalog, cases, labels, sample_only=False):
    """Remove all target examples before importing/recomputing any statistics.

    Imported aggregate counts have no document lineage. They are retained in
    the registry track and explicitly removed in the sample-only ablation.
    """
    titles = {normalized_title(c["title"]) for c in cases}
    titles.update(normalized_title(t) for c in cases for t in c.get("alternate_titles", []))
    dois = {normalized_doi(c["doi"]) for c in labels if c.get("doi")}
    arxiv_ids = {c["arxiv_id"] for c in cases if c.get("arxiv_id")}
    kept, excluded = [], []
    for article in catalog.get("articles", []):
        doi = normalized_doi(article.get("doi"))
        identifiers = " ".join(str(article.get(k) or "") for k in ("source_url", "article_id", "arxiv_id"))
        duplicate = (doi and doi in dois) or normalized_title(article.get("title", "")) in titles
        duplicate = duplicate or any(re.search(r"(?<!\d)" + re.escape(a) + r"(?:v\d+)?(?!\d)", identifiers) for a in arxiv_ids)
        (excluded if duplicate else kept).append(article)
    result = dict(catalog, articles=kept)
    if sample_only:
        result["journal_msc_stats"] = []
    return result, excluded


class RecordingModel:
    def __init__(self, backend, directory):
        self.backend = backend
        self.model = getattr(backend, "model", type(backend).__name__)
        self.directory = directory
        self.index = 0

    def complete_json(self, prompt):
        self.index += 1
        record = {"model": self.model, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "prompt": prompt}
        path = self.directory / ("call-%03d.json" % self.index)
        # Persist attempted calls too; errors must not silently remove cases.
        write(path, record)
        try:
            record["response"] = self.backend.complete_json(prompt)
        except Exception as error:
            record["error_type"] = type(error).__name__
            write(path, record)
            raise
        write(path, record)
        return record["response"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Directory containing cases.json, labels.json, supplied-msc.json")
    parser.add_argument("--output", type=Path, required=True, help="New run directory; refuses to overwrite")
    parser.add_argument("--framework-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mode", choices=("heuristic", "supplied-msc", "openai"), required=True)
    parser.add_argument("--model", help="Required for openai mode; recorded in manifest")
    parser.add_argument("--sample-only", action="store_true", help="Remove untraceable imported MSC aggregate counts")
    parser.add_argument("--without-title", action="store_true")
    parser.add_argument("--primary-only", action="store_true", help="Supplied-MSC diagnostic with secondary fields removed")
    args = parser.parse_args(argv)
    if args.mode == "openai" and not args.model:
        parser.error("--model is required for openai mode")
    if args.primary_only and args.mode != "supplied-msc":
        parser.error("--primary-only requires supplied-msc mode")
    root = args.framework_root.resolve()
    sys.path.insert(0, str(root / "src"))
    from journal_matcher.catalog import JournalCatalog
    from journal_matcher.evaluation import evaluate_rankings
    from journal_matcher.llm import HeuristicJSONModel, OpenAIJSONModel
    from journal_matcher.msc import MSCTaxonomy
    from journal_matcher.pipeline import JournalMatcher, _tokens
    from journal_matcher.schemas import ArticleProfile, ExtractedManuscript, MSCClassification

    cases, labels = read(args.dataset / "cases.json"), read(args.dataset / "labels.json")
    supplied = {c["paper_id"]: c for c in read(args.dataset / "supplied-msc.json")}
    case_ids, label_ids = [c["paper_id"] for c in cases], [c["paper_id"] for c in labels]
    if len(set(case_ids)) != len(case_ids) or len(set(label_ids)) != len(label_ids) or set(case_ids) != set(label_ids):
        raise ValueError("Cases and labels must have identical, unique paper IDs")
    original = read(root / "data/catalog.example.json")
    cleaned, excluded = prepare_catalog(original, cases, labels, args.sample_only)
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output / "catalog.json", cleaned)
    write(args.output / "exclusions.json", excluded)
    tax = MSCTaxonomy.from_json(root / "data/msc2020.json")
    predictions = []
    for case in cases:
        paper_id = case["paper_id"]
        folder = args.output / paper_id
        folder.mkdir()
        # Whitelist only content; no source paths, authors, DOIs, venues, or
        # author MSC labels are exposed to the end-to-end model.
        manuscript = ExtractedManuscript(source_path="blinded-input", title="" if args.without_title else case["title"], abstract=case["abstract"])
        write(folder / "input.json", manuscript.to_dict())
        backend = OpenAIJSONModel(args.model) if args.mode == "openai" else HeuristicJSONModel()
        model = RecordingModel(backend, folder)
        with JournalCatalog(folder / "catalog.sqlite") as catalog:
            catalog.import_json(args.output / "catalog.json")
            matcher = JournalMatcher(model, tax, catalog)
            # Preserve this pilot's original protocol when running against a
            # newer checkout. The `journal-match benchmark` command evaluates
            # the new hybrid retrieval separately.
            if hasattr(matcher, "retriever"):
                matcher.retriever = None
                matcher.final_limit = 12
            if args.mode == "supplied-msc":
                codes = supplied[paper_id]["msc_codes"]
                if args.primary_only:
                    codes = codes[:1]
                if not codes or any(tax.get(c) is None for c in codes):
                    raise ValueError("Invalid supplied MSC codes for " + paper_id)
                def classification(code, role):
                    return MSCClassification(code=code, name=tax.get(code).name, role=role, confidence="medium", evidence=[supplied[paper_id]["provenance"]])
                profile = ArticleProfile(
                    broad_fields=[classification(c, "secondary") for c in dict.fromkeys(code[:2] for code in codes)],
                    primary_msc=classification(codes[0], "primary"),
                    secondary_msc=[classification(c, "secondary") for c in codes[1:]],
                    keywords=sorted(_tokens(manuscript.title + " " + manuscript.abstract)),
                    uncertainties=["Supplied-MSC retrieval diagnostic; technical depth and audience breadth left unknown."])
            else:
                # Abstract-only cases contain no theorem environments. Use the
                # framework's empty-result path; do not invent confirmed theorems.
                central = matcher.propose_central_results(manuscript)
                broad = matcher.classify_broad(manuscript, [])
                profile = matcher.build_profile(manuscript, [], broad)
                write(folder / "central-proposal.json", central)
                write(folder / "broad.json", broad)
            codes = ([profile.primary_msc.code] if profile.primary_msc else []) + [c.code for c in profile.secondary_msc + profile.broad_fields]
            pool = catalog.find_candidates(codes, limit=None)
            candidates = matcher.candidates(profile, limit=24)
            if args.mode == "supplied-msc":
                final_pool = matcher.rank_candidates(profile, candidates, [])[:12]
                recommendations = [{"journal_id": c.journal_id, "journal_name": c.name,
                                    "fit": "subject-only ranking diagnostic; editorial fit unverified",
                                    "match_score": c.match_score} for c in final_pool[:3]]
            else:
                fields = matcher.profile_journals(profile, candidates)
                report = matcher.match(profile, candidates, fields)
                write(folder / "report.json", report.to_dict())
                final_pool = report.ranked_candidates
                recommendations = [r.to_dict() for r in report.recommendations]
            write(folder / "profile.json", profile.to_dict())
            write(folder / "candidates.json", [c.to_dict() for c in candidates])
            all_ranked = matcher.rank_candidates(profile, pool, [])
            predictions.append({"paper_id": paper_id, "primary_msc": profile.primary_msc.code if profile.primary_msc else None,
                                "broad_msc": [c.code for c in profile.broad_fields],
                                "recommendations": recommendations,
                                "msc_pool_ids": [c.journal_id for c in pool],
                                "full_preprofile_ranking": [c.journal_id for c in all_ranked],
                                "candidate_journal_ids": [c.journal_id for c in candidates],
                                "final_pool_ids": [c.journal_id for c in final_pool],
                                "candidate_with_abstract_count": sum(any(a.abstract.strip() for a in c.representative_articles) for c in candidates),
                                "candidate_with_article_count": sum(bool(c.representative_articles) for c in candidates)})
        print(paper_id + ": " + "; ".join(r["journal_name"] for r in recommendations), flush=True)

    # Join the true publication venues only after every prediction is saved.
    write(args.output / "predictions.json", predictions)
    truth = {c["paper_id"]: c for c in labels}
    evaluation_cases, rows = [], []
    for pred in predictions:
        label = truth[pred["paper_id"]]
        target = label["actual_journal_id"]
        ranking = [r["journal_id"] for r in pred["recommendations"]]
        evaluation_cases.append({"paper_id": pred["paper_id"], "relevant_journal_ids": [target], "ranked_journal_ids": ranking,
                                 "candidate_journal_ids": pred["candidate_journal_ids"]})
        rank = ranking.index(target) + 1 if target in ranking else None
        poolrank = pred["full_preprofile_ranking"].index(target) + 1 if target in pred["full_preprofile_ranking"] else None
        rows.append(dict(paper_id=pred["paper_id"], actual_journal=label["actual_journal"],
                         recommended_1=next((r["journal_name"] for r in pred["recommendations"][:1]), "ABSTAIN"),
                         recommended_2=next((r["journal_name"] for r in pred["recommendations"][1:2]), ""),
                         recommended_3=next((r["journal_name"] for r in pred["recommendations"][2:3]), ""),
                         actual_rank=rank, actual_preprofile_rank=poolrank,
                         msc_pool=target in pred["msc_pool_ids"], candidates_24=target in pred["candidate_journal_ids"],
                         final_pool_12=target in pred["final_pool_ids"], primary_msc=pred["primary_msc"]))
    evaluation = evaluate_rankings(evaluation_cases, k=3)
    n = len(rows)
    evaluation["stage_recall"] = {key: sum(r[key] for r in rows) / n for key in ("msc_pool", "candidates_24", "final_pool_12")}
    evaluation["top1_accuracy"] = sum(r["actual_rank"] == 1 for r in rows) / n
    evaluation["full_three_coverage"] = sum(len(p["recommendations"]) == 3 for p in predictions) / n
    write(args.output / "evaluation-cases.json", evaluation_cases)
    write(args.output / "evaluation.json", evaluation)
    with (args.output / "comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    tracked = list((root / "src/journal_matcher").glob("*.py")) + [root / "data/catalog.example.json", root / "data/msc2020.json"]
    manifest = {"mode": args.mode, "model": model.model if args.mode != "supplied-msc" else "none; frozen deterministic ranker",
                "sample_only": args.sample_only, "without_title": args.without_title, "primary_only": args.primary_only, "input_kind": "title-and-abstract",
                "excluded_article_count": len(excluded), "framework_root": str(root),
                "framework_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked},
                "dataset_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.dataset.glob("*.json")},
                "limitations": ["Convenience sample of 12 publications; no inference to population accuracy.",
                                "Publication is one observed positive, not the only suitable venue; no acceptance probability.",
                                "Latest abstracts and current registry statistics do not establish temporal isolation.",
                                "Abstract inputs do not test TeX extraction, full-paper profiling, or theorem confirmation.",
                                "The heuristic backend is a smoke-test fixture, not a trained editorial model.",
                                "Supplied-MSC mode bypasses model classification and journal-field profiling; it measures retrieval/ranking only."]}
    write(args.output / "manifest.json", manifest)
    print(json.dumps(evaluation["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
