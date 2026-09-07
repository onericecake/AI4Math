"""Observed-venue learning, kept separate from expert suitability judgments.

Only title/abstract text enters the model. Publication labels, machine-assigned
fields and collection strata are used for sampling/evaluation, never as text.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from .corpus import duplicate_groups, eligible_research, fingerprint, identifiers, normalize_date
from .harvest import atomic_json


def ml_dependencies():
    try:
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import SGDClassifier
    except ImportError as error:
        raise RuntimeError("Venue learning requires the optional 'training' extra: pip install '.[training]'") from error
    return np, TfidfVectorizer, SGDClassifier


def blind_text(text, journal_names=()):
    text = html.unescape(str(text or ''))
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'https?://\S+|\b10\.\d{4,9}/\S+|\barxiv\s*:\s*\S+', ' ', text, flags=re.I)
    text = re.sub(r'(?im)(?:©|copyright)\s*[^\n]*', ' ', text)
    for name in sorted(set(journal_names), key=lambda n: (-len(n), n)):
        if len(name) >= 8:
            text = re.sub(r'(?<!\w)' + re.escape(name) + r'(?!\w)', ' ', text, flags=re.I)
    # These are publisher/formatting cues, not mathematical features.
    text = re.sub(r'\b(?:elsevier|springer|wiley|taylor|francis|abstract|mathjax|texmath|jats)\b', ' ', text, flags=re.I)
    return ' '.join(text.casefold().split())


def article_text(record, names=()):
    # Deliberate allowlist: no author names, source IDs, DOI, MSC or topic labels.
    return blind_text(str(record.get('title', '')) + '\n' + str(record.get('abstract', '')), names)


def freeze_venue_corpus(data, output_dir, excluded=(), train_end='2023-12-31', validation_end='2024-12-31'):
    """Freeze disjoint work groups and quarantine conflicting publication labels."""
    output = Path(output_dir)
    excluded = list(excluded)
    train_end, validation_end = normalize_date(train_end), normalize_date(validation_end)
    if not train_end or not validation_end or train_end >= validation_end:
        raise ValueError('Invalid split cutoffs')
    journals = sorted(data['journals'], key=lambda j: j['journal_id'])
    journal_ids = {j['journal_id'] for j in journals}
    if len(journal_ids) != len(journals):
        raise ValueError('Duplicate candidate journal IDs')
    names = [j['name'] for j in journals]
    records = [dict(r) for r in data['articles']]
    for row in records:
        # Identical abstracts can link records whose title/DOI changed.
        abstract = blind_text(row.get('abstract', ''), names)
        row['identity_keys'] = sorted(identifiers(row) | ({'work:abstract-' + fingerprint(abstract)} if len(abstract.split()) >= 35 else set()))
        if row.get('openalex_id'):
            row['identity_keys'].append('work:' + row['openalex_id'])
    combined = records + list(excluded)
    splits = {s: [] for s in ('train', 'validation', 'test', 'quarantine')}
    audit = Counter()
    for group in duplicate_groups(combined):
        rows = [records[i] for i in group if i < len(records)]
        if not rows:
            continue
        if any(i >= len(records) for i in group):
            audit['excluded_previous_benchmark_records'] += len(rows)
            continue
        dates = [normalize_date(r.get('available_date')) for r in rows]
        valid = all(eligible_research(r) and r.get('journal_id') in journal_ids and
                    len(str(r.get('abstract', '')).split()) >= 35 for r in rows)
        conflict = len({r.get('journal_id') for r in rows}) != 1
        if not all(dates) or not valid or conflict:
            splits['quarantine'].extend(rows)
            audit['conflicting_venue_groups' if conflict else 'invalid_groups'] += 1
            continue
        latest = max(dates)
        destination = 'train' if latest <= train_end else 'validation' if latest <= validation_end else 'test'
        # Keep one text per work, in the latest split required by any version.
        row = dict(max(rows, key=lambda r: (normalize_date(r.get('available_date')), len(r.get('abstract', '')), str(r.get('article_id', '')))))
        row['identity_keys'] = sorted(set().union(*(identifiers(r) for r in rows)))
        row['split_date'] = latest
        splits[destination].append(row)
        audit['duplicate_versions_removed'] += len(rows) - 1
    for rows in splits.values():
        rows.sort(key=lambda r: (r.get('journal_id', ''), r.get('doi', ''), r.get('title', '')))
    snapshot = {'journals': journals, 'splits': splits}
    manifest = {'schema_version': 1, 'source_sha256': fingerprint(data), 'snapshot_sha256': fingerprint(snapshot),
                'exclusions_sha256': fingerprint(list(excluded)), 'train_end': train_end, 'validation_end': validation_end,
                'split_sha256': {s: fingerprint(rows) for s, rows in splits.items()},
                'counts': {s: len(rows) for s, rows in splits.items()}, 'audit': dict(audit),
                'candidate_journals': len(journals),
                'temporal_semantics': 'Publication-year holdout using current metadata, not historical submission-time evidence.',
                'label_semantics': 'Observed publication venue, not expert suitability or acceptance probability.'}
    path = output / 'manifest.json'
    if path.exists():
        if json.loads(path.read_text()) != manifest:
            raise ValueError('Frozen corpus changed; choose a new experiment directory')
        stored = json.loads((output / 'snapshot.json').read_text())
        if fingerprint(stored) != manifest['snapshot_sha256']:
            raise ValueError('Frozen snapshot checksum mismatch')
    else:
        atomic_json(output / 'snapshot.json', snapshot)
        atomic_json(path, manifest)
    return snapshot, manifest


def balanced_order(records, seed=0):
    """Nested, deterministic round-robin samples across journals and years."""
    by_journal = defaultdict(lambda: defaultdict(list))
    for row in records:
        by_journal[row['journal_id']][row.get('year', 0)].append(row)
    rng = random.Random(seed)
    queues = {}
    for journal in sorted(by_journal):
        years = by_journal[journal]
        for year in sorted(years):
            years[year].sort(key=lambda r: (r.get('doi', ''), r.get('title', '')))
            rng.shuffle(years[year])
        queues[journal] = []
        while any(years.values()):
            for year in sorted(years):
                if years[year]:
                    queues[journal].append(years[year].pop())
    order, ids = [], sorted(queues)
    while any(queues.values()):
        rng.shuffle(ids)
        for journal in ids:
            if queues[journal]:
                order.append(queues[journal].pop(0))
    return order


def ranking_metrics(records, rankings):
    if len(records) != len(rankings) or not records:
        raise ValueError('Metrics need nonempty aligned records and rankings')
    positions = [r.index(a['journal_id']) + 1 if a['journal_id'] in r else math.inf for a, r in zip(records, rankings)]
    def summarize(indexes):
        n = len(indexes)
        hits = sum(positions[i] <= 3 for i in indexes)
        p, z = hits / n, 1.959963984540054
        center = (p + z * z / (2 * n)) / (1 + z * z / n)
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        return {'n': n, 'hits_at_3': hits, 'hit_at_1': sum(positions[i] == 1 for i in indexes) / n,
                'hit_at_3': p, 'mrr': sum(1 / positions[i] for i in indexes) / n,
                'hit_at_3_wilson_95': [max(0, center - half), min(1, center + half)]}
    result = summarize(range(len(records)))
    for key in ('journal_id', 'collection_field', 'collection_scope_group', 'evaluation_field'):
        groups = defaultdict(list)
        for i, row in enumerate(records):
            groups[row.get(key) or 'unknown'].append(i)
        result['by_' + key] = {g: summarize(indexes) for g, indexes in sorted(groups.items())}
    result['macro_journal_hit_at_3'] = sum(v['hit_at_3'] for v in result['by_journal_id'].values()) / len(result['by_journal_id'])
    return result


def ranks_from_scores(scores, classes):
    np, _, _ = ml_dependencies()
    return [[classes[i] for i in order] for order in np.argsort(-scores, axis=1, kind='stable')]


def rank_fusion(linear, centroid, weight):
    np, _, _ = ml_dependencies()
    def reciprocal(scores):
        order = np.argsort(-scores, axis=1, kind='stable')
        ranks = np.empty_like(order)
        np.put_along_axis(ranks, order, np.arange(scores.shape[1])[None, :], axis=1)
        return 1 / (10.0 + ranks)
    return weight * reciprocal(linear) + (1 - weight) * reciprocal(centroid)


class VenueModel:
    """TF-IDF linear classifier plus journal centroids, without pickle loading."""
    def __init__(self, vectorizer, coefficients, intercept, centroids, classes, metadata):
        self.vectorizer, self.coefficients, self.intercept = vectorizer, coefficients, intercept
        self.centroids, self.classes, self.metadata = centroids, list(classes), metadata

    def component_scores(self, texts):
        names = [j['name'] for j in self.metadata['journals']]
        matrix = self.vectorizer.transform([blind_text(t, names) for t in texts])
        return matrix @ self.coefficients.T + self.intercept, matrix @ self.centroids.T

    def rank(self, texts):
        linear, centroid = self.component_scores(texts)
        return ranks_from_scores(rank_fusion(linear, centroid, self.metadata['linear_weight']), self.classes)

    def recommend(self, title, abstract, k=3):
        if k < 1 or k > len(self.classes):
            raise ValueError('k must lie within the trained candidate journal count')
        text = article_text({'title': title, 'abstract': abstract}, [j['name'] for j in self.metadata['journals']])
        if not self.vectorizer.transform([text]).nnz:
            raise ValueError('No usable mathematical text overlaps the trained vocabulary')
        journals = {j['journal_id']: j for j in self.metadata['journals']}
        return {'recommendations': [{'rank': rank, 'journal_id': jid, 'name': journals[jid]['name'],
                                    'official_url': journals[jid].get('official_url')} for rank, jid in enumerate(self.rank([text])[0][:k], 1)],
                'candidate_journals': len(self.classes), 'model_training_articles': self.metadata['training_articles'],
                'interpretation': 'Historical publication-venue affinity from title and abstract; not acceptance probability or expert suitability.',
                'coverage': 'Restricted to the candidate journals in this model. Other journals are not evaluated.',
                'model_id': self.metadata.get('protocol_sha256')}

    def save(self, directory):
        np, _, _ = ml_dependencies()
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path / 'weights.npz', coefficients=self.coefficients, intercept=self.intercept,
                            centroids=self.centroids, idf=self.vectorizer.idf_)
        payload = {'schema_version': 1, 'classes': self.classes, 'metadata': self.metadata,
                   'vocabulary': {word: int(index) for word, index in self.vectorizer.vocabulary_.items()}, 'vectorizer': vectorizer_config(),
                   'weights_sha256': hashlib.sha256((path / 'weights.npz').read_bytes()).hexdigest()}
        atomic_json(path / 'model.json', payload)

    @classmethod
    def load(cls, directory):
        np, TfidfVectorizer, _ = ml_dependencies()
        path = Path(directory)
        payload = json.loads((path / 'model.json').read_text())
        if payload['schema_version'] != 1 or payload['vectorizer'] != vectorizer_config():
            raise ValueError('Unsupported venue model format')
        if hashlib.sha256((path / 'weights.npz').read_bytes()).hexdigest() != payload['weights_sha256']:
            raise ValueError('Venue model weights checksum mismatch')
        config = vectorizer_config()
        config['ngram_range'] = tuple(config['ngram_range'])
        vectorizer = TfidfVectorizer(vocabulary=payload['vocabulary'], **config)
        with np.load(path / 'weights.npz', allow_pickle=False) as arrays:
            coef, intercept, centroids, idf = [arrays[k] for k in ('coefficients', 'intercept', 'centroids', 'idf')]
        n, d = len(payload['classes']), len(payload['vocabulary'])
        if (coef.shape != (n, d) or centroids.shape != (n, d) or intercept.shape != (n,) or idf.shape != (d,) or
                not all(np.isfinite(a).all() for a in (coef, intercept, centroids, idf)) or (idf <= 0).any()):
            raise ValueError('Invalid venue model array dimensions or values')
        if len(set(payload['classes'])) != n or set(payload['vocabulary'].values()) != set(range(d)):
            raise ValueError('Invalid model classes or vocabulary')
        if not 0 <= payload['metadata']['linear_weight'] <= 1:
            raise ValueError('Invalid fusion weight')
        vectorizer.idf_ = idf
        return cls(vectorizer, coef, intercept, centroids, payload['classes'], payload['metadata'])


def vectorizer_config():
    return {'ngram_range': [1, 2], 'min_df': 2, 'max_df': .98, 'max_features': 60000,
            'sublinear_tf': True, 'strip_accents': 'unicode', 'stop_words': 'english',
            'token_pattern': r'(?u)\b[^\W\d_][\w-]{2,}\b'}


def fit_components(records, journals, alpha, seed=0):
    np, TfidfVectorizer, SGDClassifier = ml_dependencies()
    names = [j['name'] for j in journals]
    config = vectorizer_config()
    config['ngram_range'] = tuple(config['ngram_range'])
    vectorizer = TfidfVectorizer(**config)
    matrix = vectorizer.fit_transform([article_text(r, names) for r in records])
    labels = [r['journal_id'] for r in records]
    estimator = SGDClassifier(loss='log_loss', alpha=alpha, max_iter=1500, tol=1e-5,
                              class_weight='balanced', random_state=seed)
    estimator.fit(matrix, labels)
    if len(estimator.classes_) < 3:
        raise ValueError('Venue training requires at least three journals')
    centroids = np.vstack([np.asarray(matrix[np.array(labels) == c].mean(axis=0)).ravel() for c in estimator.classes_])
    centroids /= np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-12)
    metadata = {'journals': journals, 'training_articles': len(records), 'alpha': alpha, 'seed': seed,
                'linear_weight': 1.0, 'training_sha256': fingerprint(records), 'text_features': 'title and abstract only',
                'label_semantics': 'Observed publication venue, not expert suitability; alternatives remain unjudged.'}
    return VenueModel(vectorizer, estimator.coef_, estimator.intercept_, centroids, estimator.classes_.tolist(), metadata)
