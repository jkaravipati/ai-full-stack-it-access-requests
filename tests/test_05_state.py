import copy
import json
from tests.support import OfflineTest, ROOT, source, reply, ScriptedProvider


class StateTests(OfflineTest):
    def engine(self, provider):
        from access_intake.engine import Intake
        return Intake(self.dir / 'state.sqlite3', provider=provider)

    def test_T22_current_envelopes_document_independence_and_batch_absence(self):
        from access_intake.providers import MockProvider
        e=self.engine(MockProvider(ROOT/'tests/mock_responses'))
        e.ingest([source(1),source(5)])
        e.ingest([source(1)])
        rows=e.store.current()
        self.assertEqual({r['document_id'] for r in rows},{'IT-001.json','IT-005.json'})
        self.assertEqual(rows[1]['next_action'],'confirm-withdrawal')
        second=self.variant(source(1).message,'second.json')
        e2=self.engine(ScriptedProvider(reply(1)))
        e2.ingest([second])
        self.assertEqual(len(e2.store.current()),3)
        self.assertEqual(e2.store.inspect('second.json')['extraction']['request_id'],'IT-001')
        self.assertEqual(e2.store.inspect('second.json')['next_action'],'clarify')
        for row in e.store.current():
            for field in ['document_id','source_sha256','extraction','status','owner','next_action','error','response_source','attempt_id','processing_fingerprint','policy_version']:
                self.assertIn(field,row)

    def test_T23_unchanged_rerun_reuses_one_current_result(self):
        p=ScriptedProvider(reply(1))
        e=self.engine(p)
        e.ingest([source(1)])
        first=e.store.inspect('IT-001.json')
        e.ingest([source(1)])
        self.assertEqual(p.calls,['extraction'])
        self.assertEqual(e.store.inspect('IT-001.json')['attempt_id'],first['attempt_id'])
        self.assertEqual(len(e.store.history('IT-001.json')),1)

    def test_T24_changed_source_preserves_old_hash_and_history(self):
        from access_intake.providers import MockProvider
        from access_intake.validation import load_source
        e=self.engine(MockProvider(ROOT/'tests/mock_responses'))
        e.ingest([source(1)])
        old=e.store.inspect('IT-001.json')
        e.ingest([load_source(ROOT/'tests/inputs/changed-end/IT-001.json')])
        current=e.store.inspect('IT-001.json')
        self.assertEqual(current['extraction']['end_date'],'2026-11-07')
        self.assertNotEqual(current['source_sha256'],old['source_sha256'])
        self.assertEqual(e.store.history('IT-001.json')[0]['result']['source_sha256'],old['source_sha256'])
        self.assertEqual(len(e.store.history('IT-001.json')),2)

    def test_T25_failed_retry_after_success_retains_valid_result(self):
        from access_intake.providers import ProviderError
        p=ScriptedProvider(reply(1),ProviderError('http_503','Scripted saved service failure.'))
        e=self.engine(p)
        e.ingest([source(1)])
        e.retry('IT-001.json')
        current=e.store.inspect('IT-001.json')
        self.assertEqual(current['status'],'error')
        self.assertIsNone(current['extraction'])
        self.assertEqual(current['next_action'],'retry-extraction')
        history=e.store.history('IT-001.json')
        self.assertEqual(history[0]['result']['extraction']['permission'],'read')
        self.assertGreater(current['target_generation'],history[0]['target_generation'])
        self.assertIn('--state',current['error']['retry_command'])
        e.ingest([source(1)])
        self.assertEqual(len(p.calls),2)
        e.resume()
        self.assertEqual(len(p.calls),2)

    def test_T26_configuration_policy_and_byte_changes_refresh(self):
        p=ScriptedProvider(reply(1),reply(1),reply(1),reply(1))
        e=self.engine(p)
        e.ingest([source(1)])
        p.config=dict(p.config,model='offline-test-model-2')
        e.ingest([source(1)])
        policy=self.dir/'policy.md'
        policy.write_text((ROOT/'materials/office-policy.md').read_text()+'\nVersion note.\n')
        e.policy_path=policy
        e.ingest([source(1)])
        raw=source(1).raw+b'\n'
        from access_intake.validation import load_source
        e.ingest([load_source('IT-001.json',raw)])
        self.assertEqual(len(e.store.history('IT-001.json')),4)
        self.assertEqual(len(p.calls),4)
        e.workers=1
        e.ingest([load_source('IT-001.json',raw)])
        self.assertEqual(len(p.calls),4)
        history=e.store.history('IT-001.json')
        self.assertNotEqual(history[0]['processing_fingerprint'],history[1]['processing_fingerprint'])
        self.assertNotEqual(history[1]['result']['policy_version'],history[2]['result']['policy_version'])

    def test_failed_changed_source_never_borrows_previous_extraction(self):
        from access_intake.providers import ProviderError
        from access_intake.validation import load_source
        descriptor=json.loads((ROOT/'tests/mock_responses/provider.http-503.json').read_text())
        p=ScriptedProvider(reply(1),ProviderError('http_'+str(descriptor['status']),'Saved HTTP failure scenario.'))
        e=self.engine(p)
        e.ingest([source(1)])
        changed=load_source(ROOT/'tests/inputs/changed-end/IT-001.json')
        e.ingest([changed])
        current=e.store.inspect('IT-001.json')
        self.assertEqual(current['source_sha256'],changed.source_sha256)
        self.assertIsNone(current['extraction'])
        self.assertEqual(current['status'],'error')
        old=e.store.history('IT-001.json')[0]['result']
        self.assertEqual(old['source_sha256'],source(1).source_sha256)
        self.assertEqual(old['extraction']['end_date'],'2026-11-06')
