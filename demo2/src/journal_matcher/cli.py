from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import List, Optional

from .catalog import JournalCatalog
from .evaluation import evaluate_rankings
from .latex_extract import extract_manuscript
from .llm import HeuristicJSONModel, OpenAIJSONModel
from .msc import MSCTaxonomy, default_taxonomy, normalize_msc_code
from .pipeline import JournalMatcher
from .report import write_report
from .schemas import MSCClassification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Match an unpublished mathematics article to journals")
    commands = parser.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser("analyze", help="Analyze a LaTeX manuscript")
    analyze.add_argument("manuscript", type=Path)
    analyze.add_argument("--catalog", type=Path, default=Path("data/journal_catalog.sqlite"))
    analyze.add_argument("--msc", type=Path, help="Complete MSC2020 JSON file")
    analyze.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-5.5"))
    analyze.add_argument("--offline", action="store_true", help="Use the deterministic smoke-test model instead of an API")
    analyze.add_argument("--central-result", action="append", help="Confirmed result ID; repeat for multiple results")
    analyze.add_argument("--central-text", help="Manually supplied central result when no theorem environment is available")
    analyze.add_argument("--primary-msc", help="Confirmed primary MSC code")
    analyze.add_argument("--secondary-msc", action="append", default=[], help="Confirmed secondary MSC code")
    analyze.add_argument("--yes", action="store_true", help="Accept model proposals without prompts")
    analyze.add_argument("--output-dir", type=Path, default=Path("."))
    _retrieval_arguments(analyze)
    analyze.add_argument("--final-limit", type=int, default=24)

    catalog = commands.add_parser("catalog", help="Manage the local journal catalog")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    import_json = catalog_commands.add_parser("import-json", help="Import normalized journal/article metadata")
    import_json.add_argument("source", type=Path, nargs="+", help="One or more normalized catalog JSON files to merge")
    import_json.add_argument("--database", type=Path, default=Path("data/journal_catalog.sqlite"))
    counts = catalog_commands.add_parser("counts", help="Show catalog counts")
    counts.add_argument("--database", type=Path, default=Path("data/journal_catalog.sqlite"))
    for name in ("coverage", "export"):
        command = catalog_commands.add_parser(name)
        command.add_argument("--database", type=Path, default=Path("data/journal_catalog.sqlite"))
        command.add_argument("--output", type=Path, required=True)
    plan = catalog_commands.add_parser("plan", help="Create a balanced journal/year collection plan")
    plan.add_argument("--source", type=Path, default=Path("data/catalog.example.json"))
    plan.add_argument("--journals", type=int, default=100)
    plan.add_argument("--per-journal", type=int, default=200)
    plan.add_argument("--start-year", type=int, default=2020)
    plan.add_argument("--end-year", type=int, default=2024)
    plan.add_argument("--seed", type=int, default=0)
    plan.add_argument("--output", type=Path, required=True)
    harvest = catalog_commands.add_parser("harvest-crossref", help="Resume a bounded metadata collection plan")
    harvest.add_argument("plan", type=Path)
    harvest.add_argument("--output-dir", type=Path, required=True)
    harvest.add_argument("--mailto", default="")
    harvest.add_argument("--require-abstract", action="store_true")
    openalex = catalog_commands.add_parser("harvest-openalex", help="Resume an ISSN/year OpenAlex abstract collection")
    openalex.add_argument("plan", type=Path)
    openalex.add_argument("--output-dir", type=Path, required=True)

    venues = commands.add_parser("train-venues", help="Train observed-venue affinity with frozen publication-year holdouts")
    venues.add_argument("catalog", type=Path)
    venues.add_argument("--output-dir", type=Path, required=True)
    venues.add_argument("--exclude", type=Path, action="append", default=[], help="JSON list of previous benchmark identities to exclude globally")
    venues.add_argument("--sizes", type=int, nargs="+", default=[1000, 5000, 10000])
    venues.add_argument("--seed", type=int, default=0)
    recommend = commands.add_parser("recommend-venues", help="Recommend three venues using a trained title/abstract model")
    recommend.add_argument("manuscript", type=Path, help="LaTeX manuscript, or JSON with title and abstract")
    recommend.add_argument("--venue-model", type=Path, required=True, help="Trained model directory")
    recommend.add_argument("--k", type=int, default=3)
    recommend.add_argument("--output", type=Path)

    evaluate = commands.add_parser("evaluate", help="Score saved journal rankings against independent labels")
    evaluate.add_argument("cases", type=Path, help="JSON object with a cases list")
    evaluate.add_argument("--k", type=int, default=3)
    evaluate.add_argument("--output", type=Path)
    benchmark = commands.add_parser("benchmark", help="Run the supplied-MSC retrieval benchmark")
    benchmark.add_argument("--dataset", type=Path, required=True)
    benchmark.add_argument("--catalog-json", type=Path, default=Path("data/catalog.example.json"))
    benchmark.add_argument("--msc", type=Path, default=Path("data/msc2020.json"))
    benchmark.add_argument("--output-dir", type=Path, required=True)
    benchmark.add_argument("--strict-temporal", action="store_true")
    benchmark.add_argument("--cutoff")
    benchmark.add_argument("--without-title", action="store_true")
    benchmark.add_argument("--mode", choices=("supplied-msc", "openai", "heuristic"), default="supplied-msc")
    benchmark.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-5.5"))
    benchmark.add_argument("--full-text", action="store_true", help="Use explicitly blinded TeX paths from case records")
    _retrieval_arguments(benchmark)
    split = commands.add_parser("split-corpus", help="Split paper/version groups chronologically")
    split.add_argument("source", type=Path)
    split.add_argument("--train-end", required=True)
    split.add_argument("--validation-end", required=True)
    split.add_argument("--output", type=Path, required=True)
    train = commands.add_parser("train-ranker", help="Train on explicit graded manuscript/journal judgments")
    train.add_argument("dataset", type=Path)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--epochs", type=int, default=200)
    train.add_argument("--seed", type=int, default=0)
    return parser


