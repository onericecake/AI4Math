#!/usr/bin/env python3
"""Export the completed experiment's aggregate audit and per-paper predictions."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.experiment, args.output
    summary = json.loads((source / 'summary.json').read_text())
    snapshot = json.loads((source / 'frozen/snapshot.json').read_text())
    journals = {j['journal_id']: j for j in snapshot['journals']}
    runs = output / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    for path in [source / 'summary.json', source / 'protocol.json', source / 'selection.json',
                 source / 'validation-learning-curve.json', source / 'frozen/manifest.json',
                 *sorted(source.glob('test-predictions-*.json'))]:
        shutil.copyfile(path, runs / path.name)
    code_root = Path(__file__).resolve().parents[1] / 'src/journal_matcher'
    hashes = {name: hashlib.sha256((code_root / name).read_bytes()).hexdigest() for name in
              ('openalex_harvest.py', 'venue_learning.py', 'venue_experiment.py', 'corpus.py', 'retrieval.py')}
    (runs / 'implementation-sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    frozen, selected = summary['frozen'], summary['selection']
    test = summary['selected_test']
    pct = lambda v: '%.1f%%' % (100 * v)
    lines = ['# Broad mathematical-field training experiment', '',
             'The validation-selected model puts the observed publication journal in its top three for **%d/%d test papers (%s)**, compared with **%s** for BM25 on the same training references.' % (test['hits_at_3'], test['n'], pct(test['hit_at_3']), pct(summary['baselines']['bm25_max_article']['hit_at_3'])), '',
             'This is a **50-journal title/abstract publication-venue benchmark**. It does not measure acceptance probability, expert suitability, full-registry hybrid accuracy or the LLM explanation stage. The original matching defaults are unchanged.', '',
             '## Data and split', '',
             '- Source: [OpenAlex public metadata](https://help.openalex.org/api/), collected by exact source ISSN for 2020–2025.',
             '- Training: **%s** unique works from 2020–2023; validation: **%s** from 2024; test: **%s** from 2025.' % (frozen['counts']['train'], frozen['counts']['validation'], frozen['counts']['test']),
             '- Duplicate records removed: **%d**; records matching previous benchmark identities excluded: **%d**; quarantined: **%d**.' % (frozen['audit'].get('duplicate_versions_removed', 0), frozen['audit'].get('excluded_previous_benchmark_records', 0), frozen['counts']['quarantine']),
             '- Equal journal/year quotas with availability shortfalls; earliest eligible publication dates. Scope strata are analyst collection categories; OpenAlex topic subfields are machine labels.',
             '- Metadata was observed in 2026. This publication-year split does not reconstruct historical submission-time inputs.', '',
             '## Fixed learning curve', '',
             'All tuning used 2024 validation macro-journal Hit@3. Each row’s selected model was locked before scoring any 2025 test paper. The largest requested 10,000-paper training point uses the actual available training count.', '',
             '| Training papers | Classifier weight | Validation Hit@3 | Test Hit@3 | Test hits | Test macro-journal Hit@3 |',
             '|---:|---:|---:|---:|---:|---:|']
    for row in summary['learning_curve']:
        lines.append('| %d | %.2f | %s | %s | %d/%d | %s |' % (row['training_articles'], row['linear_weight'], pct(row['validation']['hit_at_3']), pct(row['test']['hit_at_3']), row['test']['hits_at_3'], row['test']['n'], pct(row['test']['macro_journal_hit_at_3'])))
    lines += ['', 'Selected training size: **%d**, regularization alpha: **%g**, classifier weight: **%g**. Weight zero uses TF-IDF journal centroids; weight one uses the linear classifier; intermediate weights fuse their ranks.' % (selected['selected_training_articles'], selected['alpha'], selected['linear_weight']), '',
              '## Equal-corpus baselines', '',
              '| Method | Test Hit@1 | Test Hit@3 | MRR |', '|---|---:|---:|---:|']
    for name, metrics in [('Validation-selected model', test), ('BM25 maximum article', summary['baselines']['bm25_max_article']), ('TF-IDF journal centroid', summary['baselines']['tfidf_centroid'])]:
        lines.append('| %s | %s | %s | %.3f |' % (name, pct(metrics['hit_at_1']), pct(metrics['hit_at_3']), metrics['mrr']))
    delta = summary['difference_vs_bm25']
    lines += ['', 'Selected model minus BM25: **%+.1f percentage points**, paired work-bootstrap 95%% interval **[%+.1f, %+.1f] points**. Model Hit@3 Wilson interval: **[%s, %s]**. These intervals describe this convenience sample; they do not establish population-wide accuracy.' % (100 * delta['difference'], 100 * delta['bootstrap_95'][0], 100 * delta['bootstrap_95'][1], *[pct(x) for x in test['hit_at_3_wilson_95']]), '',
              'The BM25 baseline uses the existing BM25 implementation and maximum matching article per journal. It is a text-retrieval baseline, not the full MSC/LLM hybrid. All methods see the same selected training references and 50 candidate journals.', '',
              '## Generalist and specialist strata', '', '| Stratum | Test papers | Selected model Hit@3 | BM25 Hit@3 |', '|---|---:|---:|---:|']
    for group, metrics in test['by_collection_scope_group'].items():
        lines.append('| %s | %d | %s | %s |' % (group.replace('_', ' '), metrics['n'], pct(metrics['hit_at_3']), pct(summary['baselines']['bm25_max_article']['by_collection_scope_group'][group]['hit_at_3'])))
    lines += ['', 'These categories describe the collection design. They are not expert judgments of whether an individual manuscript deserves a broader venue.', '',
              '## Field coverage and performance', '', '| Collection stratum | Training papers | Test papers | Selected model Hit@3 | BM25 Hit@3 |', '|---|---:|---:|---:|---:|']
    for field, metrics in test['by_collection_field'].items():
        n_train = sum(r.get('collection_field') == field for r in snapshot['splits']['train'])
        lines.append('| %s | %d | %d | %s | %s |' % (field.replace('_', ' '), n_train, metrics['n'], pct(metrics['hit_at_3']), pct(summary['baselines']['bm25_max_article']['by_collection_field'][field]['hit_at_3'])))
    lines += ['', 'Per-paper machine-assigned topic subfield breakdowns are in [summary.json](runs/summary.json); these differ from journal-level collection strata.', '',
              '## Per-journal audit', '', '| Journal | Training papers | Test papers | Selected model Hit@3 |', '|---|---:|---:|---:|']
    for jid, metrics in sorted(test['by_journal_id'].items(), key=lambda kv: journals[kv[0]]['name']):
        n_train = sum(r['journal_id'] == jid for r in snapshot['splits']['train'])
        lines.append('| %s | %d | %d | %s |' % (journals[jid]['name'].replace('|', '/'), n_train, metrics['n'], pct(metrics['hit_at_3'])))
    lines += ['', '## Every paper and its three recommendations', '']
    for row in summary['learning_curve']:
        n = row['training_articles']
        lines.append('- [%d-paper model predictions](runs/test-predictions-%d.json): title, DOI/source, actual journal, actual rank and all three recommended journals.' % (n, n))
    lines += ['- [BM25 predictions](runs/test-predictions-bm25.json).', '- [Centroid predictions](runs/test-predictions-centroid.json).',
              '- [Frozen split hashes](runs/manifest.json), [pre-training protocol](runs/protocol.json), [validation selection](runs/selection.json) and [implementation checksums](runs/implementation-sha256.json).', '',
              '## Limits and next priorities', '',
              'More data is useful here only to the extent demonstrated by the fixed learning curve. Publication metadata supplies a single observed venue per work; it cannot reveal all suitable alternatives or the journals that rejected a paper. Generalist journals remain difficult to distinguish from subject text alone.', '',
              'Coverage depends on available abstracts and a fixed candidate list. Publisher formatting, language and publication-era effects may survive text cleaning. DOI/title/work/identical-abstract grouping does not guarantee detection of all rewritten versions, and authors can occur across splits. Future architecture or data changes need another holdout; the reported 2025 set has now been inspected.', '',
              'Prioritize missing abstract coverage in sparse journals, richer pre-submission mathematical content and independently sourced editorial scope evidence. Keep such evidence separate from manuscript-specific expert labels. Do not replace the full-registry default based only on this restricted-candidate result.', '',
              'See [the workflow and reproduction commands](../../BROAD_TRAINING.md). Raw caches, frozen text and model weights are local under `output/journal-training-2026-09-07/`; this report exports metrics, identifiers and predictions without bulk abstracts.', '']
    (output / 'REPORT.md').write_text('\n'.join(lines))
    print(output / 'REPORT.md')


if __name__ == '__main__':
    main()
