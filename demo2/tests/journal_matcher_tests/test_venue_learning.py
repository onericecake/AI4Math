import copy
import json

import pytest

from journal_matcher.venue_learning import (VenueModel, article_text, balanced_order,
    freeze_venue_corpus, ranking_metrics)


def dataset():
    journals = [{'journal_id': str(i), 'name': 'Journal %s' % i} for i in range(3)]
    rows = []
    for journal, subject in zip(journals, ('algebra groups rings ideals modules', 'probability martingales random stochastic paths', 'numerical convergence finite elements solver')):
        for year, count in ((2023, 12), (2024, 4), (2025, 4)):
            for i in range(count):
                identity = '%s-%s-%s' % (journal['journal_id'], year, i)
                rows.append({'article_id': identity, 'doi': '10.1234/' + identity, 'title': subject + ' ' + identity,
                             'abstract': (subject + ' ') * 8 + identity + (' validationcanary' if year == 2024 else ' testcanary' if year == 2025 else ''),
                             'available_date': '%s-01-01' % year, 'year': year, 'journal_id': journal['journal_id'],
                             'collection_field': subject.split()[0], 'collection_scope_group': 'specialist_or_multifield'})
    return {'journals': journals, 'articles': rows}


def test_freeze_groups_versions_excludes_previous_cases_and_refuses_mutation(tmp_path):
    data = dataset()
    first = data['articles'][0]
    data['articles'].append(dict(first, article_id='revision', available_date='2025-01-01', year=2025))
    excluded = [data['articles'][1]]
    snapshot, manifest = freeze_venue_corpus(data, tmp_path, excluded)
    assert all(r['doi'] != first['doi'] for r in snapshot['splits']['train'])
    assert any(r['doi'] == first['doi'] for r in snapshot['splits']['test'])
    assert manifest['audit']['duplicate_versions_removed'] == 1
    assert manifest['audit']['excluded_previous_benchmark_records'] == 1
    assert freeze_venue_corpus(data, tmp_path, excluded)[1] == manifest
    data['articles'][2]['abstract'] += ' changed'
    with pytest.raises(ValueError, match='changed'):
        freeze_venue_corpus(data, tmp_path, excluded)


def test_conflicting_venues_are_quarantined(tmp_path):
    data = dataset()
    data['articles'].append(dict(data['articles'][0], journal_id='1'))
    snapshot, manifest = freeze_venue_corpus(data, tmp_path)
    assert len(snapshot['splits']['quarantine']) == 2
    assert manifest['audit']['conflicting_venue_groups'] == 1


def test_balanced_samples_are_nested_and_deterministic():
    rows = dataset()['articles']
    ordered = balanced_order(rows, 8)
    assert ordered == balanced_order(list(reversed(rows)), 8)
    assert len({r['journal_id'] for r in ordered[:3]}) == 3
    assert len(ordered) == len(rows)


def test_text_allowlist_removes_metadata_and_explicit_venue_strings():
    row = {'title': 'A theorem', 'abstract': '<p>Published in Journal of Example. doi:10.1234/secret https://example.org</p>',
           'authors': ['privateauthor'], 'journal_id': 'secrettarget', 'openalex_primary_topic': 'labelcanary'}
    text = article_text(row, ['Journal of Example'])
    assert not any(s in text for s in ('journal of example', '10.1234', 'example.org', 'privateauthor', 'secrettarget', 'labelcanary'))


def test_metrics_include_missing_targets_and_macro_journal_rates():
    result = ranking_metrics([{'journal_id': 'a'}, {'journal_id': 'a'}, {'journal_id': 'b'}], [['a'], ['b'], ['b']])
    assert result['hit_at_3'] == 2 / 3
    assert result['macro_journal_hit_at_3'] == .75
    assert result['by_journal_id']['a']['n'] == 2


def test_real_training_roundtrip_excludes_holdout_vocabulary_and_runs_cli(tmp_path, capsys):
    pytest.importorskip('sklearn')
    from journal_matcher.venue_experiment import run_venue_experiment
    from journal_matcher.cli import main
    result = run_venue_experiment(dataset(), tmp_path / 'experiment', sizes=(12, 30), alphas=(.001,), weights=(0., .5, 1.))
    assert result['selected_test']['hit_at_3'] == 1.
    model = VenueModel.load(tmp_path / 'experiment/model')
    assert 'testcanary' not in model.vectorizer.vocabulary_
    assert 'validationcanary' not in model.vectorizer.vocabulary_
    sample = dataset()['articles'][0]
    before = model.rank([article_text(sample)])
    model.save(tmp_path / 'copy')
    assert VenueModel.load(tmp_path / 'copy').rank([article_text(sample)]) == before
    with pytest.raises(ValueError, match='No usable'):
        model.recommend('zzqqxx', '')
    input_path = tmp_path / 'input.json'
    input_path.write_text(json.dumps(sample))
    assert main(['recommend-venues', str(input_path), '--venue-model', str(tmp_path / 'copy')]) == 0
    assert 'Historical publication-venue affinity' in capsys.readouterr().out
    with (tmp_path / 'copy/weights.npz').open('ab') as output:
        output.write(b'tamper')
    with pytest.raises(ValueError, match='checksum'):
        VenueModel.load(tmp_path / 'copy')
