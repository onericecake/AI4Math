"""Predeclared learning curves and a frozen later-year observed-venue test."""
from __future__ import annotations

import json
import platform
import shutil
from collections import Counter
from pathlib import Path

from .corpus import fingerprint
from .harvest import atomic_json
from .retrieval import BM25
from .venue_learning import (VenueModel, article_text, balanced_order, fit_components,
                             freeze_venue_corpus, ml_dependencies, rank_fusion,
                             ranking_metrics, ranks_from_scores)


def bm25_rankings(training, queries, classes, names):
    """Existing BM25 implementation, max article score per journal, equal corpus."""
    index = BM25([article_text(r, names) for r in training])
    rankings = []
    for row in queries:
        scores = {c: 0.0 for c in classes}
        for i, score in index.scores(article_text(row, names)).items():
            jid = training[i]['journal_id']
            scores[jid] = max(scores[jid], score)
        rankings.append(sorted(classes, key=lambda c: (-scores[c], c)))
    return rankings


def paired_hit_difference(rows, learned, baseline, seed=0, repetitions=2000):
    np, _, _ = ml_dependencies()
    difference = np.array([int(r['journal_id'] in a[:3]) - int(r['journal_id'] in b[:3]) for r, a, b in zip(rows, learned, baseline)])
    rng = np.random.default_rng(seed)
    samples = np.array([rng.choice(difference, len(difference), replace=True).mean() for _ in range(repetitions)])
    return {'difference': float(difference.mean()), 'bootstrap_95': np.quantile(samples, [.025, .975]).tolist(),
            'resampling_unit': 'work', 'paired': True, 'seed': seed, 'repetitions': repetitions,
            'warning': 'Descriptive uncertainty for this convenience sample, not a guarantee across all mathematics.'}


def prediction_rows(records, rankings, journals):
    names = {j['journal_id']: j['name'] for j in journals}
    return [{'article_id': row.get('article_id'), 'doi': row.get('doi'), 'title': row['title'],
             'source_url': row.get('source_url'), 'actual_journal_id': row['journal_id'],
             'actual_journal': names[row['journal_id']], 'actual_rank': ranking.index(row['journal_id']) + 1 if row['journal_id'] in ranking else None,
             'collection_field': row.get('collection_field'), 'evaluation_field': row.get('evaluation_field'),
             'collection_scope_group': row.get('collection_scope_group'),
             'top3': [{'journal_id': c, 'name': names[c]} for c in ranking[:3]]} for row, ranking in zip(records, rankings)]


