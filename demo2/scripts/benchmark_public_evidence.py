"""Reproduce the public-evidence ablation without network access or model calls.

Run from demo2: python scripts/benchmark_public_evidence.py --output-dir PATH
Existing outputs are never overwritten. Ranking weights are not trained here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO / 'src'))
from journal_matcher.catalog import JournalCatalog
from journal_matcher.corpus import duplicate_groups, fingerprint, select_reference_corpus
from journal_matcher.experiments import benchmark_retrieval
from journal_matcher.harvest import atomic_json
from journal_matcher.msc import MSCTaxonomy


def prepare(output):
    base = json.loads((DEMO / 'data/catalog.example.json').read_text())
    additions = json.loads((DEMO / 'data/public-evidence-2026-09-07/catalog.additions.json').read_text())
    taxonomy = MSCTaxonomy.from_json(DEMO / 'data/msc2020.json')
    for article in additions['articles']:
        if not all(taxonomy.get(c) for c in article['msc_codes']):
            raise ValueError('Unvalidated MSC code in additions')
        if not all(article.get(k) for k in ['doi', 'abstract', 'authors', 'source_url', 'license_url', 'metadata_available_date']):
            raise ValueError('Missing article evidence/provenance')
    with JournalCatalog(':memory:') as catalog:
        catalog._import_data(base)
        catalog._import_data(additions)
        enriched = catalog.export_data()
        coverage = catalog.coverage()
    atomic_json(output / 'catalog.enriched.json', enriched)
    atomic_json(output / 'coverage.json', coverage)
    cases, labels, msc = [], [], []
    for name in ('pilot', 'validation'):
        folder = DEMO / 'benchmarks/focused-2026-09-07' / name
        cases += json.loads((folder / 'cases.json').read_text())
        labels += json.loads((folder / 'labels.json').read_text())
        msc += json.loads((folder / 'supplied-msc.json').read_text())
    labels_by_id = {label['paper_id']: label for label in labels}
    target_records = [{**c, 'doi': labels_by_id[c['paper_id']].get('doi')} for c in cases]
    overlaps = [g for g in duplicate_groups(additions['articles'] + target_records)
                if any(i < len(additions['articles']) for i in g) and any(i >= len(additions['articles']) for i in g)]
    if overlaps:
        raise ValueError('Public evidence duplicates an existing benchmark target')
    old = (cases, labels, msc)
    # Fresh diagnostic selected before scoring. Every new 2024 paper with
    # publisher-supplied usable MSC codes is a target, across four venues.
    fresh_articles = sorted([a for a in additions['articles'] if a['year'] == 2024 and a['msc_codes']], key=lambda a: a['doi'])
    fresh = ([], [], [])
    for i, article in enumerate(fresh_articles, 1):
        paper_id = 'online%02d' % i
        fresh[0].append({'paper_id': paper_id, 'title': article['title'], 'abstract': article['abstract'],
                         'input_kind': 'publisher title and abstract, retrospectively blinded venue',
                         'source_url': article['source_url']})
        fresh[1].append({'paper_id': paper_id, 'actual_journal_id': article['journal_id'], 'doi': article['doi']})
        fresh[2].append({'paper_id': paper_id, 'msc_codes': article['msc_codes'],
                         'provenance': 'publisher display order; first valid code used as query primary, original primary/secondary roles unspecified'})
    # Both experiments use a common union of targets as exclusions. This also
    # removes connected DOI/title/preprint versions and derived counts.
    all_targets = target_records + fresh_articles
    base_safe, base_audit = select_reference_corpus(base, all_targets)
    enriched_safe, enriched_audit = select_reference_corpus(enriched, all_targets)
    for name, dataset in [('existing36', old), ('new20', fresh)]:
        for filename, rows in zip(['cases', 'labels', 'supplied-msc'], dataset):
            atomic_json(output / 'datasets' / name / (filename + '.json'), rows)
    atomic_json(output / 'manifest.json', {
        'base_sha256': fingerprint(base), 'additions_sha256': fingerprint(additions),
        'base_exclusions': base_audit, 'enriched_exclusions': enriched_audit,
        'target_count': len(all_targets), 'new_target_count': len(fresh_articles),
        'all_targets_excluded_from_all_runs': True,
        'new_reference_article_count': len(enriched_safe['articles']) - len(base_safe['articles']),
        'ranker_training': False, 'policy': 'Source-data ablation; identical fixed ranking weights; all candidate journals remain eligible.',
        'limitations': ['Convenience samples; six open-access journals only.',
            'Current scopes/metadata and undated imported aggregate MSC counts remain: not a historical submission-time simulation.',
            'Published venue is one observed outcome, not the only suitable journal or an acceptance probability.',
            'Supplied MSC and abstracts only; no live LLM, proof assessment, or independent expert labels.',
            '2024 targets excluded across every run; retained 2024 references are from AHL/SIGMA, whose pages lacked MSC.',
            'Existing 36 cases have already informed development; new 20 are a first-pass diagnostic, not a representative independent test.']})
    return base_safe, enriched_safe, taxonomy, [('existing36', old), ('new20', fresh)]


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    base, enriched, taxonomy, datasets = prepare(output)
    summaries = []
    for name, (cases, labels, msc) in datasets:
        for strategy in ('hybrid', 'focused'):
            for variant, corpus in [('before', base), ('after', enriched)]:
                directory = output / 'runs' / ('%s-%s-%s' % (name, strategy, variant))
                result = benchmark_retrieval(corpus, cases, labels, msc, taxonomy, directory, retrieval=strategy)
                summary = {'dataset': name, 'retrieval': strategy, 'variant': variant, **result}
                summaries.append(summary)
                print(name, strategy, variant, 'hit@3=', result['metrics']['hit_rate_at_k'], flush=True)
    atomic_json(output / 'summary.json', summaries)
    return summaries


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    run(args.output_dir)
