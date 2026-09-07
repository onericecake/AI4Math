#!/usr/bin/env python3
"""Collect the fixed public-metadata experiment; rerunning resumes its checkpoint."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from journal_matcher.openalex_harvest import harvest_openalex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=Path(__file__).resolve().parents[1] / 'data/broad-training-2026-09-07/collection-plan.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(harvest_openalex(json.loads(args.plan.read_text()), args.output), indent=2))


if __name__ == '__main__':
    main()
