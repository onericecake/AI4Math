"""Bounded public OpenAlex collection with journal/year quotas and resumable pages."""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .corpus import eligible_research, fingerprint, normalize_doi, normalize_date
from .harvest import atomic_json

# Collection design, not expert suitability labels or a journal quality ranking.
STRATA = {
    'generalist': [2531, 465, 554, 290, 411, 2579, 393, 744, 9591, 311, 500, 1206, 623],
    'algebra_number_theory': [473, 5004, 512, 1917, 1605, 518],
    'combinatorics': [9185, 1828, 69, 480],
    'geometry_topology': [485, 2395, 6180, 1418],
    'analysis_pde': [492, 484, 1897, 1566, 2184],
    'probability_statistics': [318, 1080, 1642, 2165, 319, 6214, 2481],
    'numerical_applied': [610, 708, 1843, 1637],
    'optimization': [1796, 1746, 563, 515],
    'mathematical_physics': [3352, 63, 2684],
}


def broad_training_plan(catalog):
    by_id = {j['journal_id']: j for j in catalog['journals']}
    journals = []
    for field, serials in STRATA.items():
        for serial in serials:
            journal = dict(by_id['zbmath-serial-%d' % serial])
            journal.update(collection_field=field, collection_scope_group='generalist' if field == 'generalist' else 'specialist_or_multifield')
            journals.append(journal)
    return {'schema_version': 1, 'journals': journals,
            'year_quotas': {'2020': 60, '2021': 60, '2022': 60, '2023': 60, '2024': 20, '2025': 20},
            'train_end': '2023-12-31', 'validation_end': '2024-12-31',
            'minimum_abstract_words': 35, 'maximum_pages_per_job': 10,
            'maximum_articles': len(journals) * 280,
            'selection': 'Fixed 50-journal collection design spanning nine strata; equal per-journal/year quotas; earliest eligible publication dates, never citation order.',
            'scope_group_provenance': 'Analyst collection strata based on registry journal identity and scope; not expert manuscript judgments.',
            'label_semantics': 'Observed publication venue only. Alternative journals are unjudged for suitability.',
            'temporal_semantics': 'Publication-year holdout using current metadata snapshots; not a historical submission-time simulation.'}


def reconstruct_abstract(index):
    if not isinstance(index, dict) or not index:
        return ''
    positions = {}
    for word, indexes in index.items():
        if not isinstance(word, str) or not isinstance(indexes, list):
            return ''
        for position in indexes:
            if type(position) is not int or position < 0 or position > 20000 or position in positions:
                return ''
            positions[position] = word
    if not positions or sorted(positions) != list(range(len(positions))):
        return ''
    return ' '.join(positions[i] for i in range(len(positions)))


