import hashlib
import json
from pathlib import Path
from tests.support import OfflineTest

ROOT = Path(__file__).resolve().parents[1]


class MockProviderTests(OfflineTest):
    def test_T01_fixture_provider_is_offline_and_counts_operations(self):
        from access_intake.providers import MockProvider
        raw = (ROOT / 'materials/requests/IT-001.json').read_bytes()
        context = {'document_id': 'IT-001.json', 'source_sha256': hashlib.sha256(raw).hexdigest()}
        provider = MockProvider(ROOT / 'tests/mock_responses')
        response = provider.call('extraction', json.loads(raw)['message'], context)
        self.assertEqual(response['status'], 'completed')
        self.assertEqual(provider.calls, ['extraction'])
        self.assertEqual(provider.response_source, 'mock')
        with self.assertRaisesRegex(Exception, 'fixture'):
            provider.call('extraction', 'changed', dict(context, source_sha256='changed'))
