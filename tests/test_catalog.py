import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from catalog import ROOT, LEVELS, LICENSE, append_pack, due, read, source_url, validate, validate_word
from dictionary import parse_article
from update import generate, make_card

HTML = '''<h2 id="English">English</h2><h3>Pronunciation</h3><ul>
<li>(Received Pronunciation) IPA: <span class="IPA">/ˈbɒrəʊ/</span></li>
<li>(General American) IPA: <span class="IPA">/ˈbɑɹoʊ/</span></li></ul>
<h3>Noun</h3><ol><li>A temporary thing.<dl><dd>This example must be excluded.</dd><dd><div class="h-usage-example"><i class="e-example" lang="en">The borrow is due tomorrow.</i></div></dd></dl></li></ol>
<h4>Translations</h4><table class="translations" data-gloss="a temporary thing"><tr><td><ul><li>Russian: <span lang="ru">вещь</span></li></ul></td></tr></table>
<h3>Verb</h3><ol><li>To receive something for temporary use.<dl><dd><div class="h-usage-example"><i class="e-example" lang="en">May I borrow this item?</i></div></dd></dl></li><li>(obsolete) An old meaning.</li></ol>
<h4>Translations</h4><table class="translations" data-gloss="to receive for temporary use"><tr><td><ul><li>Russian: <span lang="ru">одолжи́ть</span></li></ul></td></tr></table>
<h2 id="Other">Other language</h2><h3>Noun</h3><ol><li>A different language meaning.</li></ol>'''

def card(word, level, today=dt.date(2026, 10, 30)):
    return {'id': f'pack-{today:%Y%m%d}-{level.lower()}-{word}', 'word': word, 'level': level, 'pos': 'verb', 'translation': 'взять на время', 'definition': 'To use an item and return it later.', 'example': f'May I {word} this item?', 'collocation': f'{word} a book', 'topic': 'Предметы', 'levelReason': 'An approximate educational level.', 'pronunciation': {'uk': '/ˈbɒrəʊ/', 'us': '/ˈbɑɹoʊ/'}, 'source': {'name': 'Wiktionary', 'url': source_url(word), 'checkedOn': today.isoformat(), 'license': 'CC BY-SA 4.0', 'licenseUrl': LICENSE}}