def normalize_openalex(work, journal, year, observed, minimum_words=35):
    location = work.get('primary_location') or {}
    source = location.get('source') or {}
    # Match the source identity, not a mention of a journal elsewhere in metadata.
    if source.get('type') != 'journal' or journal['issn_l'] not in (source.get('issn') or []):
        return None, 'source_mismatch'
    if work.get('publication_year') != year or work.get('is_retracted') or work.get('type') != 'article':
        return None, 'type_year_or_retraction'
    doi = normalize_doi(work.get('doi'))
    title = work.get('title') or ''
    abstract = reconstruct_abstract(work.get('abstract_inverted_index'))
    if not re.fullmatch(r'10\.\d{4,9}/\S+', doi) or not title or len(abstract.split()) < minimum_words:
        return None, 'missing_identity_or_short_abstract'
    try:
        published = normalize_date(work.get('publication_date'))
    except ValueError:
        published = ''
    if not re.fullmatch(r'https://openalex.org/W\d+', str(work.get('id', ''))) or not published or int(published[:4]) != year:
        return None, 'invalid_id_or_date'
    if not eligible_research({'title': title, 'article_type': 'research article'}) or re.search(r'\b(editorial|preface|correction|corrections|book review)\b', title, re.I):
        return None, 'non_research'
    topic = work.get('primary_topic') or {}
    return {'article_id': work['id'].rsplit('/', 1)[-1], 'openalex_id': work['id'],
            'journal_id': journal['journal_id'], 'doi': doi, 'title': title, 'abstract': abstract,
            'year': year, 'available_date': published, 'metadata_available_date': observed,
            'article_type': 'research article', 'article_type_basis': 'OpenAlex article in a journal, minus explicit corrections/editorials; not individual peer-review verification',
            'source_url': location.get('landing_page_url') or 'https://doi.org/' + doi,
            'metadata_source_url': work['id'].replace('https://openalex.org/', 'https://api.openalex.org/'),
            'source': 'openalex', 'authors': [a['author']['display_name'] for a in work.get('authorships', []) if a.get('author', {}).get('display_name')],
            'msc_codes': [], 'msc_provenance': 'OpenAlex topics are not MSC codes',
            'openalex_primary_topic': topic, 'evaluation_field': (topic.get('subfield') or {}).get('display_name', 'unknown'),
            'collection_field': journal.get('collection_field', 'unknown'),
            'collection_scope_group': journal.get('collection_scope_group', 'unknown'),
            'source_issns': source.get('issn'), 'source_openalex_id': source.get('id'),
            'language': work.get('language'), 'license': location.get('license') or '',
            'metadata_license': 'CC0', 'rights_note': 'OpenAlex metadata is CC0; article/abstract rights remain with original rights holders. No full text downloaded.',
            'abstract_provenance': 'Reconstructed from the OpenAlex positional inverted index, not an AI summary',
            'observed_publication_venue': True}, None


class OpenAlexClient:
    def __init__(self, timeout=30, retries=2, interval=.12):
        self.timeout, self.retries, self.interval = timeout, retries, interval

    def get(self, url):
        for attempt in range(self.retries + 1):
            time.sleep(self.interval)
            try:
                request = Request(url, headers={'User-Agent': 'AI4Math-journal-matcher/0.3', 'Accept': 'application/json'})
                with urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code not in {408, 429, 500, 502, 503, 504} or attempt == self.retries:
                    raise RuntimeError('OpenAlex HTTP %d; checkpoint retained' % error.code) from error
                retry = error.headers.get('Retry-After', '')
                time.sleep(min(30, float(retry) if retry.isdigit() else 2 ** attempt))
            except (URLError, TimeoutError) as error:
                if attempt == self.retries:
                    raise RuntimeError('OpenAlex connection failed; checkpoint retained') from error
                time.sleep(2 ** attempt)


def validate_plan(plan):
    journals, quotas = plan.get('journals', []), plan.get('year_quotas', {})
    if not journals or len(journals) > 200 or not quotas:
        raise ValueError('A bounded nonempty journal/year plan is required')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', j.get('journal_id', '')) or
           not re.fullmatch(r'\d{4}-[\dXx]{4}', j.get('issn_l', '')) for j in journals):
        raise ValueError('Invalid journal identity or ISSN')
    if len({j['journal_id'] for j in journals}) != len(journals) or len({j['issn_l'] for j in journals}) != len(journals):
        raise ValueError('Duplicate journals in plan')
    if any(not re.fullmatch(r'\d{4}', y) or not 1900 <= int(y) <= date.today().year or
           type(q) is not int or not 0 <= q <= 1000 for y, q in quotas.items()):
        raise ValueError('Invalid year or article quota')
    if not 1 <= plan.get('maximum_pages_per_job', 0) <= 50 or not 1 <= plan.get('minimum_abstract_words', 0) <= 1000:
        raise ValueError('Invalid page or abstract bounds')
    if not 0 < len(journals) * sum(quotas.values()) <= 200000:
        raise ValueError('Collection exceeds the bounded article limit')