def _retrieval_arguments(parser):
    parser.add_argument("--retrieval", choices=("hybrid", "focused", "legacy"), default="hybrid",
                        help="hybrid (default), focused (experimental field-share ranking), or legacy")
    parser.add_argument("--candidate-limit", type=int, default=50)
    parser.add_argument("--embedding-model", help="Optional Sentence Transformers model; may download weights")
    parser.add_argument("--embedding-revision", help="Pinned model commit/revision")
    parser.add_argument("--reranker", type=Path, help="Trained pairwise ranker JSON")


def _retrieval_options(args):
    from .retrieval import SentenceTransformerEncoder
    from .rerank import LinearReranker
    if args.candidate_limit <= 0:
        raise ValueError("candidate-limit must be positive")
    if args.retrieval == "legacy" and (args.embedding_model or args.reranker):
        raise ValueError("Embedding and learned ranking require hybrid or focused retrieval")
    encoder = SentenceTransformerEncoder(args.embedding_model, args.embedding_revision) if args.embedding_model else None
    return {"retrieval": args.retrieval, "encoder": encoder,
            "reranker": LinearReranker.load(args.reranker) if args.reranker else None,
            "candidate_limit": args.candidate_limit}


def _select_result_ids(matcher: JournalMatcher, manuscript, args: argparse.Namespace) -> List[str]:
    if args.central_result:
        selected = args.central_result
    else:
        proposal = matcher.propose_central_results(manuscript)
        print("Proposed central results:")
        for item in proposal["candidates"]:
            print("  %s: %s (%s)" % (item.get("result_id"), item.get("reason", ""), item.get("confidence", "")))
        if args.yes:
            selected = [str(item["result_id"]) for item in proposal["candidates"]]
        else:
            answer = input("Confirm result IDs (comma-separated): ").strip()
            selected = [item.strip() for item in answer.split(",") if item.strip()]
            if not selected:
                selected = [str(item["result_id"]) for item in proposal["candidates"]]
    known = {item.result_id for item in manuscript.theorems}
    invalid = [item for item in selected if item not in known]
    if invalid:
        raise ValueError("unknown central result ID(s): " + ", ".join(invalid))
    if not selected and args.central_text:
        return []
    if not selected:
        # A manuscript can be a survey, computational article, or simply use
        # prose instead of theorem environments.  Whole-paper classification
        # does not require selecting a central theorem.
        return []
    return selected