def draft_for(word, level):
    sample = card(word, level)
    return {'suitable': True, 'senseIndex': 1, 'translationIndex': 0, 'exampleIndex': 0, 'topic': 'everyday', **{k: sample[k] for k in ('collocation', 'levelReason')}}

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = read(ROOT / 'data/migration-baseline.json')
        self.base = read(ROOT / 'data/base-words.json')
        self.date = dt.date(2026, 10, 30)

    def test_migration_preserves_every_old_card(self):
        current = validate(read(ROOT / 'data/catalog.json'), self.catalog)
        self.assertGreaterEqual(len(current['words']), 35)
        self.assertEqual(len(self.base), 100)

    def test_changed_or_deleted_old_word_is_rejected(self):
        for mutation in ('remove', 'change'):
            altered = copy.deepcopy(self.catalog); altered['revision'] += 1
            if mutation == 'remove': altered['words'].pop()
            else: altered['words'][0]['word'] = 'altered'
            with self.assertRaises(ValueError): validate(altered, self.catalog)

    def test_revisions_and_pack_membership(self):
        for mutation in ('rollback', 'missing-member', 'duplicate-word', 'duplicate-pack'):
            altered = copy.deepcopy(self.catalog)
            if mutation == 'rollback': altered['revision'] = 1
            if mutation == 'missing-member': altered['packs'][0]['wordIds'].append('pack-absent')
            if mutation == 'duplicate-word': altered['words'].append(altered['words'][0])
            if mutation == 'duplicate-pack': altered['packs'].append(altered['packs'][0])
            with self.assertRaises(ValueError): validate(altered, self.catalog)

    def test_balanced_atomic_append_and_retry(self):
        words = [card(w, level) for w, level in zip(('testalpha', 'testbeta', 'testgamma', 'testdelta', 'testomega'), LEVELS)]
        new = append_pack(self.catalog, 'daily', self.date, words, self.base)
        self.assertEqual(len(new['words']), 40)
        self.assertEqual(len(self.catalog['words']), 35)
        self.assertEqual(new['revision'], 3)
        self.assertEqual(due(new, self.date), [])
        with self.assertRaises(ValueError): append_pack(new, 'daily', self.date, words, self.base)
        with self.assertRaises(ValueError): append_pack(self.catalog, 'daily', self.date, words[:-1], self.base)

    def test_base_dedup_ignores_level(self):
        words = [card(w, level) for w, level in zip((self.base[0]['word'], 'mention', 'outcome', 'elusive', 'obdurate'), LEVELS)]
        with self.assertRaises(ValueError): append_pack(self.catalog, 'daily', self.date, words, self.base)

    def test_legacy_daily_and_weekly_schedule(self):
        self.assertEqual(due(self.catalog, dt.date(2026, 10, 29)), [])
        self.assertEqual(due(self.catalog, dt.date(2026, 11, 2)), ['daily', 'weekly'])
        self.assertEqual(due(self.catalog, self.date), ['daily'])

    def test_new_word_requires_attributed_ipa_and_real_source_url(self):
        original = card('borrow', 'A2')
        validate_word(original, new=True)
        for field in ('pronunciation', 'source', 'levelReason'):
            altered = copy.deepcopy(original); del altered[field]
            with self.assertRaises((ValueError, KeyError)): validate_word(altered, new=True)
        for url in ('http://en.wiktionary.org/wiki/borrow#English', 'https://evil.example/wiki/borrow', source_url('other')):
            altered = copy.deepcopy(original); altered['source']['url'] = url
            with self.assertRaises(ValueError): validate_word(altered, new=True)
        original['pronunciation']['us'] = '<script>'
        with self.assertRaises(ValueError): validate_word(original, new=True)

    def test_parser_isolates_english_and_senses(self):
        parsed = parse_article(HTML, 'borrow')
        self.assertEqual(len(parsed['senses']), 2)
        self.assertNotIn('example', parsed['senses'][0]['definition'])
        self.assertEqual(parsed['senses'][1]['pos'], 'verb')
        self.assertEqual(parsed['senses'][0]['pronunciation']['us'], '/ˈbɑɹoʊ/')

    def test_parser_rejects_missing_accent_and_wrong_etymology(self):
        with self.assertRaises(ValueError): parse_article(HTML.replace('General American', 'Canadian'), 'borrow')
        with self.assertRaises(ValueError): parse_article(HTML.replace('id="English"', 'id="French"'), 'borrow')
        altered = HTML.replace('<h3>Pronunciation', '<h3>Etymology 1</h3><h3>Pronunciation').replace('<h3>Noun', '<h3>Etymology 2</h3><h3>Noun')
        with self.assertRaises(ValueError): parse_article(altered, 'borrow')

    def test_model_cannot_override_source_or_pronunciation(self):
        class FakeModel:
            def complete(self, task, data, schema):
                if 'suitable' in schema['properties']:
                    return {**draft_for('borrow', 'A2'), 'definition': 'Never return anything.', 'example': 'She can opportunity to travel.', 'translation': 'выдуманный перевод', 'pronunciation': {'uk': '/fake/'}, 'source': 'https://evil.example'}
                return {k: True for k in schema['properties']}
        result = make_card(FakeModel(), parse_article(HTML, 'borrow'), 'A2', self.date)
        self.assertEqual(result['pronunciation']['uk'], '/ˈbɒrəʊ/')
        self.assertEqual(result['source']['url'], source_url('borrow'))
        self.assertEqual(result['translation'], 'одолжить')
        self.assertEqual(result['example'], 'May I borrow this item?')
        self.assertEqual(result['exampleOrigin'], 'dictionary')
        self.assertEqual(result['definition'], 'To receive something for temporary use.')
        self.assertEqual(result['definitionOrigin'], 'dictionary')

    def test_russian_definitions_cannot_pass_validation(self):
        sample = card('borrow', 'A2')
        for field in ('definition', 'example', 'collocation', 'levelReason'):
            changed = copy.deepcopy(sample); changed[field] = 'Ошибка языка ' + changed[field]
            with self.assertRaises(ValueError): validate_word(changed, new=True)

    def test_russian_translation_must_exist_in_english_section(self):
        with self.assertRaises(ValueError): parse_article(HTML.replace('lang="ru"', 'lang="uk"'), 'borrow')
        parsed = parse_article(HTML, 'borrow')
        self.assertEqual(parsed['senses'][1]['translations'][0]['terms'], ['одолжить'])

    def test_failed_review_cannot_publish(self):
        class BadModel:
            def complete(self, task, data, schema):
                if 'suitable' in schema['properties']:
                    return {'suitable': False}
                return {k: False for k in schema['properties']}
        with self.assertRaises(ValueError): make_card(BadModel(), parse_article(HTML, 'borrow'), 'A2', self.date)

    def test_invalid_example_index_gets_one_corrective_attempt(self):
        class RepairModel:
            calls = 0
            def complete(self, task, data, schema):
                self.calls += 1
                if 'suitable' not in schema['properties']:
                    return {k: True for k in schema['properties']}
                draft = draft_for('borrow', 'A2')
                if self.calls == 1:
                    draft['exampleIndex'] = 99
                else:
                    assert data['previousValidationError'] == 'No dictionary example selected'
                return draft
        model = RepairModel()
        result = make_card(model, parse_article(HTML, 'borrow'), 'A2', self.date)
        self.assertIn('borrow', result['example'])
        self.assertEqual(model.calls, 3)

    def test_invalid_second_attempt_still_rejected(self):
        class InvalidModel:
            calls = 0
            def complete(self, task, data, schema):
                self.calls += 1
                return {**draft_for('borrow', 'A2'), 'exampleIndex': 99}
        model = InvalidModel()
        with self.assertRaises(ValueError):
            make_card(model, parse_article(HTML, 'borrow'), 'A2', self.date)
        self.assertEqual(model.calls, 2)

    def test_long_optional_explanation_does_not_discard_dictionary_card(self):
        class VerboseModel:
            def complete(self, task, data, schema):
                if 'suitable' in schema['properties']:
                    return {**draft_for('borrow', 'A2'), 'levelReason': 'A long explanation. ' * 30}
                return {k: True for k in schema['properties']}
        result = make_card(VerboseModel(), parse_article(HTML, 'borrow'), 'A2', self.date)
        self.assertLessEqual(len(result['levelReason']), 200)
        self.assertIn('not an official CEFR', result['levelReason'])
        self.assertEqual(result['definition'], 'To receive something for temporary use.')

    def test_network_failure_leaves_catalog_unchanged(self):
        before = json.dumps(self.catalog, sort_keys=True)
        def unavailable(*args): raise TimeoutError('offline')
        with self.assertRaises(TimeoutError): generate(self.catalog, self.base, None, self.date, 'owner/repo', fetch=unavailable)
        self.assertEqual(json.dumps(self.catalog, sort_keys=True), before)

    def test_full_daily_and_monday_pipelines(self):
        class AcceptedModel:
            def complete(self, task, data, schema):
                if 'suitable' in schema['properties']:
                    return draft_for(data['article']['word'], data['level'])
                return {k: True for k in schema['properties']}
        for day, count in ((self.date, 5), (dt.date(2026, 11, 2), 30)):
            with self.subTest(day=day), patch('builtins.print'):
                result = generate(self.catalog, self.base, AcceptedModel(), day, 'owner/repo', fetch=lambda word, repo: parse_article(HTML.replace('borrow', word), word))
                self.assertEqual(len(result['words']), 35 + count)
                self.assertEqual(due(result, day), [])
                validate(result, self.catalog)

    def test_failed_second_level_does_not_leave_partial_pack(self):
        class PartialModel:
            def complete(self, task, data, schema):
                if 'suitable' in schema['properties']:
                    if data['level'] != 'A2':
                        raise TimeoutError('model unavailable')
                    return draft_for(data['article']['word'], 'A2')
                return {k: True for k in schema['properties']}
        before = copy.deepcopy(self.catalog)
        with patch('builtins.print'), self.assertRaises(TimeoutError):
            generate(self.catalog, self.base, PartialModel(), self.date, 'owner/repo', fetch=lambda word, repo: parse_article(HTML.replace('borrow', word), word))
        self.assertEqual(self.catalog, before)

    def test_missing_dictionary_examples_are_not_invented(self):
        with self.assertRaises(ValueError):
            parse_article(HTML.replace('h-usage-example', 'quotation'), 'borrow')

if __name__ == '__main__':
    unittest.main()
