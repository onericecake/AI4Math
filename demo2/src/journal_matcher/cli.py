from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import List, Optional

from .catalog import JournalCatalog
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

    catalog = commands.add_parser("catalog", help="Manage the local journal catalog")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    import_json = catalog_commands.add_parser("import-json", help="Import normalized journal/article metadata")
    import_json.add_argument("source", type=Path, nargs="+", help="One or more normalized catalog JSON files to merge")
    import_json.add_argument("--database", type=Path, default=Path("data/journal_catalog.sqlite"))
    counts = catalog_commands.add_parser("counts", help="Show catalog counts")
    counts.add_argument("--database", type=Path, default=Path("data/journal_catalog.sqlite"))
    return parser


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
    if args.primary_msc:
        entry = taxonomy.get(args.primary_msc)
        profile.primary_msc = MSCClassification(normalize_msc_code(args.primary_msc), entry.name if entry else "", "primary", "author-confirmed")
    elif not args.yes:
        shown = profile.primary_msc.code if profile.primary_msc else "unknown"
        answer = input("Primary MSC code [%s] (Enter to keep): " % shown).strip()
        if answer:
            entry = taxonomy.get(answer)
            profile.primary_msc = MSCClassification(normalize_msc_code(answer), entry.name if entry else "", "primary", "author-confirmed")
    if args.secondary_msc:
        profile.secondary_msc = [
            MSCClassification(normalize_msc_code(code), taxonomy.get(code).name if taxonomy.get(code) else "", "secondary", "author-confirmed")
            for code in args.secondary_msc
        ]
    return profile


def run_analysis(args: argparse.Namespace) -> int:
    manuscript = extract_manuscript(args.manuscript)
    taxonomy = MSCTaxonomy.from_json(args.msc) if args.msc else default_taxonomy()
    if not taxonomy.is_complete():
        print("warning: no complete MSC2020 file was supplied; classification coverage is limited")
    with JournalCatalog(args.catalog) as catalog:
        model = HeuristicJSONModel() if args.offline else OpenAIJSONModel(args.model)
        matcher = JournalMatcher(model, taxonomy, catalog)
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
