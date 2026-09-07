import json
from pathlib import Path

from journal_matcher.catalog import JournalCatalog
from journal_matcher.corpus import duplicate_groups, select_reference_corpus
from journal_matcher.msc import MSCTaxonomy
from journal_matcher.prompts import journal_field_profile_prompt
from journal_matcher.retrieval import HybridRetriever
from journal_matcher.schemas import ArticleProfile, MSCClassification


DATA = Path(__file__).resolve().parents[2] / 'data/public-evidence-2026-09-07'


def test_collected_evidence_has_rights_provenance_and_no_target_versions():
    additions = json.loads((DATA / 'catalog.additions.json').read_text())
    articles = additions['articles']
    taxonomy = MSCTaxonomy.from_json(DATA.parent / 'msc2020.json')
    assert len(articles) == 60
    for article in articles:
        assert article['authors'] and article['abstract'] and article['doi']
        assert article['license'] in {'CC-BY-4.0', 'CC-BY-ND-4.0'}
        assert article['source_url'].startswith('https://')
        assert article['license_source_url'].startswith('https://')
        assert article['metadata_available_date'] == '2026-09-07'
        assert all(taxonomy.get(code) for code in article['msc_codes'])
        assert set(article['publisher_msc_codes']) == set(article['msc_codes'] + article['quarantined_msc_codes'])
        assert 'actual_journal_id' not in article and 'relevance' not in article
    targets = []
    for dataset in ('pilot', 'validation'):
        folder = DATA.parents[1] / 'benchmarks/focused-2026-09-07' / dataset
        labels = {r['paper_id']: r for r in json.loads((folder / 'labels.json').read_text())}
        targets.extend({**r, 'doi': labels[r['paper_id']].get('doi')} for r in json.loads((folder / 'cases.json').read_text()))
    groups = duplicate_groups(articles + targets)
    assert all(not (min(g) < 60 <= max(g)) for g in groups)
    assert not additions.get('journal_msc_stats')
    assert all(j['audience_breadth'] == j['technical_level'] == 'unknown' for j in additions['journals'])


def test_policy_and_abstract_attribution_reach_both_candidate_routes():
    journal = {'journal_id': 'broad', 'name': 'Broad Journal', 'scope_summary': 'Geometry and algebra',
               'scope_url': 'https://example.org/scope', 'scope_breadth': 'generalist',
               'editorial_evidence': [{'statement': 'Clear exposition for a wide readership.',
                 'source_url': 'https://example.org/scope', 'available_date': '2026-09-07', 'evidence_type': 'public_editorial_policy'}]}
    article = {'article_id': 'a', 'journal_id': 'broad', 'title': 'Symplectic geometry', 'abstract': 'Symplectic geometry and Hamiltonian actions.',
               'authors': ['A. Author'], 'license': 'CC-BY-4.0', 'license_url': 'https://creativecommons.org/licenses/by/4.0/', 'msc_codes': ['53D20']}
    with JournalCatalog(':memory:') as catalog:
        catalog.upsert_journal(journal)
        catalog.upsert_article(article)
        catalog.rebuild_statistics()
        for profile in [ArticleProfile(primary_msc=MSCClassification('53D20')),
                        ArticleProfile(retrieval_text='Symplectic geometry Hamiltonian actions')]:
            candidate = HybridRetriever(catalog).retrieve(profile)[0]
            assert candidate.editorial_evidence == journal['editorial_evidence']
            assert candidate.scope_breadth == 'generalist'
            assert candidate.audience_breadth == 'unknown'
            assert candidate.representative_articles[0].authors == ['A. Author']
            assert candidate.representative_articles[0].license == 'CC-BY-4.0'
            prompt = journal_field_profile_prompt(profile, candidate)
            assert 'https://example.org/scope' in prompt
            assert 'public_editorial_policy' in prompt


def test_temporal_filter_excludes_current_policies_even_with_old_registry():
    data = {'articles': [], 'journals': [{'journal_id': 'j', 'registry_available_date': '2020-01-01',
        'scope_summary': 'Current scope', 'scope_breadth': 'generalist', 'scope_available_date': '2026-09-07',
        'editorial_evidence': [{'statement': 'Old policy', 'available_date': '2020-01-01'},
                               {'statement': 'New policy', 'available_date': '2026-09-07'}, {'statement': 'Undated policy'}]}]}
    result, _ = select_reference_corpus(data, cutoff='2021-12-31')
    journal = result['journals'][0]
    assert journal['scope_breadth'] == 'unknown' and not journal['scope_summary']
    assert [e['statement'] for e in journal['editorial_evidence']] == ['Old policy']