def harvest_openalex(plan, output_dir, client=None, max_jobs=None):
    validate_plan(plan)
    client = client or OpenAlexClient()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / 'checkpoint.json'
    plan_hash = fingerprint(plan)
    state = json.loads(state_path.read_text()) if state_path.exists() else {'plan_sha256': plan_hash, 'jobs': {}}
    if state['plan_sha256'] != plan_hash:
        raise ValueError('Plan differs from checkpoint; use a new output directory')
    jobs_done = 0
    selected_fields = 'id,doi,title,type,publication_year,publication_date,primary_location,abstract_inverted_index,primary_topic,is_retracted,authorships,language'
    for journal in plan['journals']:
        for raw_year, quota in sorted(plan['year_quotas'].items()):
            year = int(raw_year)
            key = '%s-%d' % (journal['journal_id'], year)
            job = state['jobs'].setdefault(key, {'cursor': '*', 'page': 0, 'complete': quota == 0, 'rejected': {}, 'quota': quota})
            records_path = output / 'records' / (key + '.json')
            records = json.loads(records_path.read_text()) if records_path.exists() else []
            if job['complete']:
                continue
            if max_jobs is not None and jobs_done >= max_jobs:
                atomic_json(state_path, state)
                return {'complete': False, 'jobs_processed': jobs_done}
            while not job['complete']:
                params = {'filter': 'primary_location.source.issn:%s,publication_year:%d,has_abstract:true,type:article,is_retracted:false' % (journal['issn_l'], year),
                          'sort': 'publication_date:asc', 'per_page': min(100, max(2 * (quota - len(records)), 20)),
                          'cursor': job['cursor'], 'select': selected_fields}
                url = 'https://api.openalex.org/works?' + urlencode(params)
                cache = output / 'pages' / (fingerprint(url) + '.json')
                try:
                    if cache.exists():
                        response = json.loads(cache.read_text())
                    else:
                        response = client.get(url)
                        response['_observed_on'] = date.today().isoformat()
                        response['_request_url'] = url
                        atomic_json(cache, response)
                    items = response['results']
                    observed = response['_observed_on']
                    page_hash = fingerprint(items)
                    if items and page_hash in job.get('seen_pages', []):
                        raise RuntimeError('Repeated OpenAlex page; checkpoint retained')
                    known = {r['doi'] for r in records}
                    for work in items:
                        record, reason = normalize_openalex(work, journal, year, observed, plan['minimum_abstract_words'])
                        if reason:
                            job['rejected'][reason] = job['rejected'].get(reason, 0) + 1
                        elif record['doi'] not in known:
                            record['raw_page_sha256'] = fingerprint(response)
                            records.append(record)
                            known.add(record['doi'])
                        if len(records) >= quota:
                            break
                    job.setdefault('seen_pages', []).append(page_hash)
                    job['page'] += 1
                    job['cursor'] = response.get('meta', {}).get('next_cursor')
                    job['complete'] = len(records) >= quota or not items or not job['cursor'] or job['page'] >= plan['maximum_pages_per_job']
                    job['accepted'] = len(records)
                    job['available_at_source'] = response.get('meta', {}).get('count')
                    atomic_json(records_path, records)
                    atomic_json(state_path, state)
                except Exception:
                    # The persisted checkpoint precedes this page. Cached pages
                    # and DOI deduplication make replay safe after interruption.
                    if not state_path.exists():
                        atomic_json(state_path, {'plan_sha256': plan_hash, 'jobs': {}})
                    raise
            jobs_done += 1
            print(key, '%d/%d' % (len(records), quota), flush=True)
    articles = []
    for journal in plan['journals']:
        for year in plan['year_quotas']:
            path = output / 'records' / ('%s-%s.json' % (journal['journal_id'], year))
            articles.extend(json.loads(path.read_text()) if path.exists() else [])
    corpus = {'journals': plan['journals'], 'articles': articles, 'journal_msc_stats': [],
              'provenance': {'source': 'OpenAlex', 'plan_sha256': plan_hash, 'retrieved_on': date.today().isoformat(),
                             'complete': True, 'label_semantics': plan['label_semantics']}}
    atomic_json(output / 'catalog.json', corpus)
    summary = {'articles': len(articles), 'journals': len({a['journal_id'] for a in articles}),
               'by_year': dict(Counter(a['year'] for a in articles)), 'jobs': len(state['jobs']),
               'complete': True, 'quota_shortfalls': {k: j['quota'] - j.get('accepted', 0) for k, j in state['jobs'].items() if j.get('accepted', 0) < j['quota']}}
    atomic_json(output / 'summary.json', summary)
    return summary
