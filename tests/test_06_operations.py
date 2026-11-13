import json
import subprocess
import sys
import threading
import time
from tests.support import OfflineTest, ROOT, source, reply, ScriptedProvider


class OperationsTests(OfflineTest):
    def test_T27_latest_accepted_generation_wins_and_pending_is_explicit(self):
        from access_intake.engine import Intake
        from access_intake.providers import MockProvider
        from access_intake.validation import load_source
        from access_intake.pipeline import process_message
        p=MockProvider(ROOT/'tests/mock_responses')
        changed=load_source(ROOT/'tests/inputs/changed-end/IT-001.json')
        for older_finishes_first in [True,False]:
            e=Intake(self.dir/f'{older_finishes_first}.sqlite3',provider=p)
            old_id,_=e.accept(source(1))
            old_claim=e.store.claim(old_id)
            new_id,_=e.accept(changed)
            if older_finishes_first:
                e.store.finish(old_id,old_claim['token'],process_message(source(1),p))
            e.process(new_id)
            if not older_finishes_first:
                e.store.finish(old_id,old_claim['token'],process_message(source(1),p))
            current=e.store.inspect('IT-001.json')
            self.assertEqual(current['extraction']['end_date'],'2026-11-07')
            self.assertEqual(current['source_sha256'],changed.source_sha256)
            self.assertEqual(e.store.history('IT-001.json')[0]['processing_state'],'superseded')
            e.retry('IT-001.json',run=False)
            pending=e.store.inspect('IT-001.json')
            self.assertEqual(pending['processing_state'],'queued')
            self.assertIsNone(pending['next_action'])
            self.assertEqual(pending['previous']['attempt_id'],current['attempt_id'])

    def test_T28_slow_request_does_not_hide_completed_work_and_leases_recover(self):
        from access_intake.engine import Intake
        released=threading.Event()
        def hook(op,message,context):
            if context['document_id']=='IT-002.json': released.wait(3)
            return reply(int(context['document_id'][3:6]))
        e=Intake(self.dir/'slow.sqlite3',provider=ScriptedProvider(hook=hook))
        worker=threading.Thread(target=lambda:e.ingest([source(1),source(2),source(18)]),daemon=True)
        worker.start()
        try:
            until=time.monotonic()+1
            while time.monotonic()<until:
                record=e.store.inspect('IT-018.json')
                if record and record['processing_state']=='succeeded': break
                time.sleep(.01)
            self.assertEqual(e.store.inspect('IT-018.json')['next_action'],'review-request')
            self.assertEqual(e.store.inspect('IT-002.json')['processing_state'],'running')
        finally:
            released.set()
            worker.join(4)
        self.assertFalse(worker.is_alive())
        clock=[1000.0]
        e=Intake(self.dir/'leases.sqlite3',provider=ScriptedProvider(reply(1)),clock=lambda:clock[0])
        attempt,_=e.accept(source(1))
        old=e.store.claim(attempt)
        self.assertIsNone(e.store.claim(attempt))
        clock[0]+=30
        self.assertTrue(e.store.heartbeat(attempt,old['token']))
        clock[0]+=181
        new=e.store.claim(attempt)
        self.assertGreater(new['token'],old['token'])
        self.assertFalse(e.store.finish(attempt,old['token'],{'status':'review'}))

    def test_T29_rate_limit_outage_deadline_and_manual_retry(self):
        from access_intake.engine import Intake
        from access_intake.providers import ProviderError
        for code in ['http_429','http_503','connection_error']:
            p=ScriptedProvider(ProviderError(code,'Saved outage scenario.'),reply(1))
            e=Intake(self.dir/(code+'.db'),provider=p)
            e.ingest([source(1)])
            self.assertEqual(e.store.inspect('IT-001.json')['status'],'error')
            self.assertEqual(len(p.calls),1)
            e.retry('IT-001.json')
            self.assertEqual(e.store.inspect('IT-001.json')['next_action'],'review-request')
        release=threading.Event()
        p=ScriptedProvider(hook=lambda *args:(release.wait(2),reply(1))[1])
        e=Intake(self.dir/'deadline.db',provider=p,call_timeout=.05)
        started=time.monotonic()
        try:
            e.ingest([source(1)])
            self.assertLess(time.monotonic()-started,1)
            self.assertEqual(e.store.inspect('IT-001.json')['error']['code'],'timeout')
        finally: release.set()

    def test_T30_snapshot_export_refuses_pending_and_survives_partial_publication(self):
        from access_intake.engine import Intake
        e=Intake(self.dir/'export.db',provider=ScriptedProvider(reply(1),reply(1)))
        e.ingest([source(1)])
        output=self.dir/'outputs'
        first=e.store.export(output)
        generation=(output/'current').resolve()
        records=[json.loads(line) for line in (generation/'extractions.jsonl').read_text().splitlines()]
        queue=json.loads((generation/'queue.json').read_text())
        self.assertEqual(records[0]['source_sha256'],queue[0]['source_sha256'])
        self.assertEqual(records[0]['attempt_id'],queue[0]['attempt_id'])
        e.retry('IT-001.json',run=False)
        with self.assertRaisesRegex(ValueError,'unfinished'): e.store.export(output)
        e.resume()
        def fail(): raise OSError('Simulated write/publication interruption')
        with self.assertRaises(OSError): e.store.export(output,before_publish=fail)
        self.assertEqual((output/'current').resolve(),generation)
        second=e.store.export(output)
        self.assertGreater(second['generation'],first['generation'])
        self.assertTrue((output/'history.jsonl').read_text())

    def test_two_operator_processes_reuse_the_same_document(self):
        code='''
import sys
from tests.support import OfflineTest,ROOT,source
from access_intake.engine import Intake
from access_intake.providers import MockProvider
guard=OfflineTest(); guard.setUp()
try: Intake(sys.argv[1],provider=MockProvider(ROOT/'tests/mock_responses')).ingest([source(1)])
finally: guard.doCleanups()
'''
        path=self.dir/'processes.db'
        children=[subprocess.Popen([sys.executable,'-c',code,str(path)],cwd=ROOT,
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
        for child in children:
            out,err=child.communicate(timeout=10)
            self.assertEqual(child.returncode,0,err.decode())
        from access_intake.store import Store
        s=Store(path)
        self.assertEqual(len(s.current()),1)
        self.assertEqual(len(s.history('IT-001.json')),1)
