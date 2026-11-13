"""Step 4: real-adapter request/response behavior, entirely offline.

These tests are intentionally written before the provider implementation.
Saved responses are authored fixtures, not observations from a live provider.
"""
import json
import urllib.error

from tests.support import OfflineTest, ROOT, source


def saved(name):
    return json.loads((ROOT / 'tests/mock_responses' / name).read_text())


def saved_failure(name):
    descriptor = saved(name)
    if descriptor['kind'] == 'http':
        return urllib.error.HTTPError('https://example.invalid', descriptor['status'],
                                      descriptor['message'], {}, None)
    if descriptor['kind'] == 'connection':
        return urllib.error.URLError(descriptor['message'])
    if descriptor['kind'] == 'timeout':
        return TimeoutError(descriptor['message'])
    raise AssertionError('Unsupported saved failure descriptor')


class ProviderTests(OfflineTest):
    def adapter(self, responses, **config):
        from access_intake.providers import OpenAIProvider
        self.requests = []
        sequence = iter(responses)

        def transport(url, headers, request, timeout):
            self.requests.append({'url': url, 'headers': headers,
                                  'request': request, 'timeout': timeout})
            result = next(sequence)
            if isinstance(result, Exception):
                raise result
            return result

        return OpenAIProvider(config=config, transport=transport,
                              credential_getter=lambda: 'test-only-credential', origin='mock')

    def run_message(self, number, responses, **config):
        from access_intake.pipeline import process_message
        return process_message(source(number), self.adapter(responses, **config))

    def assert_error(self, result, stage, code=None):
        self.assertEqual((result['status'], result['owner'], result['next_action']),
                         ('error', 'IT Service Desk', 'retry-extraction'))
        self.assertIsNone(result['extraction'])
        self.assertEqual(result['error']['stage'], stage)
        if code is not None:
            self.assertEqual(result['error']['code'], code)
        self.assertTrue(result['error']['retry_command'])
        self.assertNotIn('test-only-credential', json.dumps(result))

    def test_T17_both_requests_use_supported_configuration_and_mock_provenance(self):
        from access_intake.pipeline import process_message
        from access_intake.providers import OpenAIProvider
        extraction = saved('it-001.complete.json')
        provider = self.adapter([extraction])
        result = process_message(source(1), provider)
        self.assertEqual(result['next_action'], 'review-request')
        self.assertEqual(result['response_source'], 'mock')
        request = self.requests[0]
        self.assertEqual(request['url'], 'https://api.openai.com/v1/responses')
        data = request['request']
        self.assertEqual(data['model'], 'gpt-5.6-terra')
        self.assertEqual(data['reasoning'], {'effort': 'none'})
        self.assertEqual(data['max_output_tokens'], 4096)
        self.assertFalse(data['stream'])
        self.assertFalse(data['store'])
        self.assertEqual(data['tools'], [])
        self.assertNotIn('temperature', data)
        self.assertNotIn('top_p', data)
        self.assertEqual(data['text']['format']['type'], 'json_schema')
        self.assertTrue(data['text']['format']['strict'])
        self.assertEqual(data['input'][0]['role'], 'user')
        self.assertEqual(json.loads(data['input'][0]['content'])['message'], source(1).message)
        self.assertEqual(result['provider_calls'][0]['returned_model'], 'mock-model')
        self.assertTrue(result['provider_calls'][0]['response_received'])

        provider = self.adapter([saved('it-006.override.json'),
                                 saved('it-006.override-assessment.true.json')],
                                model='explicit-test-model', max_output_tokens=2048)
        result = process_message(source(6), provider)
        self.assertEqual(result['next_action'], 'inspect-message')
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.requests[1]['request']['model'], 'explicit-test-model')
        self.assertEqual(self.requests[1]['request']['max_output_tokens'], 2048)
        self.assertEqual(self.requests[1]['request']['text']['format']['name'],
                         'access_override_assessment')
        self.assertEqual([c['operation'] for c in result['provider_calls']],
                         ['extraction', 'override_assessment'])
        evidence = provider.request_evidence(source(6))
        self.assertNotIn('test-only-credential', json.dumps(evidence))
        self.assertIn('[REDACTED]', json.dumps(evidence))

        def forbidden(*args):
            raise AssertionError('Transport called without a credential')

        empty = OpenAIProvider(transport=forbidden, credential_getter=lambda: None, origin='mock')
        self.assert_error(process_message(source(1), empty), 'extraction', 'missing_api_key')

    def test_T18_invalid_output_and_invalid_assessment_fail_explicitly(self):
        for fixture in ['openai.it-001.invalid-json.json', 'openai.it-001.invalid-schema.json',
                        'openai.it-001.error-envelope.json', 'openai.it-001.missing-model.json']:
            with self.subTest(fixture=fixture):
                self.assert_error(self.run_message(1, [saved(fixture)]), 'extraction')
        for fixture in ['openai.it-006.assessment.invalid-json.json',
                        'openai.it-006.assessment.invalid-schema.json',
                        'openai.it-006.assessment.bad-evidence.json']:
            with self.subTest(fixture=fixture):
                self.assert_error(self.run_message(6, [saved('it-006.override.json'), saved(fixture)]),
                                  'override_assessment')

    def test_T19_provider_errors_are_actionable_for_both_operations(self):
        for number, preceding, stage in [(1, [], 'extraction'),
                                         (6, [saved('it-006.override.json')], 'override_assessment')]:
            for failure, code in [(saved_failure('provider.http-503.json'), 'http_503'),
                                  (saved_failure('provider.connection-error.json'), 'connection_error')]:
                with self.subTest(number=number, code=code):
                    self.assert_error(self.run_message(number, preceding + [failure]), stage, code)
                    self.assertEqual(len(self.requests), len(preceding) + 1)

    def test_T20_refusal_never_becomes_extraction_or_harmless_verdict(self):
        self.assert_error(self.run_message(1, [saved('openai.it-001.refusal.json')]),
                          'extraction', 'refusal')
        self.assert_error(self.run_message(6, [saved('it-006.override.json'),
                                             saved('openai.it-006.assessment.refusal.json')]),
                          'override_assessment', 'refusal')

    def test_T21_incomplete_cutoff_timeout_and_redaction_for_both_operations(self):
        for number, preceding, stage, fixture in [
                (1, [], 'extraction', 'openai.it-001.incomplete.json'),
                (6, [saved('it-006.override.json')], 'override_assessment',
                 'openai.it-006.assessment.incomplete.json')]:
            for response in [saved(fixture),
                             (ROOT / 'tests/mock_responses/openai.cutoff.txt').read_bytes(),
                             saved_failure('provider.timeout.json')]:
                with self.subTest(number=number, response_type=type(response).__name__):
                    self.assert_error(self.run_message(number, preceding + [response]), stage)
