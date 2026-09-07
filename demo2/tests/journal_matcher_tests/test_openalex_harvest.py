import copy
import json

import pytest

from journal_matcher.openalex_harvest import harvest_openalex, normalize_openalex, reconstruct_abstract


def work(number=1, year=2023):
    return {'id': 'https://openalex.org/W%d' % number, 'doi': 'https://doi.org/10.1234/example%d' % number,
            'title': 'A mathematical research article %d' % number, 'publication_year': year,
            'publication_date': '%d-01-02' % year, 'type': 'article', 'is_retracted': False,
            'primary_location': {'source': {'type': 'journal', 'issn': ['1234-5678']}},
            'abstract_inverted_index': {'mathematics': list(range(40))},
            'primary_topic': {'subfield': {'display_name': 'Algebra and Number Theory'}}}


JOURNAL = {'journal_id': 'j1', 'issn_l': '1234-5678', 'name': 'Example Journal'}


def plan():
    return {'journals': [JOURNAL], 'year_quotas': {'2023': 2}, 'minimum_abstract_words': 35,
            'maximum_pages_per_job': 3, 'label_semantics': 'Observed publication venue'}


def test_normalization_preserves_source_and_does_not_invent_msc():
    record, reason = normalize_openalex(work(), JOURNAL, 2023, '2026-09-07')
    assert reason is None
    assert record['doi'] == '10.1234/example1'
    assert record['msc_codes'] == []
    assert record['evaluation_field'] == 'Algebra and Number Theory'
    assert record['metadata_available_date'] == '2026-09-07'
    assert record['observed_publication_venue'] is True
    for change in ({'publication_year': 2024}, {'is_retracted': True}, {'title': 'Correction to a theorem'},
                   {'publication_date': '2023-99-04'}, {'doi': 'not-a-doi'}, {'id': 'bad'}):
        assert normalize_openalex(dict(work(), **change), JOURNAL, 2023, '2026-09-07')[0] is None
    wrong = copy.deepcopy(work())
    wrong['primary_location']['source']['issn'] = ['9999-0000']
    assert normalize_openalex(wrong, JOURNAL, 2023, '2026-09-07')[1] == 'source_mismatch'


def test_invalid_inverted_indexes_are_not_silently_reordered():
    assert reconstruct_abstract({'two': [1], 'one': [0, 2]}) == 'one two one'
    for index in ({'one': [1]}, {'a': [0], 'b': [0]}, {'a': [-1]}, {'a': [False]}, {'a': [20001]}):
        assert reconstruct_abstract(index) == ''


def test_collection_resumes_after_connection_failure_and_is_idempotent(tmp_path):
    class Client:
        def __init__(self):
            self.calls = 0
        def get(self, url):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError('connection interrupted')
            return {'results': [work(self.calls)], 'meta': {'next_cursor': 'page2' if self.calls == 1 else None, 'count': 2}}
    client = Client()
    with pytest.raises(RuntimeError, match='interrupted'):
        harvest_openalex(plan(), tmp_path, client)
    assert len(json.loads((tmp_path / 'records/j1-2023.json').read_text())) == 1
    result = harvest_openalex(plan(), tmp_path, client)
    assert result['articles'] == 2
    assert client.calls == 3
    assert harvest_openalex(plan(), tmp_path, client) == result
    assert client.calls == 3
    changed = dict(plan(), minimum_abstract_words=36)
    with pytest.raises(ValueError, match='differs'):
        harvest_openalex(changed, tmp_path, client)


def test_path_unsafe_and_duplicate_plans_are_rejected(tmp_path):
    for journals in ([dict(JOURNAL, journal_id='../outside')], [JOURNAL, JOURNAL]):
        with pytest.raises(ValueError):
            harvest_openalex(dict(plan(), journals=journals), tmp_path)