def _confirm_classification(profile, taxonomy: MSCTaxonomy, args: argparse.Namespace):
    def confirmed(code: str, role: str) -> MSCClassification:
        code = normalize_msc_code(code)
        entry = taxonomy.get(code)
        if entry is None or len(code) != 5:
            raise ValueError("expected a detailed MSC code in the loaded taxonomy: %s" % code)
        return MSCClassification(code, entry.name, role, "author-confirmed")

    changed = False
    if args.primary_msc:
        profile.primary_msc = confirmed(args.primary_msc, "primary")
        changed = True
    elif not args.yes:
        shown = profile.primary_msc.code if profile.primary_msc else "unknown"
        answer = input("Primary MSC code [%s] (Enter to keep): " % shown).strip()
        if answer:
            profile.primary_msc = confirmed(answer, "primary")
            changed = True
    if args.secondary_msc:
        profile.secondary_msc = [
            confirmed(code, "secondary")
            for code in args.secondary_msc
        ]
        changed = True
    if changed:
        # Remove stale broad-field proposals after the author's correction.
        detailed = ([profile.primary_msc] if profile.primary_msc else []) + profile.secondary_msc
        broad_codes = list(dict.fromkeys(item.code[:2] for item in detailed))
        profile.broad_fields = [MSCClassification(code, taxonomy.get(code).name if taxonomy.get(code) else "",
                               "primary" if index == 0 else "secondary", "author-confirmed")
                               for index, code in enumerate(broad_codes)]
    return profile