def run_venue_experiment(data, output_dir, excluded=(), sizes=(1000, 5000, 10000),
                         alphas=(.0001, .001, .01), weights=(0., .25, .5, .75, 1.), seed=0):
    if not sizes or any(type(n) is not int or n < 1 for n in sizes) or not alphas or any(a <= 0 for a in alphas):
        raise ValueError('Positive training sizes and regularization strengths required')
    if not weights or any(not 0 <= w <= 1 for w in weights):
        raise ValueError('Fusion weights must be between zero and one')
    np, _, _ = ml_dependencies()
    import sklearn
    output = Path(output_dir)
    snapshot, manifest = freeze_venue_corpus(data, output / 'frozen', excluded)
    journals, splits = snapshot['journals'], snapshot['splits']
    if any(not splits[s] for s in ('train', 'validation', 'test')):
        raise ValueError('Nonempty train, validation and test sets are required')
    required = {j['journal_id'] for j in journals}
    if any({r['journal_id'] for r in splits[s]} != required for s in ('train', 'validation', 'test')):
        raise ValueError('Every candidate journal must have training, validation and test examples; revise the collection explicitly')
    order = balanced_order(splits['train'], seed)
    actual_sizes = sorted({min(n, len(order)) for n in sizes})
    if actual_sizes[0] < len(journals):
        raise ValueError('Smallest training size must cover every candidate journal')
    protocol = {'schema_version': 1, 'frozen_snapshot_sha256': manifest['snapshot_sha256'],
                'requested_training_sizes': list(sizes), 'actual_training_sizes': actual_sizes,
                'alphas': list(alphas), 'linear_weights': list(weights), 'seed': seed,
                'candidate_journal_ids': sorted(required), 'selection': 'Maximize validation macro-journal hit@3; ties prefer smaller training size, then greater regularization and less classifier weight.',
                'test_policy': 'All model choices locked on validation before any test predictions; report fixed learning-curve models and equal-corpus baselines, no test tuning.',
                'input': 'Title and abstract only, journal names/URLs/DOIs and obvious publisher boilerplate removed.',
                'limitations': ['Observed venue is one positive, not an exhaustive set of suitable journals.',
                               'Candidate set is restricted to the collected journals; not the full registry.',
                               'Publication-year holdout uses present-day metadata and published abstracts.',
                               'Available-abstract convenience sample, earliest eligible dates in each journal/year.',
                               'Scope groups are collection strata and topic subfields are OpenAlex machine labels, not expert judgments.'],
                'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'scikit_learn': sklearn.__version__}}
    protocol_hash = fingerprint(protocol)
    path = output / 'protocol.json'
    if path.exists() and json.loads(path.read_text()) != protocol:
        raise ValueError('Experiment protocol changed; choose a new output directory')
    atomic_json(path, protocol)  # Written before any fitting or test scoring.
    if (output / 'summary.json').exists():
        return json.loads((output / 'summary.json').read_text())
    names = [j['name'] for j in journals]
    validation_text = [article_text(r, names) for r in splits['validation']]
    curve, selected_models = [], []
    for n in actual_sizes:
        training, trials = order[:n], []
        best, best_key, best_metrics = None, None, None
        for alpha in sorted(alphas, reverse=True):
            model = fit_components(training, journals, alpha, seed)
            linear, centroid = model.component_scores(validation_text)
            for weight in sorted(weights):
                rankings = ranks_from_scores(rank_fusion(linear, centroid, weight), model.classes)
                metrics = ranking_metrics(splits['validation'], rankings)
                score = metrics['macro_journal_hit_at_3']
                trials.append({'alpha': alpha, 'linear_weight': weight, 'macro_journal_hit_at_3': score,
                               'hit_at_3': metrics['hit_at_3']})
                key = (score, alpha, -weight)
                if best_key is None or key > best_key:
                    best, best_key, best_metrics = model, key, metrics
                    # One alpha model can be best at several weights; retain the
                    # winning weight separately until every trial is evaluated.
                    best_weight = weight
            print('validation training=%d alpha=%g completed' % (n, alpha), flush=True)
        best.metadata.update(linear_weight=best_weight, protocol_sha256=protocol_hash)
        best.save(output / 'models' / str(n))
        entry = {'training_articles': n, 'training_by_journal': dict(Counter(r['journal_id'] for r in training)),
                 'alpha': best.metadata['alpha'], 'linear_weight': best_weight,
                 'validation': best_metrics, 'trials': trials}
        curve.append(entry)
        selected_models.append(output / 'models' / str(n))
        atomic_json(output / 'validation-learning-curve.json', curve)
    chosen = max(range(len(curve)), key=lambda i: (curve[i]['validation']['macro_journal_hit_at_3'], -curve[i]['training_articles']))
    selection = {'protocol_sha256': protocol_hash, 'selected_training_articles': curve[chosen]['training_articles'],
                 'alpha': curve[chosen]['alpha'], 'linear_weight': curve[chosen]['linear_weight'],
                 'selection_split': 'validation'}
    atomic_json(output / 'selection.json', selection)  # Lock before accessing test text.
    shutil.copytree(selected_models[chosen], output / 'model', dirs_exist_ok=True)
    test_text = [article_text(r, names) for r in splits['test']]
    learned_predictions = None
    for i, model_path in enumerate(selected_models):
        model = VenueModel.load(model_path)
        predictions = model.rank(test_text)
        curve[i]['test'] = ranking_metrics(splits['test'], predictions)
        atomic_json(output / ('test-predictions-%d.json' % curve[i]['training_articles']), prediction_rows(splits['test'], predictions, journals))
        if i == chosen:
            learned_predictions = predictions
    model = VenueModel.load(output / 'model')
    _, centroid = model.component_scores(test_text)
    centroid_predictions = ranks_from_scores(centroid, model.classes)
    print('scoring BM25 baseline on the same training corpus', flush=True)
    bm25_predictions = bm25_rankings(order[:curve[chosen]['training_articles']], splits['test'], model.classes, names)
    baselines = {'tfidf_centroid': ranking_metrics(splits['test'], centroid_predictions),
                 'bm25_max_article': ranking_metrics(splits['test'], bm25_predictions)}
    atomic_json(output / 'test-predictions-bm25.json', prediction_rows(splits['test'], bm25_predictions, journals))
    atomic_json(output / 'test-predictions-centroid.json', prediction_rows(splits['test'], centroid_predictions, journals))
    summary = {'protocol_sha256': protocol_hash, 'frozen': manifest, 'selection': selection,
               'learning_curve': curve, 'selected_test': curve[chosen]['test'], 'baselines': baselines,
               'difference_vs_bm25': paired_hit_difference(splits['test'], learned_predictions, bm25_predictions, seed),
               'difference_vs_centroid': paired_hit_difference(splits['test'], learned_predictions, centroid_predictions, seed),
               'candidate_journals': len(journals), 'limitations': protocol['limitations'],
               'default_changed': False}
    atomic_json(output / 'summary.json', summary)
    # Importable training-only references: validation/test never enter retrieval.
    atomic_json(output / 'training-catalog.json', {'journals': journals, 'articles': order[:curve[chosen]['training_articles']],
                                                  'journal_msc_stats': [], 'provenance': selection})
    return summary