def run_analysis(args: argparse.Namespace) -> int:
    manuscript = extract_manuscript(args.manuscript)
    taxonomy = MSCTaxonomy.from_json(args.msc) if args.msc else default_taxonomy()
    if not taxonomy.is_complete():
        print("warning: no complete MSC2020 file was supplied; classification coverage is limited")
    with JournalCatalog(args.catalog) as catalog:
        model = HeuristicJSONModel() if args.offline else OpenAIJSONModel(args.model)
        matcher = JournalMatcher(model, taxonomy, catalog, **_retrieval_options(args), final_limit=args.final_limit)
        central_ids = _select_result_ids(matcher, manuscript, args)
        central_text = args.central_text or "\n\n".join(item.statement for item in manuscript.theorems if item.result_id in central_ids)
        broad = matcher.classify_broad(manuscript, central_ids, central_text)
        profile = matcher.build_profile(manuscript, central_ids, broad, central_text)
        profile = _confirm_classification(profile, taxonomy, args)
        candidates = matcher.candidates(profile)
        field_profiles = matcher.profile_journals(profile, candidates)
        report = matcher.match(profile, candidates, field_profiles, central_text)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_report(report, args.output_dir / "report.md", args.output_dir / "report.json")
        print("Wrote %s and %s" % (args.output_dir / "report.md", args.output_dir / "report.json"))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from .harvest import atomic_json
        if args.command == "recommend-venues":
            from .venue_learning import VenueModel
            if args.manuscript.suffix.lower() == '.json':
                manuscript = json.loads(args.manuscript.read_text())
                title, abstract = manuscript.get('title', ''), manuscript.get('abstract', '')
            else:
                manuscript = extract_manuscript(args.manuscript)
                title, abstract = manuscript.title, manuscript.abstract
            result = VenueModel.load(args.venue_model).recommend(title, abstract, args.k)
            if args.output:
                atomic_json(args.output, result)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if args.command == "train-venues":
            from .venue_experiment import run_venue_experiment
            excluded = []
            for source in args.exclude:
                values = json.loads(source.read_text())
                if not isinstance(values, list):
                    raise ValueError('--exclude must contain a JSON list of article identities')
                excluded.extend(values)
            result = run_venue_experiment(json.loads(args.catalog.read_text()), args.output_dir, excluded, args.sizes, seed=args.seed)
            print(json.dumps({'counts': result['frozen']['counts'], 'selection': result['selection'],
                              'test_hit_at_3': result['selected_test']['hit_at_3'],
                              'bm25_test_hit_at_3': result['baselines']['bm25_max_article']['hit_at_3']}, indent=2))
            return 0
        if args.command == "catalog" and args.catalog_command == "harvest-openalex":
            from .openalex_harvest import harvest_openalex
            result = harvest_openalex(json.loads(args.plan.read_text()), args.output_dir)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "train-ranker":
            from .rerank import train_ranker
            ranker = train_ranker(json.loads(args.dataset.read_text()), epochs=args.epochs, seed=args.seed)
            ranker.save(args.output)
            print(json.dumps(ranker.metadata, indent=2))
            return 0
        if args.command == "split-corpus":
            from .corpus import temporal_split
            data = json.loads(args.source.read_text())
            records = data.get("articles", data.get("rows")) if isinstance(data, dict) else data
            if not isinstance(records, list):
                raise ValueError("Expected an article list or an object with articles/rows")
            result = temporal_split(records, args.train_end, args.validation_end)
            result = {split: [{**row, "split": split} for row in rows] for split, rows in result.items()}
            atomic_json(args.output, result)
            print(json.dumps({name: len(rows) for name, rows in result.items()}))
            return 0
        if args.command == "benchmark":
            from .experiments import benchmark_retrieval
            cases = json.loads((args.dataset / "cases.json").read_text())
            for case in cases:
                if case.get("manuscript_path"):
                    case["manuscript_path"] = str((args.dataset / case["manuscript_path"]).resolve())
            factory = (lambda: OpenAIJSONModel(args.model)) if args.mode == "openai" else HeuristicJSONModel if args.mode == "heuristic" else None
            result = benchmark_retrieval(json.loads(args.catalog_json.read_text()),
                cases, json.loads((args.dataset / "labels.json").read_text()),
                json.loads((args.dataset / "supplied-msc.json").read_text()) if (args.dataset / "supplied-msc.json").exists() else [], MSCTaxonomy.from_json(args.msc), args.output_dir,
                cutoff=args.cutoff, strict_temporal=args.strict_temporal, without_title=args.without_title,
                model_factory=factory, full_text=args.full_text, **_retrieval_options(args))
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "catalog" and args.catalog_command == "plan":
            from .harvest import collection_plan
            result = collection_plan(json.loads(args.source.read_text()), args.journals, args.per_journal, args.start_year, args.end_year, args.seed)
            atomic_json(args.output, result)
            print(json.dumps({"journals": len(result["journals"]), "maximum_articles": result["maximum_articles"]}))
            return 0
        if args.command == "catalog" and args.catalog_command == "harvest-crossref":
            from .harvest import CrossrefClient, harvest_crossref
            result = harvest_crossref(json.loads(args.plan.read_text()), args.output_dir, CrossrefClient(args.mailto), args.require_abstract)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "catalog" and args.catalog_command in {"coverage", "export"}:
            with JournalCatalog(args.database) as catalog:
                result = catalog.coverage() if args.catalog_command == "coverage" else catalog.export_data()
                atomic_json(args.output, result)
                print("Wrote " + str(args.output))
            return 0
        if args.command == "evaluate":
            data = json.loads(args.cases.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("evaluation JSON must be an object with a cases list")
            result = evaluate_rankings(data.get("cases"), args.k)
            output = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(output + "\n", encoding="utf-8")
            print(output)
            return 0
        if args.command == "catalog" and args.catalog_command == "import-json":
            with JournalCatalog(args.database) as catalog:
                imported = sum(catalog.import_json(source) for source in args.source)
                print(json.dumps({"journals_imported": imported, "sources": len(args.source), "counts": catalog.counts()}, indent=2))
            return 0
        if args.command == "catalog" and args.catalog_command == "counts":
            with JournalCatalog(args.database) as catalog:
                print(json.dumps(catalog.counts(), indent=2))
            return 0
        return run_analysis(args)
    except (FileNotFoundError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print("error: %s" % error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
